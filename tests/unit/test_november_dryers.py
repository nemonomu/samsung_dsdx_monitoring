"""November launch, preview removal and retailer isolation regressions."""
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from unittest import TestCase
from unittest.mock import Mock, patch

from django.test import override_settings

from apps.common import dryer_onboarding as onboarding, seib_retail, sem_retail
from apps.common.source_dates import source_date_value
from apps.dx.dx_layer1.seg_retail import sources as seg_sources, seg_retail_services
from apps.dx.dx_layer1.sem_retail import sem_retail_services, sem_retail_repositories
from apps.dx.dx_layer1.seib_retail import seib_retail_services
from apps.dx.dx_layer1.column_statistics import services as columns
from apps.dx.dx_layer1.column_statistics.comparison import attach_comparisons, collection_complete
from apps.dx.dx_layer1.collection_statistics import calculations as stats, automatic, live
from apps.dx.dx_layer1.management.commands import setup_november_dryers as setup
from apps.dx.dx_layer2 import seg_sources as seg2, seg_validation, sem_validation
from apps.dx.dx_layer2 import seib_null_validation as seib_null, seib_duplicate_validation as seib_dup
from apps.dx.dx_layer3.cross_field import sem_services as sem_cross, seg_sources as seg_cross

PREVIEW = date(2026, 10, 30)
LAUNCH = date(2026, 11, 1)


class NovemberDryerTests(TestCase):
    def test_only_new_dryer_retailers_are_added(self):
        self.assertEqual(('Mediamarkt', 'Expert', 'OTTO'), seg_sources.active_retailers(seg_sources.get_seg_source('seg_ldy_dryer'), PREVIEW))
        self.assertEqual(('HomeDepot', 'Coppel', 'Liverpool'), sem_retail.active_sem_retailers('sem_ldy_dryer', PREVIEW))
        self.assertEqual(('MediaMarkt', 'ECI'), seib_retail.active_retailers(seib_retail.get_seib_source('seib_ldy_dryer'), PREVIEW))
        self.assertEqual(('MediaMarkt',), seib_retail.get_seib_source('seib_ldy')['retailers'])
        self.assertIsNone(onboarding.config('SEG', 'LDY', 'OTTO'))

    def test_exact_eleven_null_fields_and_optional_values(self):
        required = set(onboarding.REQUIRED_COLUMNS)
        self.assertEqual(11, len(required))
        self.assertEqual(required, set(seg2.get_seg_null_columns('seg_ldy_dryer', 'OTTO')))
        self.assertEqual(required, set(sem_retail.get_sem_required_columns('sem_ldy_dryer', 'Liverpool')))
        self.assertEqual(required, set(seib_retail.get_seib_null_columns('seib_ldy_dryer', 'ECI')))
        for missing in (None, '', '  '):
            self.assertTrue(seib_null.missing(missing))
            self.assertTrue(seg_validation._missing(missing))
        for value in (0, '0', '0.0'):
            self.assertFalse(seib_null.missing(value))
            self.assertFalse(seg_validation._missing(value))
        with self.assertRaises(ValueError):
            seib_retail.get_seib_null_columns('seib_tv', 'ECI')

    def test_otto_country_null_is_not_hidden_by_country_filter(self):
        condition = seg2.country_scope(seg2.get_seg_source('seg_ldy_dryer'))
        self.assertIn("OR LOWER(BTRIM(CAST(source.account_name AS TEXT))) = 'otto'", condition)
        for source in (seg2.get_seg_source('seg_ldy'), seg2.SEG_FORMAT_SOURCE_CONFIG['seg_ldy_dryer']):
            self.assertEqual('UPPER(BTRIM(CAST(source.country AS TEXT))) = %s', seg2.country_scope(source))

    def test_eci_deadline_and_mediamarkt_deadline_are_independent(self):
        source = seib_retail.get_seib_source('seib_ldy_dryer')
        for hour, minute, expected in ((7, 59, 'pending'), (8, 0, 'collecting'), (8, 59, 'collecting'), (9, 0, 'complete')):
            now = datetime(2026, 11, 1, hour, minute, tzinfo=seib_retail.KST)
            self.assertEqual(expected, seib_retail.collection_phase(LAUNCH, now, source=source, retailer='ECI'))
            self.assertEqual('complete', seib_retail.collection_phase(LAUNCH, now))
            self.assertEqual(expected == 'complete', collection_complete('SEIB', 'LDY_DRYER', 'ECI', LAUNCH, now))

    def test_seib_preview_delete_and_post_launch_missing(self):
        cursor = Mock()
        cursor.fetchone.return_value = (86, 86, 86, 'eci')
        now = datetime(2026, 11, 1, 9, tzinfo=seib_retail.KST)
        def eci(day):
            result = seib_retail_services.get_layer1_stats(cursor, day, now)
            return next(r for c in result['check']['categories'] for r in c['retailers'] if r['retailer'] == 'ECI')
        row = eci(PREVIEW)
        self.assertEqual((True, 86, 'OK'), (row['preview_mode'], row['actual'], row['status']))
        cursor.fetchone.return_value = (0, 0, 0, None)
        row = eci(PREVIEW)
        self.assertEqual(('PENDING', 'pending', 0), (row['status'], row['collection_phase'], row['actual']))
        row = eci(LAUNCH)
        self.assertEqual((False, 'CRITICAL'), (row['preview_mode'], row['status']))

    def test_eci_and_mediamarkt_do_not_share_latest_batches(self):
        cursor = Mock()
        cursor.fetchone.side_effect = [(1, 1, 1, 'm1')] * 4 + [(86, 86, 86, 'e1')]
        result = seib_retail_services.get_layer1_stats(cursor, LAUNCH, datetime(2026, 11, 1, 9, tzinfo=seib_retail.KST))
        dryer = result['check']['categories'][-1]
        self.assertEqual([('MediaMarkt', 1, 'm1'), ('ECI', 86, 'e1')],
                         [(r['retailer'], r['actual'], r['batch_id']) for r in dryer['retailers']])
        self.assertEqual(87, dryer['total'])
        self.assertEqual('eci', cursor.execute.call_args.args[1][-1])

    def test_eci_queries_use_recorded_date_and_account_in_join(self):
        source = seib_retail.get_seib_source('seib_ldy_dryer')
        cte, scope, params = seib_retail.latest_scope(source, PREVIEW, PREVIEW, 'ECI')
        self.assertEqual(['2026-10-30', '2026-10-30', 'eci', 'eci'], params)
        self.assertIn('LEFT(BTRIM(CAST(anchor.crawl_datetime AS TEXT)), 10)', cte)
        self.assertIn('source.batch_id IS NOT DISTINCT FROM latest.batch_id', scope)
        cursor = Mock()
        cursor.fetchone.return_value = (None, 'ECI', 'item', 'batch')
        self.assertEqual((None, 'ECI', 'item'), seib_null.select_record(cursor, PREVIEW, 'seib_ldy_dryer', 1, 'sku'))
        sql, params = cursor.execute.call_args.args
        self.assertIn('LOWER(BTRIM(source.account_name)) = latest.retailer_key', sql)
        self.assertIn('FOR UPDATE OF source', sql)
        self.assertIn('eci', params)
        # Existing MediaMarkt format editing must not gain ECI access.
        seib_null.select_record(cursor, PREVIEW, 'seib_ldy_dryer', 1, 'sku', format_columns=['sku'])
        self.assertNotIn('eci', cursor.execute.call_args.args[1])
        self.assertEqual('2026-10-30', source_date_value('2026-10-30T23:59:59-04:00'))
        self.assertEqual('2026-11-01', source_date_value('2026-11-01T00:00:00+09:00'))

    def test_duplicate_keys_keep_otto_variants_and_retailers_separate(self):
        rows = [dict(id=1, item='I1', sku='S1', retailer_sku_name='Dryer'),
                dict(id=2, item='I1', sku='S2', retailer_sku_name='Dryer')]
        self.assertEqual([], seg_validation.build_duplicate_groups(rows, 'OTTO', 'seg_ldy_dryer'))
        self.assertEqual(1, len(seg_validation.build_duplicate_groups([rows[0], dict(rows[0], id=3)], 'OTTO', 'seg_ldy_dryer')))
        self.assertEqual(1, len(sem_validation._duplicate_groups(rows)))
        mapping = dict(source_date=str(PREVIEW), inspection_date=str(PREVIEW), offset_days=0)
        with patch.object(seib_dup, 'latest_rows', return_value=(rows, mapping)) as fetch:
            detail = seib_dup.duplicate_detail(None, PREVIEW, 'seib_ldy_dryer', 'ECI')
        self.assertEqual('ECI', fetch.call_args.args[-1])
        self.assertEqual(1, detail['results']['total_groups'])
        self.assertEqual('ECI', detail['retailer'])

    def test_liverpool_raw_count_and_main_count_are_preserved(self):
        current = dict(retailer='Liverpool', actual_count=60, main_count=58, bsr_count=25, batch_id='liv')
        with patch.object(sem_retail_repositories, 'get_latest_batch_counts', return_value=current), \
                patch.object(sem_retail_repositories, 'get_previous_main_counts', return_value=[]):
            check = sem_retail_services.get_layer1_stats(None, PREVIEW, datetime(2026, 10, 30, 15))['check']
        row = next(r for r in stats.normalize_check(check, 'SEM', PREVIEW) if r['retailer'] == 'Liverpool' and r['product'] == 'LDY_DRYER')
        self.assertEqual((60, 58, 25, 58), (row['collected_count'], row['main'], row['bsr'], row['total']))
        self.assertTrue(row['preview_mode'])
        self.assertFalse(row['baseline_eligible'])
        self.assertFalse(row['complete'])

    def test_preview_never_contributes_to_baselines_or_observation(self):
        row = dict(product='LDY_DRYER', retailer='OTTO', slot='daily', country='SEG',
                   main=247, bsr=100, total=247, complete=True, base_status='OK', baseline_eligible=True,
                   preview_mode=True, active_from=str(LAUNCH))
        preview = stats.compare_rows([row], [], 'SEG')[0]
        self.assertEqual('preview', preview['comparison_state'])
        self.assertEqual([], preview['alerts'])
        observations = defaultdict(set)
        stats.remember_observation(observations, [preview], str(PREVIEW))
        self.assertEqual(0, len(observations[('LDY_DRYER', 'OTTO')]))
        # Legacy saved rows are excluded by their original date as well.
        history = [dict(row, preview_mode=False, source_date=str(PREVIEW-timedelta(days=i))) for i in range(7)]
        operating = stats.compare_rows([dict(row, preview_mode=False)], history, 'SEG')[0]
        self.assertEqual(0, operating['observation_prior_days'])
        self.assertEqual({}, operating['baselines'])
        week = stats.build_week({PREVIEW: [dict(preview, complete=False)]}, date(2026, 10, 26), PREVIEW)[0]
        self.assertEqual('preview', week['daily'][4]['state'])
        self.assertEqual(0, week['completed_days'])
        self.assertIsNone(week['metrics']['total']['sum'])

    def test_bsr_unknown_policy_never_falls_back_to_100(self):
        for country, retailer, bsr in [('SEM', 'Liverpool', 25), ('SEIB', 'ECI', 86)]:
            row = dict(product='LDY_DRYER', retailer=retailer, slot='daily', complete=True,
                       base_status='OK', main=100, bsr=bsr, total=100, observation_state='ready',
                       baselines={'main': {'value': 100, 'days': 5}})
            self.assertEqual(('policy_pending', 'policy_pending', None, None), stats._compare_bsr(row, [], country))
            self.assertNotIn('bsr', stats.comparison_rules(row, country))
            self.assertEqual('policy_pending', stats.current_volume_decision(row, country)['comparison_state'])

    def test_column_statistics_preview_is_visible_without_becoming_history(self):
        for country, retailer in [('SEG', 'OTTO'), ('SEM', 'Liverpool'), ('SEIB', 'ECI')]:
            cursor = Mock()
            cursor.fetchall.return_value = []
            @contextmanager
            def connection():
                yield None, cursor
            with patch.object(columns, 'dx_connection', connection):
                data = columns.daily_counts(country, 'LDY_DRYER', retailer, PREVIEW, 5)
            self.assertEqual(str(LAUNCH), data['active_from'])
            self.assertIn('capacity', data['columns'])
            self.assertIn('loading_type', data['columns'])
            self.assertNotIn('ldy_capacity', data['columns'])
            sql, params = cursor.execute.call_args.args
            self.assertIn(str(onboarding.config(country, 'LDY_DRYER', retailer)['preview_from']), params)
            self.assertIn('latest.chosen_batch', sql)
            data['daily'][-1].update(total=10, counts={c: 10 for c in data['columns']})
            result = attach_comparisons(data, PREVIEW, datetime(2026, 11, 1, 15, tzinfo=seib_retail.KST))
            self.assertTrue(all(r['status'] == 'not_scheduled' for r in result['comparisons']))
            self.assertEqual(10, result['daily'][-1]['total'])

    def test_new_crossfield_targets_do_not_enable_format_checks(self):
        self.assertNotIn('OTTO', seg2.SEG_FORMAT_SOURCE_CONFIG['seg_ldy_dryer']['retailers'])
        self.assertIn('OTTO', seg_cross.SEG_SOURCE_CONFIG['seg_ldy_dryer']['retailers'])
        self.assertEqual((), sem_validation.get_review_allowed_columns('sem_ldy_dryer', 'format_check', 'Liverpool'))
        self.assertEqual(('HomeDepot', 'Coppel', 'Liverpool'), sem_cross.active_sem_retailers('sem_ldy_dryer', LAUNCH))
        self.assertIn('Liverpool', sem_cross.SEM_SOURCE_CONFIG['sem_ldy_dryer']['retailers'])
        self.assertEqual([], sem_validation.format_detail(None, PREVIEW, 'sem_ldy_dryer', retailer='Liverpool')['results'])

    def test_registration_is_scoped_idempotent_and_environment_isolated(self):
        for debug in (True, False):
            for exists in (True, False):
                cursor = Mock(rowcount=int(exists))
                def fetch():
                    sql = cursor.execute.call_args.args[0]
                    if sql.startswith('SELECT COUNT'):
                        return (11,)
                    return (5,) if exists or 'INSERT INTO' in sql else None
                cursor.fetchone.side_effect = fetch
                with override_settings(DEBUG=debug):
                    setup.register(cursor)
                for call in cursor.execute.call_args_list:
                    sql = call.args[0]
                    params = call.args[1] if len(call.args) > 1 else ()
                    self.assertEqual(sql.count('%s'), len(params), sql)
                    if sql.lstrip().startswith(('UPDATE', 'INSERT')):
                        self.assertIn('public.' + ('test_' if debug else '') + 'monitoring_', sql)
                        self.assertNotIn('UPDATE dx_', sql)
                        self.assertNotIn('validation_rules', sql)
                schedules = [call.args[1] for call in cursor.execute.call_args_list
                             if call.args[0].lstrip().startswith('UPDATE') and 'monitoring_collection_schedule' in call.args[0]]
                self.assertEqual(['otto', 'liverpool', 'eci'], [p[-1] for p in schedules])
                self.assertEqual([300, 270, 60], [p[2] for p in schedules])

    def test_background_refresh_rechecks_surviving_preview_rows(self):
        row = dict(product='LDY_DRYER', retailer='OTTO', bsr=100, total=247, collected_count=247)
        # A saved preview count remains refreshable even when it is >3 days old.
        with patch.object(automatic.Daily, 'objects') as manager:
            manager.filter.return_value.values_list.return_value = [(PREVIEW, [row])]
            start, end = automatic.history_range('SEG', date(2026, 11, 2))
        self.assertLessEqual(start, PREVIEW)
        self.assertEqual(PREVIEW, end)

    def test_live_statistics_preserve_preview_state_after_deletion(self):
        for count in (86, 0):
            row = onboarding.decorate_row(dict(retailer='ECI', raw_count=count, actual=count,
                main_count=count, bsr_count=count, batch_id='e1' if count else None,
                status='OK', collection_phase='complete'), 'SEIB', 'LDY_DRYER', PREVIEW)
            check = dict(phase='complete', categories=[dict(name='LDY_DRYER', retailers=[row])])
            with patch.object(live, 'load_current_check', return_value=check), \
                    patch.object(live.Daily, 'objects') as manager, \
                    patch.object(live, 'review_index', return_value={}):
                history, older = Mock(), Mock()
                history.order_by.return_value = []
                older.filter.return_value = older
                older.order_by.return_value.first.return_value = None
                manager.filter.side_effect = [history, older]
                snapshot = live.current_snapshot('SEIB', PREVIEW)
            current = snapshot['rows'][0]
            self.assertEqual('preview', current['state'])
            self.assertEqual(count, current['total'])
            self.assertEqual({}, current['rules'])
            self.assertEqual([], current['alerts'])
