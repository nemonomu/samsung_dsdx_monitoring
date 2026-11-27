"""Reuse completed daily retail cards only after checking their current source rows."""
import logging
from datetime import date, timedelta

from psycopg2 import Error

from apps.common.dx_schedules import load_collection_schedules
from apps.common.monitoring_cache import _backend, _has_error, _root, _value_digest
from apps.common.source_dates import source_date_sql
from apps.dx.dx_layer1.common.retail_batches import _scope
from apps.dx.dx_layer1.common.retail_verification import has_collection
from apps.dx.dx_layer1.siel_retail import jiomart
from apps.dx.dx_layer1.tse_retail.tse_retail_services import _configured_retailers
from .collection_revisions import batch_revision


logger = logging.getLogger(__name__)
# shortcut: Historical baselines refresh on the next Seoul day or manual refresh.
_TTL = 24 * 60 * 60


def source_revision(cursor, check, inspection_day=None):
    check_type = check['check_type']
    queries, params = [], []
    for category in check['categories']:
        product, day = category.get('product_line'), category.get('source_date')
        if check_type == 'tse_retail' and product:
            # TSE counts its selected inspection day directly.
            day = day or (str(inspection_day) if inspection_day else None)
        if not product or not day:
            return None
        try:
            source, _, condition, args = _scope(check_type, product, day)
        except (KeyError, ValueError):
            return None
        column = source.get('date_column', 'crawl_datetime')
        if check_type == 'retail' and source['product_key'] == 'tv':
            # SEA TV totals use the legacy range, with a separate original day for Costco.
            condition = f"(({column}::timestamp >= %s AND {column}::timestamp < %s) OR {source_date_sql(column)} = %s)"
            args = (day, str(date.fromisoformat(day) + timedelta(days=1)), day)
        if check_type == 'siel_retail' and jiomart.preview(day):
            condition = f"(({condition}) OR (batch_id = %s AND {column} = %s::timestamptz))"
            args = (*args, jiomart.TEST_BATCH, jiomart.TEST_TIMESTAMP)
        page_type = (
            check_type in ('siel_retail', 'seda_retail')
            or (check_type == 'retail' and source['product_key'] in ('ref', 'ldy'))
            or (check_type == 'seg_retail' and source.get('has_page_type', True))
        )
        fields = ['source.account_name']
        if source.get('has_redirect'):
            fields.append('source.redirect IS TRUE')
        if source.get('extra_rank_field'):
            fields.append(f"source.{source['extra_rank_field']} IS NOT NULL")
        revision = batch_revision(column, page_type=page_type, extra_fields=fields)
        queries.append(f"(SELECT {revision} FROM {source['table_name']} source WHERE {condition})")
        params.extend(args)

    cursor.execute('SAVEPOINT layer1_country_revision')
    try:
        cursor.execute('SELECT ' + ', '.join(queries), params)
        return tuple(cursor.fetchone())
    except Error:
        cursor.execute('ROLLBACK TO SAVEPOINT layer1_country_revision')
        logger.warning('Layer 1 source revision unavailable for %s', check_type, exc_info=True)
        return None
    finally:
        cursor.execute('RELEASE SAVEPOINT layer1_country_revision')


def _completed_sea_receipt(row):
    if (row.get('status') != 'UNASSESSED' or row.get('retailer') != 'HomeDepot'
            or row.get('collection_phase') != 'complete' or row.get('batch_count') != 1
            or not row.get('batch_id') or not row.get('count')):
        return False
    ranks = {item['name']: item['count'] for item in row.get('items', [])}
    main, bsr = ranks.get('Main Rank', 0), ranks.get('BSR Rank', 0)
    return main > 0 and main >= bsr


def _raw_issue(check_type, row):
    counts = {item['name']: item['count'] for item in row.get('items', [])}
    main = row.get('main_count', counts.get('Main Rank'))
    bsr = row.get('bsr_count', counts.get('BSR Rank'))
    return (
        (main == 0 and not row.get('missing_by_raw_count'))
        or (row.get('bsr_applicable') is not False and main is not None and bsr is not None and main < bsr)
        # SEUK's receipt check does not apply the separately fixed Currys BSR rule.
        or (check_type == 'seuk_retail' and row.get('retailer') == 'Currys' and bsr != 100)
    )


def database_snapshot(cursor):
    cursor.execute('SAVEPOINT layer1_database_snapshot')
    try:
        cursor.execute('SELECT current_database(), current_user, pg_postmaster_start_time(), txid_current_snapshot()::text')
        return cursor.fetchone()
    except Error:
        cursor.execute('ROLLBACK TO SAVEPOINT layer1_database_snapshot')
        return None
    finally:
        cursor.execute('RELEASE SAVEPOINT layer1_database_snapshot')


def collection_configuration(check):
    if check['check_type'] == 'tse_retail':
        return tuple(tuple(sorted(_configured_retailers(category['product_line']).items()))
                     for category in check['categories'] if category.get('product_line'))
    if check['check_type'] == 'retail':
        fields = ('category', 'retailer', 'expected_count', 'us_start_hour', 'collection_duration_min')
        return tuple(tuple(schedule.get(field) for field in fields)
                     for schedule in load_collection_schedules() if schedule['check_type'] == 'retail')
    return ()


def reusable(check, failed_items, *, sea_source_complete=False):
    if (check.get('status') != 'OK' or check.get('phase', 'complete') != 'complete'
            or _has_error(check) or check.get('batch_count_error') or failed_items):
        return False
    rows = [
        row for category in check.get('categories', [])
        for slot in category.get('time_slots') or (category,)
        for row in slot.get('retailers', [])
    ]
    operating = [row for row in rows if not row.get('exclude_from_total')]
    return bool(operating) and all(
        (row.get('status') == 'OK' or (
            check.get('check_type') == 'retail' and sea_source_complete and _completed_sea_receipt(row)
        )) and row.get('verification_state') == 'ready'
        and row.get('batch_count', 0) < 2 and has_collection(row)
        and not _raw_issue(check.get('check_type'), row) for row in operating
    )


class CountryRevisions:
    def __init__(self, cursor, day, now, refresh):
        self.cursor = cursor
        self.day = day
        self.today = now.date()
        self.refresh = refresh
        self.cache = _backend(_root())
        self.checked = {}
        self.snapshot = None

    def _key(self, check_type):
        return _value_digest(
            'layer1-country-v2', (check_type, str(self.day), str(self.today)),
        )

    def _revision(self, check):
        scope = (
            check['check_type'],
            tuple((category.get('product_line'), category.get('source_date'))
                  for category in check.get('categories', [])),
        )
        # Both reads use the dashboard's repeatable-read transaction.
        if scope not in self.checked:
            self.checked[scope] = source_revision(self.cursor, check, self.day)
        return self.checked[scope]

    def get(self, check_type):
        if self.refresh:
            return None
        key = self._key(check_type)
        try:
            saved = self.cache.get(key)
        except (OSError, ValueError):
            logger.warning('Layer 1 country cache unavailable', exc_info=True)
            return None
        if (saved and saved.get('revision')
                and saved.get('configuration') == collection_configuration(saved['check'])):
            snapshot = self._database_snapshot()
            if (snapshot and saved.get('snapshot') == snapshot
                    or saved['revision'] == self._revision(saved['check'])):
                if snapshot and saved.get('snapshot') != snapshot:
                    self._store(key, {**saved, 'snapshot': snapshot})
                return saved['check']
        return None

    def _database_snapshot(self):
        if self.snapshot is None:
            self.snapshot = database_snapshot(self.cursor) or ()
        return self.snapshot

    def _store(self, key, entry):
        try:
            self.cache.set(key, entry, timeout=_TTL)
        except (OSError, ValueError):
            logger.warning('Layer 1 country cache update failed', exc_info=True)

    def store(self, check, failed_items):
        check_type = check['check_type']
        key = self._key(check_type)
        try:
            # SEA's D-1 source schedule is closed when the inspection date has arrived.
            if reusable(check, failed_items, sea_source_complete=self.day <= self.today):
                revision = self._revision(check)
                if revision is not None:
                    self._store(key, {'revision': revision, 'check': check,
                                      'configuration': collection_configuration(check),
                                      'snapshot': self._database_snapshot()})
                    return
            self.cache.delete(key)
        except (OSError, ValueError):
            logger.warning('Layer 1 country cache update failed', exc_info=True)
