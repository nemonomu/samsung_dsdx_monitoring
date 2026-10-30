"""AO launch/preview isolation and Casas-only D-DAY, without production writes."""
import sys
import unittest
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests import test_collection_statistics_backend  # isolated Django settings
from apps.common import seuk_retail as uk, dryer_onboarding as onboarding
from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.source_dates import source_date_sql, source_date_value
from apps.dx.dx_layer1.seuk_retail.seuk_retail_services import get_layer1_stats
from apps.dx.dx_layer1.collection_statistics import calculations as stats, automatic
from apps.dx.dx_layer1.column_statistics import services as columns
from apps.dx.dx_layer1.column_statistics.comparison import collection_complete, attach_comparisons
from apps.dx.dx_layer1.dashboard import seda_collection as casas, collection_services as dday
from apps.dx.dx_layer2 import seuk_null_validation as nulls, seuk_duplicate_validation as duplicates
from apps.dx.dx_layer2 import seuk_format_validation as formats
from apps.dx.dx_layer3.cross_field import seuk_services as cross

PREVIEW = date(2026, 10, 30)
LAUNCH = date(2026, 11, 1)


class AoMonitoringTests(unittest.TestCase):
    def check(self, day, count, now=None):
        cursor = Mock()
        cursor.fetchone.return_value = (count, count, min(count, 100), 'latest' if count else None)
        result = get_layer1_stats(cursor, day, now or datetime(2026, 11, 2, 5, tzinfo=uk.KST))
        return result, cursor

    def test_scope_is_three_products_and_preserves_currys_default(self):
        for key, source in uk.SEUK_SOURCE_CONFIG.items():
            self.assertEqual(('Currys',) if key == 'seuk_tv' else ('Currys', 'AO'), source['retailers'])
            _, _, params = uk.latest_scope(source, '2026-10-01', '2026-11-01')
            self.assertEqual(['2026-10-25', '2026-11-01', 'currys', 'currys'], params)
        with self.assertRaises(ValueError): uk.get_seuk_null_columns('seuk_tv', 'AO')
        self.assertIsNone(onboarding.config('SEUK', 'TV', 'AO'))
        for key in ('seuk_ref', 'seuk_ldy', 'seuk_ldy_dryer'):
            cte, scope, params = uk.latest_scope(uk.SEUK_SOURCE_CONFIG[key], '2026-10-01', '2026-11-01', ' ao ')
            self.assertEqual(['2026-10-30', '2026-11-01', 'ao', 'ao'], params)
            self.assertIn(source_date_sql('anchor.crawl_datetime'), cte)
            self.assertNotIn('AT TIME ZONE', cte + scope)
            self.assertIn('IS NOT DISTINCT FROM latest.batch_id', scope)
        self.assertEqual('2026-10-30', source_date_value('2026-10-30T23:59:59-04:00'))

    def test_preview_received_deleted_and_launch_deadline(self):
        before, _ = self.check(date(2026, 10, 29), 10)
        self.assertEqual(4, sum(len(c['retailers']) for c in before['check']['categories']))
        for count in (203, 0):
            result, cursor = self.check(PREVIEW, count)
            rows = [r for c in result['check']['categories'] for r in c['retailers'] if r['retailer'] == 'AO']
            self.assertEqual(3, len(rows))
            self.assertEqual(7, cursor.execute.call_count)
            self.assertTrue(all(r['preview_mode'] and r['active_from'] == str(LAUNCH) for r in rows))
            self.assertTrue(all(r['status'] == ('OK' if count else 'PENDING') for r in rows))
            self.assertFalse(any('(AO)' in r['source'] for r in result['failed_items']))
        for hour, minute, status in ((0,59,'PENDING'),(1,0,'COLLECTING'),(3,59,'COLLECTING'),(4,0,'CRITICAL')):
            now = datetime(2026,11,1,hour,minute,tzinfo=uk.KST)
            result, _ = self.check(LAUNCH, 0, now.astimezone(timezone.utc))
            rows = [r for c in result['check']['categories'] for r in c['retailers'] if r['retailer'] == 'AO']
            self.assertTrue(all(not r['preview_mode'] and r['status'] == status for r in rows))

    def test_preview_excluded_from_observation_week_and_column_history(self):
        result, _ = self.check(PREVIEW, 203)
        rows = [r for r in stats.normalize_check(result['check'], 'SEUK', PREVIEW) if r['retailer'] == 'AO']
        compared = stats.compare_rows(rows, [], 'SEUK')
        self.assertTrue(all(r['comparison_state'] == 'preview' and not r['baseline_eligible'] for r in compared))
        observed = defaultdict(set)
        stats.remember_observation(observed, compared, str(PREVIEW))
        self.assertFalse(any(observed.values()))
        weeks = stats.build_week({PREVIEW: compared}, date(2026,10,26), PREVIEW)
        self.assertTrue(all(r['completed_days'] == 0 and r['metrics']['total']['sum'] is None for r in weeks))
        cursor = Mock()
        cursor.fetchall.return_value = []
        @contextmanager
        def connection(): yield None, cursor
        for product in ('REF', 'LDY', 'LDY_DRYER'):
            with patch.object(columns, 'dx_connection', connection):
                data = columns.daily_counts('SEUK', product, 'AO', PREVIEW, 7)
            self.assertEqual(str(LAUNCH), data['active_from'])
            sql, params = cursor.execute.call_args.args
            self.assertIn(str(PREVIEW), params)
            self.assertIn('latest.chosen_batch', sql)
            self.assertFalse(collection_complete('SEUK', product, 'AO', PREVIEW))
            compared_columns = attach_comparisons(data, PREVIEW)
            self.assertTrue(all(c['status'] == 'not_scheduled' for c in compared_columns['comparisons']))

    def test_null_fields_and_latest_batch_edit_allowlist(self):
        for product, extra in (('ref','ref_capacity'),('ldy','capacity'),('ldy_dryer','capacity')):
            key = 'seuk_' + product
            fields = uk.get_seuk_null_columns(key, 'AO')
            self.assertEqual(11, len(fields))
            self.assertIn(extra, fields)
            self.assertFalse(set(fields) & {'loading_type','ref_refrigerator_type','original_sku_price','savings'})
            cursor = Mock()
            cursor.fetchone.return_value = (None, 'AO', 'same-item', 'latest')
            self.assertEqual((None,'AO','same-item'), nulls.select_record(cursor,PREVIEW,key,42,extra))
            sql, params = cursor.execute.call_args.args
            self.assertIn('latest.retailer_key', sql)
            self.assertIn('FOR UPDATE OF source', sql)
            self.assertIn('ao', params)
            nulls.select_record(cursor, PREVIEW, key, 42, 'star_rating', format_columns=formats.get_format_columns(key))
            self.assertNotIn('ao', cursor.execute.call_args.args[1])
        for value in (None, '', '  '): self.assertTrue(nulls.missing(value))
        for value in (0, '0', '0.0'): self.assertFalse(nulls.missing(value))

    def test_null_counts_and_duplicate_details_for_ao(self):
        source = uk.SEUK_SOURCE_CONFIG['seuk_ldy']
        mapping = nulls._mapping(PREVIEW, source)
        record = dict.fromkeys(source['columns'], 'present')
        record.update(id=1,account_name='AO',item='A',capacity='',star_rating='0',count_of_reviews='0')
        with patch.object(nulls,'latest_rows',return_value=([record],mapping)), \
             patch.object(nulls,'_load_normal_reviews',return_value={}), \
             patch.object(nulls,'uses_new_policy',return_value=False):
            result = {'tables':[]}
            nulls.append_null_stats(Mock(),PREVIEW,result,source['section_code'])
        ao = next(r for r in result['tables'][0]['retailers'] if r['retailer']=='AO')
        self.assertEqual(1,ao['total_null_count'])
        self.assertEqual(1,ao['fields_detail']['capacity'])
        with patch.object(duplicates,'latest_rows',return_value=([record,dict(record,id=2)],mapping)) as fetch:
            detail = duplicates.duplicate_detail(Mock(),PREVIEW,source['section_code'],' ao ')
        self.assertEqual('AO',fetch.call_args.args[-1])
        self.assertEqual('AO',detail['retailer'])
        self.assertEqual(1,detail['results']['total_groups'])

    def test_no_ao_format_or_crossfield_and_previews_rechecked(self):
        self.assertEqual([],formats.get_format_rule_details('seuk_ref','AO'))
        cursor = Mock()
        cursor.description = []
        cursor.fetchall.return_value = []
        cross._load_rows(cursor,uk.SEUK_SOURCE_CONFIG['seuk_ref'],PREVIEW,PREVIEW)
        self.assertNotIn('ao', cursor.execute.call_args.args[1])
        queryset = Mock()
        old = [dict(product=p,retailer='Currys',bsr=100,source_date_basis='db_original')
               for p in ('TV','REF','LDY','LDY_DRYER')]
        queryset.values_list.return_value = [(PREVIEW, old)]
        with patch.object(automatic.Daily.objects,'filter',return_value=queryset):
            start, end = automatic.history_range('SEUK',date(2026,11,2))
        self.assertEqual(PREVIEW,end)
        self.assertLessEqual(start,PREVIEW)


class CasasDdayTests(unittest.TestCase):
    def status(self, now, result=(0,None,None,0,0), error=False):
        cursor = Mock()
        cursor.fetchone.return_value = result
        if error: cursor.execute.side_effect = RuntimeError('unavailable')
        @contextmanager
        def connection(): yield None,cursor
        with patch.object(casas,'dx_connection',connection):
            return casas.get_collection_status(PREVIEW,now),cursor

    def test_time_boundaries_receipt_and_failure(self):
        for hour,minute,status in ((8,59,'scheduled'),(9,0,'waiting'),(14,59,'waiting'),(15,0,'uncollected')):
            now = datetime(2026,10,30,hour,minute,tzinfo=uk.KST)
            result,_ = self.status(now.astimezone(timezone.utc))
            self.assertEqual({'TV','REF','LDY'},{r['product'] for r in result['retailers']})
            self.assertTrue(all(r['retailer']=='Casas Bahia' and r['status']==status for r in result['retailers']))
            received,_ = self.status(now,(300,'2026-10-30 09:28:13','latest',300,100))
            self.assertTrue(all(r['status']=='received' for r in received['retailers']))
        failed,_ = self.status(now,error=True)
        self.assertTrue(all(r['status']=='error' and r['count'] is None for r in failed['retailers']))

    def test_raw_source_day_alias_latest_batch_and_d_minus_one_unchanged(self):
        _,cursor = self.status(datetime(2026,10,30,10,tzinfo=uk.KST))
        for call in cursor.execute.call_args_list:
            sql,params = call.args
            self.assertEqual(['2026-10-30'],params)
            self.assertIn(source_date_sql('source.crawl_strdatetime'),sql)
            self.assertIn("= 'casasbahia'",sql)
            self.assertNotIn('magalu',sql.lower())
            self.assertNotIn('AT TIME ZONE',sql)
            self.assertIn('IS NOT DISTINCT FROM latest.batch_id',sql)
        self.assertEqual('2026-10-29',resolve_monitoring_date(PREVIEW,'SEDA','seda_tv')['source_date'])

    def test_api_combines_separate_country_cards(self):
        sea = dict(source_date=str(PREVIEW),retailers=[dict(retailer='Walmart')])
        seda = dict(country='SEDA',retailers=[dict(retailer='Casas Bahia')])
        with patch.object(dday,'get_collection_status',return_value=sea), \
             patch.object(casas,'get_collection_status',return_value=seda):
            result = dday.get_dday_collection_status(PREVIEW)
        self.assertEqual(['SEA','SEDA'],[r['country'] for r in result['countries']])
        self.assertEqual(sea['retailers'],result['retailers'])


if __name__ == '__main__':
    unittest.main()
