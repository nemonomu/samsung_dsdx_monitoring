import unittest
from datetime import date
from unittest.mock import patch

from apps.dx.dx_layer3.cross_field import sem_services


class SemCrossfieldHistoryTests(unittest.TestCase):
    def setUp(self):
        self.target = {
            'id': 30, 'item': '123', 'country': 'SEM',
            'account_name': 'Liverpool', 'crawl_datetime': '2026-09-08 10:00:00',
            'final_sku_price': '$100.00', 'original_sku_price': '$0.00',
        }
        self.mapping = {
            'inspection_date': '2026-09-08', 'source_date': '2026-09-08',
            'offset_days': 0,
        }

    def detail(self, history, days=3, product='sem_tv', targets=None):
        with patch.object(sem_services, '_latest_rows') as latest:
            with patch.object(sem_services, '_history_rows') as load_history:
                latest.return_value = (
                    [self.target] if targets is None else targets, self.mapping,
                )
                load_history.return_value = history
                result = sem_services.get_sem_cross_field_rule_detail(
                    None, date(2026, 9, 8), product,
                    product + ':original_price_zero', days=days,
                )
        return result, load_history

    def test_three_days_includes_normal_history_and_keeps_today_count(self):
        history = [
            {**self.target, 'id': 20, 'crawl_datetime': '2026-09-07 10:00:00',
             'original_sku_price': '$150.00'},
            {**self.target, 'id': 10, 'crawl_datetime': '2026-09-06 10:00:00'},
        ]
        for product in ('sem_tv', 'sem_ref', 'sem_ldy'):
            with self.subTest(product=product):
                result, load_history = self.detail(history, product=product)
                self.assertEqual([10, 20, 30], [r['id'] for r in result['anomalies']])
                self.assertEqual(
                    ['comparison_history', 'comparison_history', 'target'],
                    [r['row_role'] for r in result['anomalies']],
                )
                self.assertEqual(1, result['total_anomalies'])
                self.assertEqual(1, result['retailer_summary']['Liverpool']['count'])
                self.assertEqual(
                    (date(2026, 9, 6), date(2026, 9, 7), ['123']),
                    load_history.call_args.args[2:],
                )

    def test_missing_history_keeps_target_and_requested_period(self):
        result, _ = self.detail([])
        self.assertEqual(3, result['days'])
        self.assertEqual([30], [r['id'] for r in result['anomalies']])
        self.assertEqual('target', result['anomalies'][0]['row_role'])

    def test_history_cannot_replace_today_or_include_other_sources(self):
        prior = {**self.target, 'id': 20, 'crawl_datetime': '2026-09-07 10:00:00'}
        result, _ = self.detail([
            {**self.target, 'id': 99},
            {**prior, 'item': 'other'},
            {**prior, 'country': 'SEA'},
            {**prior, 'account_name': 'other'},
            {**prior, 'crawl_datetime': '2026-09-05 10:00:00'},
            prior,
        ])
        self.assertEqual([20, 30], [r['id'] for r in result['anomalies']])

    def test_one_day_and_no_findings_do_not_query_history(self):
        result, load_history = self.detail([], days=1)
        load_history.assert_not_called()
        self.assertEqual([30], [r['id'] for r in result['anomalies']])
        result, load_history = self.detail([], targets=[])
        load_history.assert_not_called()
        self.assertEqual([], result['anomalies'])

    def test_thirty_day_limit_and_missing_item_preserve_target(self):
        result, load_history = self.detail([], days=60)
        self.assertEqual(30, result['days'])
        self.assertEqual(date(2026, 8, 10), load_history.call_args.args[2])
        result, load_history = self.detail([], targets=[{**self.target, 'item': None}])
        load_history.assert_not_called()
        self.assertEqual([30], [r['id'] for r in result['anomalies']])


if __name__ == '__main__':
    unittest.main()
