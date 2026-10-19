"""Spain onboarding: D-day deadlines, original dates, batches and NULL scope."""
import unittest
from datetime import date, datetime, timezone
from unittest.mock import Mock

from django.test import override_settings
from apps.common import seib_retail as policy
from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.source_dates import source_date_value, source_date_sql
from apps.dx.dx_layer1.seib_retail.seib_retail_services import get_layer1_stats
from apps.dx.dx_layer1.collection_statistics import calculations as calc
from apps.dx.dx_layer1.column_statistics import services as columns
from apps.dx.dx_layer1.column_statistics.comparison import collection_complete
from apps.dx.dx_layer1.common import retail_batches
from apps.dx.dx_layer1.management.commands.setup_seib import register
from apps.dx.dx_layer2 import seib_null_validation as nulls


class SeibMonitoringTests(unittest.TestCase):
    day = date(2026, 10, 19)

    def test_original_dates_and_same_day_mapping(self):
        for raw, expected in [('2026-10-18T23:59:59-04:00', '2026-10-18'),
                              ('2026-10-19T00:00:00+09:00', '2026-10-19')]:
            self.assertEqual(expected, source_date_value(raw))
        for key, source in policy.SEIB_SOURCE_CONFIG.items():
            mapping = resolve_monitoring_date(self.day, 'SEIB', key)
            self.assertEqual('2026-10-19', mapping['source_date'])
            self.assertEqual(0, mapping['offset_days'])
            cte, scope, params = policy.latest_scope(source, '2026-10-01', '2026-10-19')
            self.assertEqual(['2026-10-18', '2026-10-19', 'mediamarkt', 'mediamarkt'], params)
            self.assertIn(source_date_sql('anchor.crawl_datetime'), cte)
            self.assertIn('ORDER BY', cte)
            self.assertIn('anchor.id DESC', cte)
            self.assertIn('latest.source_date', scope)
            self.assertNotIn('AT TIME ZONE', cte + scope)
            self.assertNotIn('page_type', cte + scope)

    def test_deadline_boundaries_and_timezone_are_separate_from_date_key(self):
        for hour, minute, expected in [(0, 59, 'pending'), (1, 0, 'collecting'),
                                       (3, 59, 'collecting'), (4, 0, 'complete')]:
            now = datetime(2026, 10, 19, hour, minute, tzinfo=policy.KST)
            self.assertEqual(expected, policy.collection_phase(self.day, now))
            self.assertEqual(expected, policy.collection_phase(self.day, now.astimezone(timezone.utc)))
            self.assertEqual(expected == 'complete', collection_complete('SEIB', 'TV', 'MediaMarkt', self.day, now))
        cursor = Mock()
        before = get_layer1_stats(cursor, date(2026, 10, 17), datetime(2026, 10, 19, 5, tzinfo=policy.KST))
        self.assertEqual('PENDING', before['check']['status'])
        self.assertTrue(all(not c['retailers'] for c in before['check']['categories']))
        cursor.execute.assert_not_called()

    def test_missing_after_four_is_critical_even_without_history(self):
        cursor = Mock()
        cursor.fetchone.return_value = (0, 0, 0, None)
        result = get_layer1_stats(cursor, self.day, datetime(2026, 10, 19, 4, tzinfo=policy.KST))
        self.assertEqual('CRITICAL', result['check']['status'])
        self.assertEqual(4, len(result['failed_items']))
        rows = calc.normalize_check(result['check'], 'SEIB', self.day)
        self.assertEqual(4, len(rows))
        for row in calc.compare_rows(rows, [], country='SEIB'):
            self.assertEqual('missing', row['bsr_comparison_state'])
            self.assertEqual('CRITICAL', row['base_status'])
            self.assertEqual('db_original', row['source_date_basis'])

    def test_overlap_and_variable_bsr_do_not_create_fixed_100_errors(self):
        cursor = Mock()
        cursor.fetchone.side_effect = [(300, 300, 100, 'm1'), (217, 206, 100, 'm1'),
                                      (291, 291, 100, 'm1'), (74, 66, 59, 'm1')]
        result = get_layer1_stats(cursor, self.day, datetime(2026, 10, 19, 4, tzinfo=policy.KST))
        self.assertEqual(882, result['check']['actual'])
        rows = calc.normalize_check(result['check'], 'SEIB', self.day)
        for row in rows:
            self.assertTrue(calc.variable_bsr(row, 'SEIB'))
            self.assertEqual(('median_28d', 'observing', None, None),
                             calc._compare_bsr(dict(row, observation_state='observing'), [], 'SEIB'))
            history = [dict(row, source_date=f'2026-10-{d}', bsr=100) for d in range(18, 23)]
            for count, status in [(86, None), (85, 'VOLUME_REVIEW'), (80, 'VOLUME_LOW')]:
                alert = calc._compare_bsr(dict(row, bsr=count, observation_state='ready'), history, 'SEIB')[3]
                self.assertEqual(status, alert['status'] if alert else None)

    def test_batch_details_keep_both_batches_and_original_date(self):
        cursor = Mock()
        cursor.fetchall.return_value = [('m_old', 't1', 't1', 80, 59, False, 88),
                                       ('m_new', 't2', 't2', 66, 59, True, 74)]
        cursor.mogrify.return_value = b'SELECT *;'
        result = retail_batches.fetch_batch_details(cursor, 'seib_retail', 'seib_ldy_dryer', '2026-10-19', 'MediaMarkt')
        self.assertEqual([False, True], [row['applied'] for row in result['batches']])
        sql, params = cursor.execute.call_args.args
        self.assertEqual(('2026-10-19', 'mediamarkt'), params)
        self.assertIn(source_date_sql('crawl_datetime'), sql)
        self.assertNotIn('page_type', sql)

    def test_type_fields_remain_in_statistics_only(self):
        for key, config in policy.SEIB_SOURCE_CONFIG.items():
            required = policy.get_seib_null_columns(key)
            fields = columns.ordered_columns(config['columns'])
            self.assertEqual(11, len(required))
            self.assertEqual(11 if key == 'seib_tv' else 12, len(fields))
            source = columns.select_source('SEIB', config['category'], 'MediaMarkt')
            sql, params = columns.query_spec(source, source['retailers'][0], fields, date(2026, 10, 1), self.day)
            self.assertIn('2026-10-18', params)
            self.assertIn('latest.chosen_batch', sql)
            self.assertNotIn('page_type', sql)
            for optional in ('original_sku_price', 'savings', 'main_rank', 'bsr_rank', 'loading_type', 'ref_refrigerator_type'):
                self.assertNotIn(optional, required)
            if key in ('seib_ldy', 'seib_ldy_dryer'):
                self.assertIn('loading_type', fields)
                self.assertIn('capacity', required)
            for value in (0, '0', '0.0'):
                self.assertFalse(nulls.missing(value))
            for value in (None, '', '  '):
                self.assertTrue(nulls.missing(value))

    def test_null_review_selects_only_current_batch_and_allowed_field(self):
        cursor = Mock()
        cursor.fetchone.return_value = (None, 'MediaMarkt', 'item1', 'm_new')
        self.assertEqual((None, 'MediaMarkt', 'item1'), nulls.select_record(cursor, self.day, 'seib_ldy', 42, 'capacity'))
        sql, params = cursor.execute.call_args.args
        self.assertIn('source.batch_id IS NOT DISTINCT FROM latest.batch_id', sql)
        self.assertIn('FOR UPDATE OF source', sql)
        self.assertEqual(['2026-10-19', '2026-10-19', 'mediamarkt', 'mediamarkt', 42], params)
        with self.assertRaises(ValueError):
            nulls.select_record(cursor, self.day, 'seib_ldy', 42, 'loading_type')

    @override_settings(DEBUG=True)
    def test_registration_is_test_isolated_and_does_not_enable_other_layers(self):
        cursor = Mock()
        cursor.fetchone.return_value = (11,)
        register(cursor)
        queries = '\n'.join(call.args[0] for call in cursor.execute.call_args_list)
        self.assertIn('public.test_monitoring_null_column', queries)
        self.assertNotIn('public.monitoring_null_column', queries)
        self.assertNotIn('format_rule', queries)
        self.assertNotIn('UPDATE dx_seib.', queries)
