import unittest
from datetime import date, datetime, time, timezone
from unittest.mock import patch

from apps.common.seg_retail import get_seg_average, get_seg_collection_phase
from apps.dx.dx_layer1.seg_retail import seg_retail_services as service


class SegLayer1ServiceTests(unittest.TestCase):
    def result(self, current=None, previous=None, now=None):
        with patch.object(service.repo, 'get_latest_main_batch_counts') as counts:
            with patch.object(service.repo, 'get_previous_main_counts') as history:
                counts.return_value = current or []
                history.return_value = previous or []
                result = service.get_layer1_stats(
                    None, date(2026, 9, 9), now or datetime(2026, 9, 9, 12),
                )
        return result, counts, history

    def test_average_is_an_integer_and_ignores_zero(self):
        self.assertEqual(300, get_seg_average([300, 0, 301, None]))
        self.assertIs(type(get_seg_average([300, 301])), int)
        self.assertEqual(299, get_seg_average([299, 300]))
        self.assertIsNone(get_seg_average([0, None]))

    def test_collection_time_boundaries(self):
        self.assertEqual('pending', get_seg_collection_phase(time(6, 59, 59)))
        self.assertEqual('collecting', get_seg_collection_phase(time(7)))
        self.assertEqual('collecting', get_seg_collection_phase(time(11, 59, 59)))
        self.assertEqual('complete', get_seg_collection_phase(time(12)))

    def test_each_retailer_uses_own_history_and_raw_count_is_separate(self):
        result, counts, history = self.result([
            {'retailer': 'Mediamarkt', 'main_count': 300, 'bsr_count': 100,
             'actual_count': 318, 'batch_id': 'm-1'},
            {'retailer': 'OTTO', 'main_count': 290, 'bsr_count': 100,
             'actual_count': 290, 'batch_id': 'o-1'},
        ], [
            {'retailer': 'mediamarkt', 'source_date': '2026-09-08', 'main_count': 300},
            {'retailer': 'mediamarkt', 'source_date': '2026-09-06', 'main_count': 301},
            {'retailer': 'otto', 'source_date': '2026-09-08', 'main_count': 280},
        ])
        check = result['check']
        tv = check['categories'][0]
        self.assertEqual(300, tv['retailers'][0]['expected'])
        self.assertEqual(280, tv['retailers'][1]['expected'])
        self.assertEqual(10, tv['retailers'][1]['difference'])
        self.assertIsNone(tv['retailers'][2]['expected'])
        self.assertEqual(608, tv['raw_count'])
        self.assertEqual(590, tv['main_count'])
        self.assertEqual(200, tv['bsr_count'])
        self.assertEqual('KST 07:00~12:00', check['collection_window'])
        self.assertEqual('2026-09-09', check['source_date'])
        self.assertEqual(3, counts.call_count)
        self.assertTrue(all(call.args[2:] == ('2026-09-09', 7)
                            for call in history.call_args_list))
        self.assertEqual(['Mediamarkt', 'OTTO'], [
            row['retailer'] for row in check['categories'][2]['retailers']
        ])

    def test_zero_is_collecting_before_noon_and_critical_at_noon(self):
        collecting, _, _ = self.result(now=datetime(2026, 9, 9, 11, 59))
        completed, _, _ = self.result(now=datetime(2026, 9, 9, 12))
        self.assertEqual('COLLECTING', collecting['check']['status'])
        self.assertEqual([], collecting['failed_items'])
        self.assertEqual('CRITICAL', completed['check']['status'])
        self.assertEqual(8, len(completed['failed_items']))

    def test_utc_clock_is_converted_to_kst(self):
        result, _, _ = self.result(now=datetime(2026, 9, 9, 3, tzinfo=timezone.utc))
        self.assertEqual('complete', result['check']['phase'])

    def test_no_history_does_not_use_current_day_as_its_own_average(self):
        result, _, _ = self.result([
            {'retailer': 'OTTO', 'main_count': 300, 'actual_count': 300},
        ])
        retailer = result['check']['categories'][0]['retailers'][1]
        self.assertIsNone(retailer['expected'])
        self.assertIsNone(retailer['difference'])


if __name__ == '__main__':
    unittest.main()
