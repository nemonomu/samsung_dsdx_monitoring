import json
import unittest
from datetime import date
from unittest.mock import Mock

from apps.ds.cause_history import attach_cause_history, record_cause_application
from apps.ds.ds_layer2.report.anomaly_causes import carry_forward_causes


def sample(**kwargs):
    return dict(dict(id=7, retailer_id=3, retailersku='SKU', title='SSD',
                     retailprice='399.99', ships_from=None, sold_by='Currys',
                     imageurl='https://example.com/image', cause='원인 A'), **kwargs)


class CauseHistoryTests(unittest.TestCase):
    def test_carry_source_uses_previous_values_and_stable_id(self):
        previous = sample(id=2, title='과거 제목', screenshot_id=99)
        current = sample(id=7, cause='', title='오늘 제목', _cause_source={'id': 999})
        result = carry_forward_causes([current], [previous, sample(id=1)])[0]
        self.assertEqual(result['_cause_source'], previous)
        self.assertEqual(current['_cause_source'], {'id': 999})
        direct = carry_forward_causes([sample(_cause_source={'id': 999})], [previous])[0]
        self.assertNotIn('_cause_source', direct)

    def test_snapshot_is_written_without_changing_existing_data(self):
        cursor = Mock()
        cursor.fetchone.return_value = None
        source = sample(crawl_date=date(2026, 9, 22), screenshot_id=99)
        record_cause_application(cursor, 7, '원인 A', 'tester', '2026-09-23 12:00:00', source)
        sql, params = cursor.execute.call_args.args
        self.assertIn('INSERT INTO', sql)
        self.assertEqual(params[:3], (7, 'automatic', '원인 A'))
        snapshot = json.loads(params[3])
        self.assertEqual(snapshot['crawl_date'], '2026-09-22')
        self.assertEqual(snapshot['screenshot_id'], 99)
        self.assertEqual(snapshot['retailprice'], '399.99')

    def test_same_cause_does_not_replace_original_source(self):
        cursor = Mock()
        cursor.fetchone.return_value = ('원인 A',)
        record_cause_application(cursor, 7, '원인 A', 'tester', '2026-09-23')
        self.assertEqual(cursor.execute.call_count, 1)

    def test_manual_change_is_recorded_without_a_past_snapshot(self):
        cursor = Mock()
        cursor.fetchone.return_value = ('원인 A',)
        record_cause_application(cursor, 7, '원인 B', 'tester', '2026-09-23')
        self.assertEqual(cursor.execute.call_args.args[1][1:4], ('manual', '원인 B', None))

    def test_recorded_source_takes_precedence_over_reconstructed_evidence(self):
        cursor = Mock()
        source = sample(id=2, screenshot_id=99)
        cursor.fetchall.return_value = [(7, 'automatic', '원인 A', json.dumps(source), '2026-09-23', 'tester')]
        current = sample()
        attach_cause_history(cursor, [current], '2026-09-23')
        self.assertEqual(current['cause_history']['source']['id'], 2)
        self.assertEqual(current['cause_history']['status'], 'automatic')
        self.assertEqual(cursor.execute.call_count, 1)

    def test_legacy_matching_requires_retailer_sku_signature_and_unique_cause(self):
        for retailer_id, sku, ships_from, extra_cause, expected in [
            (3, 'sku', None, None, 'legacy_match'),
            (4, 'sku', None, None, 'unrecorded'),
            (3, 'different', None, None, 'unrecorded'),
            (3, 'sku', 'gb', None, 'unrecorded'),
            (3, 'sku', None, '원인 B', 'unrecorded'),
        ]:
            with self.subTest(retailer=retailer_id, sku=sku, extra=extra_cause):
                row = (2, date(2026, 9, 22), sku, '과거 제목', '299', ships_from, 'Old Seller',
                       'https://example.com/old', 99, '원인 A', None, 'reviewer', None, None, retailer_id)
                rows = [row]
                if extra_cause:
                    rows.append((*row[:9], extra_cause, *row[10:]))
                cursor = Mock()
                cursor.fetchall.side_effect = [[], rows]
                current = sample()
                attach_cause_history(cursor, [current], '2026-09-23')
                self.assertEqual(current['cause_history']['status'], expected)
                self.assertEqual(cursor.execute.call_args.args[1], [date(2026, 9, 22), 3])
                if expected == 'legacy_match':
                    self.assertEqual(current['cause_history']['source']['sold_by'], 'Old Seller')

    def test_empty_current_cause_is_not_labeled_as_auto_applied(self):
        cursor = Mock()
        cursor.fetchall.return_value = []
        current = sample(cause='')
        attach_cause_history(cursor, [current], '2026-09-23')
        self.assertEqual(current['cause_history']['status'], 'none')
        self.assertEqual(cursor.execute.call_count, 1)


if __name__ == '__main__':
    unittest.main()
