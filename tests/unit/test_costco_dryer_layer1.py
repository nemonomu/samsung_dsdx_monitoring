import unittest
from contextlib import contextmanager
from datetime import date, datetime
from unittest.mock import MagicMock, patch

from apps.common.sea_collection import KST
from apps.common.sea_retail import SEA_RETAIL_SOURCES
from apps.dx.dx_layer1.retail import costco, retail_services as svc, retail_repositories as repo
from apps.dx.dx_layer1.dashboard import collection_services as dday
from apps.dx.dx_layer1.column_statistics import services as columns
from apps.dx.dx_layer1.collection_statistics import calculations as calc
from apps.dx.dx_layer1.seg_retail import seg_retail_services as seg


@contextmanager
def connection():
    yield None, MagicMock()


class DryerTests(unittest.TestCase):
    def test_costco_tv_has_no_fixed_100_bsr_target(self):
        for count in (50, 99, 100, 101):
            self.assertTrue(svc._meets_retailer_criteria(
                {'count': 300, 'main': 300, 'bsr': count}, svc._retailer_criteria('TV', 'Costco')))
            row = dict(product='TV', retailer='Costco', slot='daily', main=300,
                       bsr=count, total=300, complete=True, base_status='OK')
            self.assertFalse(calc.exact_bsr(row, 'SEA'))
            result = calc.compare_rows([row], [], 'SEA')[0]
            self.assertFalse(any(a['metric'] == 'bsr' for a in result['alerts']))
            self.assertNotEqual('fixed_100', calc.comparison_rules(result, 'SEA').get('bsr', {}).get('rule'))
            with patch.object(dday, 'dx_connection', connection), patch.object(
                    dday, 'fetch_collection', return_value=(300, None, 'batch', 300, count)):
                rows = dday.get_collection_status(date(2026, 10, 11), datetime(2026, 10, 11, 16, tzinfo=KST))['retailers']
            tv = next(r for r in rows if r['product'] == 'TV' and r['retailer'] == 'Costco')
            self.assertEqual('received', tv['status'])
        self.assertEqual(100, svc._retailer_criteria('REF', 'Costco')['bsr_exact'])
        for product in ('LDY', 'LDY_DRYER'):
            self.assertNotIn('bsr_exact', svc._retailer_criteria(product, 'Costco'))
        self.assertTrue(calc.exact_bsr({'product': 'TV', 'retailer': 'Expert'}, 'SEG'))

    def test_source_scope_counts_start_and_date(self):
        self.assertNotIn('ldy_dryer', SEA_RETAIL_SOURCES)
        source = svc._get_layer1_source('LDY_DRYER')
        self.assertEqual('public.ldy_dryer_retail', source['table_name'])
        self.assertFalse(costco.enabled('2026-10-08', 'ldy_dryer'))
        cursor = MagicMock()
        self.assertIsNone(repo.get_latest_appliance_main_batch(cursor, source['table_name'], 'crawl_datetime', '2026-10-08', 'Costco'))
        cursor.execute.assert_not_called()
        cursor.fetchone.side_effect = [('c9',), (300, 100, 0, 332)]
        counts = repo.query_appliance_counts_by_retailer(cursor, source['table_name'], 'crawl_datetime', '2026-10-09', 'Costco')
        self.assertEqual((300, 100, 0, 332, 'c9'), counts)
        self.assertNotIn('page_type', cursor.execute.call_args.args[0])
        with patch.object(svc, '_matching_schedule_slots', return_value=[]), patch.object(svc, '_source_rows', return_value=[('Costco', 332, 300, 100, 0, 'c9')]):
            category, failures, contract = svc._build_category(cursor, source, date(2026, 10, 10), datetime(2026, 10, 11, tzinfo=KST))
        self.assertEqual('2026-10-09', contract['source_date'])
        self.assertEqual(332, category['total'])
        self.assertEqual([], failures)
        rows = calc.normalize_check({'categories': [category]}, 'SEA', date(2026, 10, 10))
        self.assertEqual('LDY_DRYER', rows[0]['product'])
        self.assertEqual('2026-10-09', rows[0]['active_from'])

    def test_dday_dryer_order_schedule_and_bsr(self):
        for count, expected in [(99, 'received'), (100, 'received'), (101, 'received')]:
            with patch.object(dday, 'dx_connection', connection), patch.object(dday, 'fetch_collection', return_value=(300, None, 'c11', 300, count)):
                rows = dday.get_collection_status(date(2026, 10, 11), datetime(2026, 10, 11, 16, tzinfo=KST))['retailers']
            self.assertEqual('LDY_DRYER', rows[-1]['product'])
            self.assertEqual(expected, rows[-1]['status'])
            self.assertEqual('2026-10-11T13:00:00+09:00', rows[-1]['scheduled_at'])

    def test_column_statistics_use_dryer_schema(self):
        source = columns.select_source('SEA', 'LDY_DRYER', 'Costco')
        retailer = next(r for r in source['retailers'] if r['name'] == 'Costco')
        sql, params = columns.query_spec(source, retailer, ['capacity', 'loading_type'], date(2026, 10, 1), date(2026, 10, 11))
        self.assertIn('public.ldy_dryer_retail', sql)
        self.assertIn('2026-10-09', params)
        self.assertNotIn('page_type', sql)
        self.assertIn('crawl_datetime', sql)

    def test_exact_bsr_without_five_day_wait(self):
        for country, retailer, product in [('SEA', 'Costco', 'REF'), ('SEG', 'Expert', 'LDY_DRYER')]:
            for count in (99, 100, 101):
                row = dict(product=product, retailer=retailer, slot='daily', main=300,
                           bsr=count, total=300, complete=True, base_status='OK')
                result = calc.compare_rows([row], [], country)[0]
                self.assertEqual(count != 100, bool(result['alerts']))
                result = calc.current_volume_decision(result, country)
                self.assertEqual(count != 100, bool(result['alerts']))
                self.assertTrue(calc.comparison_rules(result, country)['bsr']['exact'])
                self.assertEqual(count == 100, svc._meets_retailer_criteria(
                    {'count': 300, 'main': 300, 'bsr': count}, {'bsr_exact': 100, 'total_min': 1}))
                if retailer == 'Expert':
                    with patch.object(seg.repo, 'get_latest_main_batch_counts', return_value=[{'retailer': 'expert', 'main_count': 300, 'bsr_count': count, 'actual_count': 300}]), patch.object(seg.repo, 'get_previous_main_counts', return_value=[]):
                        check = seg.get_layer1_stats(None, date(2026, 10, 11), datetime(2026, 10, 11, 12, tzinfo=KST))['check']
                    expert = check['categories'][-1]['retailers'][0]
                    self.assertEqual('OK' if count == 100 else 'CRITICAL', expert['status'])

    def test_costco_laundry_medians_and_bidirectional_boundaries(self):
        for product, baseline, samples in [('LDY', 72, (50, 51, 74, 93, 94)),
                                           ('LDY_DRYER', 100, (70, 71, 97, 129, 130))]:
            for count in samples:
                with self.subTest(product=product, count=count):
                    row = dict(product=product, retailer='Costco', slot='daily', main=300,
                               bsr=count, total=300, complete=True, base_status='OK', baseline_eligible=True)
                    history = [dict(row, source_date=f'2026-11-{d:02}', bsr=baseline,
                                    alerts=[{'metric': 'bsr', 'status': 'VOLUME_LOW', 'rule': 'fixed_100'}])
                               for d in range(1, 6)]
                    observing = calc.compare_rows([row], history[:4], 'SEA')[0]
                    self.assertNotIn('bsr', observing['baselines'])
                    self.assertFalse(observing['alerts'])
                    ready = calc.compare_rows([row], history, 'SEA')[0]
                    self.assertEqual({'value': baseline, 'days': 5, 'rule': 'median_28d'}, ready['baselines']['bsr'])
                    self.assertFalse(calc.exact_bsr(row, 'SEA'))
                    self.assertEqual(abs(count - baseline) * 100 >= baseline * 30,
                                     any(a['metric'] == 'bsr' for a in ready['alerts']))
                    rules = calc.comparison_rules(ready, 'SEA')['bsr']
                    self.assertEqual((30, 'VOLUME_LOW'), (rules['high_percent'], rules['high_status']))
                    if count >= baseline * 1.3:
                        self.assertEqual('increase', ready['alerts'][0]['direction'])
                        self.assertEqual('VOLUME_LOW', ready['alerts'][0]['status'])
                        self.assertIn('30% 이상 증가', ready['alerts'][0]['reason'])
                    self.assertEqual(ready['alerts'], calc.current_volume_decision(ready, 'SEA')['alerts'])
                    legacy = dict(ready, baselines={'bsr': {'value': 100, 'days': 0, 'rule': 'fixed_100'}})
                    self.assertEqual('insufficient', calc.current_bsr_decision(legacy, 'SEA')['bsr_comparison_state'])

    def test_costco_policy_scope(self):
        for product, variable, exact in [('TV', True, False), ('REF', False, True),
                                         ('LDY', True, False), ('LDY_DRYER', True, False)]:
            row = {'product': product, 'retailer': 'Costco'}
            self.assertEqual(variable, calc.variable_bsr(row, 'SEA'))
            self.assertEqual(exact, calc.exact_bsr(row, 'SEA'))
            self.assertFalse(calc.variable_bsr(row, 'SEDA'))
            self.assertEqual(product in ('LDY', 'LDY_DRYER'), calc.bidirectional_bsr(row, 'SEA'))
            self.assertFalse(calc.bidirectional_bsr(row, 'SEDA'))

    def test_increase_history_excluded_and_tv_increase_unchanged(self):
        row = dict(product='LDY', retailer='Costco', slot='daily', main=300, bsr=74, total=300,
                   complete=True, base_status='OK', baseline_eligible=True)
        history = [dict(row, source_date=f'2026-11-{d:02}', bsr=72) for d in range(1, 6)]
        high = calc.compare_rows([dict(row, bsr=94)], history, 'SEA')[0]
        history.append(dict(high, source_date='2026-11-06'))
        result = calc.compare_rows([row], history, 'SEA')[0]
        self.assertEqual({'value': 72, 'days': 5, 'rule': 'median_28d'}, result['baselines']['bsr'])
        tv = dict(high, product='TV', bsr=140)
        self.assertFalse(calc.current_bsr_decision(tv, 'SEA')['alerts'])
        self.assertIsNone(calc.comparison_rules(tv, 'SEA')['bsr']['high_percent'])

    def test_bidirectional_thresholds_compare_before_rounding(self):
        for baseline, count, abnormal in [(72.5, 94, False), (72.5, 95, True),
                                           (2000, 2599, False), (2000, 2600, True),
                                           (2000, 1401, False), (2000, 1400, True)]:
            row = dict(product='LDY_DRYER', retailer='Costco', slot='daily', main=3000, total=3000,
                       bsr=count, complete=True, base_status='OK', observation_state='ready',
                       baselines={'bsr': {'value': baseline, 'days': 28, 'rule': 'median_28d'}})
            self.assertEqual(abnormal, bool(calc.current_bsr_decision(row, 'SEA')['alerts']))
