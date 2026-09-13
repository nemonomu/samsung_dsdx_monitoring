import unittest
from datetime import date, datetime
from unittest.mock import patch

from apps.common.seda_retail import get_seda_average
from apps.dx.dx_layer1.seda_retail import seda_retail_services as service


class SedaLayer1ServiceTests(unittest.TestCase):
    def _result(self, current=None, previous=None, target=None, now=None):
        with patch.object(service.repo, 'get_latest_main_batch_counts') as counts:
            with patch.object(service.repo, 'get_previous_main_counts') as history:
                counts.return_value = current or []
                history.return_value = previous or []
                result = service.get_layer1_stats(
                    None,
                    target or date(2026, 8, 11),
                    now or datetime(2026, 8, 11, 12),
                )
        return result, counts, history

    def test_d_minus_one_counts_and_aliases_are_displayed(self):
        result, counts, history = self._result([
            {
                'retailer': 'Magalu', 'batch_id': 'm1',
                'actual_count': 238, 'main_count': 218, 'bsr_count': 100,
            },
            {
                'retailer': 'CasasBahia', 'batch_id': 'c1',
                'actual_count': 308, 'main_count': 300, 'bsr_count': 100,
            },
        ], [
            {'retailer': 'magalu', 'source_date': '2026-08-09', 'main_count': 220},
            {'retailer': 'casasbahia', 'source_date': '2026-08-09', 'main_count': 300},
        ])

        check = result['check']
        tv = check['categories'][0]
        self.assertEqual('SEDA Retail', check['name'])
        self.assertEqual('2026-08-11', check['inspection_date'])
        self.assertEqual('2026-08-10', check['source_date'])
        self.assertEqual(-1, check['offset_days'])
        self.assertEqual(['Magalu', 'Casas Bahia'], [
            row['retailer'] for row in tv['retailers']
        ])
        self.assertEqual(546, tv['raw_count'])
        self.assertEqual(518, tv['main_count'])
        self.assertEqual(200, tv['bsr_count'])
        self.assertEqual([220, 300], [
            row['expected'] for row in tv['retailers']
        ])
        self.assertTrue(all(
            call.args[2:] == ('2026-08-10', 7)
            for call in history.call_args_list
        ))
        self.assertTrue(all(
            call.args[2] == '2026-08-10'
            for call in counts.call_args_list
        ))

    def test_completed_missing_retailers_are_critical(self):
        result, _, _ = self._result()

        self.assertEqual('CRITICAL', result['check']['status'])
        self.assertEqual(6, len(result['failed_items']))
        self.assertTrue(all(
            item['timestamp'] == '2026-08-10'
            for item in result['failed_items']
        ))

    def test_collected_rows_are_ok_even_when_main_rank_is_empty(self):
        result, _, _ = self._result([{
            'retailer': 'Magalu', 'batch_id': 'm1',
            'actual_count': 3, 'main_count': 0, 'bsr_count': 3,
        }])

        retailer = result['check']['categories'][0]['retailers'][0]
        self.assertEqual(3, retailer['raw_count'])
        self.assertEqual(0, retailer['main_count'])
        self.assertEqual('OK', retailer['status'])

    def test_future_inspection_date_is_pending(self):
        result, _, _ = self._result(
            target=date(2026, 8, 12), now=datetime(2026, 8, 11, 12)
        )

        self.assertEqual('PENDING', result['check']['status'])
        self.assertEqual([], result['failed_items'])
        self.assertEqual('2026-08-11', result['check']['source_date'])

    def test_average_is_integer_and_ignores_zero(self):
        self.assertEqual(300, get_seda_average([300, 0, 301, None]))
        self.assertIs(type(get_seda_average([300, 301])), int)
        self.assertIsNone(get_seda_average([0, None]))


if __name__ == '__main__':
    unittest.main()
