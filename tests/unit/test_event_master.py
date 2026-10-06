import unittest
from datetime import date, datetime, timezone
from unittest.mock import Mock

from apps.dx.dx_layer1.event_master import services as svc, repositories


class EventMasterTests(unittest.TestCase):
    def check(self, groups=(), selected='2026-10-06', now=None):
        groups = [(*row, '2026-10-05') if len(row) == 3 else row for row in groups]
        return svc.build_check(selected, groups, now or datetime(2026, 10, 6, 13))

    def test_master_has_57_distinct_countries(self):
        self.assertEqual(57, len(svc.COUNTRIES))
        self.assertEqual(57, len(set(svc.COUNTRIES.values())))

    def test_selected_month_determines_date(self):
        for selected, expected in [('2026-10-06', '2026-10-05'),
                                   ('2026-10-31', '2026-10-05'),
                                   ('2026-09-15', '2026-09-07')]:
            self.assertEqual(expected, self.check(selected=selected)['execution_date'])
        self.assertEqual('PENDING', self.check(selected='2026-10-01')['status'])

    def test_kst_start_and_deadline(self):
        for hour, minute, status in [(0, 29, 'PENDING'), (0, 30, 'COLLECTING'),
                                      (4, 59, 'COLLECTING'), (5, 0, 'COLLECTING')]:
            self.assertEqual(status, self.check(selected='2026-10-05',
                now=datetime(2026, 10, 5, hour, minute))['status'])
        self.assertEqual('COLLECTING', self.check(selected='2026-10-05',
            now=datetime(2026, 10, 4, 20, tzinfo=timezone.utc))['status'])

    def test_received_countries_normal_before_deadline(self):
        groups = [(name, code, 1) for code, name in svc.COUNTRIES.items()]
        check = self.check(groups, now=datetime(2026, 10, 5, 1))
        self.assertEqual(('OK', 57), (check['status'], check['actual']))

    def test_partial_receipt_and_missing_country(self):
        check = self.check([('GERMANY', 'DE', 30)], now=datetime(2026, 10, 5, 1))
        self.assertEqual('COLLECTING', check['status'])
        self.assertEqual('OK', next(r for r in check['countries'] if r['country_code'] == 'DE')['status'])
        self.assertEqual(56, check['missing'])
        self.assertEqual('COLLECTING', self.check([('GERMANY', 'DE', 30)])['status'])

    def test_alias_scopes_and_mismatched_code(self):
        check = self.check([('NEW ZEALAND', 'NZ_eStore', 18), ('NEW ZELAND', 'NZ', 1),
                            ('GERMANY', 'US_AMAZON', 2)])
        nz = next(r for r in check['countries'] if r['country_code'] == 'NZ')
        self.assertEqual((19, 0, 'OK'), (nz['count'], nz['issue_count'], nz['status']))
        self.assertEqual(2, check['actual'])
        de = next(r for r in check['countries'] if r['country_code'] == 'DE')
        self.assertEqual('REVIEW', de['status'])

    def test_known_typo_does_not_flag_fully_received_month(self):
        groups = [(name, code, 1) for code, name in svc.COUNTRIES.items()]
        check = self.check(groups + [('NEW ZELAND', 'NZ', 1)])
        self.assertEqual(('OK', 57, 0), (check['status'], check['actual'], check['review_count']))

    def test_extra_country_does_not_replace_missing(self):
        groups = [(name, code, 1) for code, name in svc.COUNTRIES.items() if code != 'DE']
        check = self.check(groups + [('BELGIUM', 'BE', 1)])
        self.assertEqual((56, 1, 1, 'REVIEW'),
            (check['actual'], check['missing'], check['unexpected_count'], check['status']))
        check = self.check(groups + [('GERMANY', 'DE', 1), ('BELGIUM', 'BE', 1)])
        self.assertEqual('REVIEW', check['status'])

    def test_repository_uses_execution_date_not_batch(self):
        cursor = Mock()
        repositories.country_counts(cursor, '2026-10-05', '2026-10-06')
        sql, params = cursor.execute.call_args.args
        self.assertIn('execution_date BETWEEN %s AND %s', sql)
        self.assertNotIn('batch_id', sql)
        self.assertEqual(('2026-10-05', '2026-10-06'), params)

    def test_tuesday_receipt_and_wednesday_next_schedule(self):
        groups = [('GERMANY', 'DE', 10, '2026-10-05'), ('GERMANY', 'DE', 5, '2026-10-06')]
        check = self.check(groups, selected='2026-10-07', now=datetime(2026, 10, 7))
        self.assertEqual('PENDING', check['status'])
        self.assertEqual('2026-11-02', check['scheduled_date'])
        de = next(r for r in check['countries'] if r['country_code'] == 'DE')
        self.assertEqual(('OK', 15, '2026-10-06'), (de['status'], de['count'], de['execution_date']))
        self.assertTrue(all(r['status'] in ('OK', 'PENDING') for r in check['countries']))
        self.assertEqual('COLLECTING', self.check(now=datetime(2026, 10, 6, 23, 59))['status'])
        december = self.check(selected='2026-12-09', now=datetime(2026, 12, 9))
        self.assertEqual('2027-01-04', december['scheduled_date'])

    def test_closed_window_still_queries_receipts(self):
        cursor = Mock()
        cursor.fetchall.return_value = [('GERMANY', 'DE', 2, date(2026, 10, 6))]
        result = svc.get_layer1_stats(cursor, date(2026, 10, 7), datetime(2026, 10, 7))
        self.assertEqual(1, result['check']['actual'])
        self.assertEqual([], result['failed_items'])
        self.assertEqual('2026-10-05', self.check(selected='2026-10-05')['query_end_date'])

    def test_query_error_isolated_not_missing(self):
        cursor = Mock()
        cursor.fetchall.side_effect = RuntimeError('query failed')
        result = svc.get_layer1_stats(cursor, date(2026, 10, 6), datetime(2026, 10, 6))
        self.assertEqual('ERROR', result['check']['status'])
        self.assertIsNone(result['check']['actual'])
        cursor.execute.assert_any_call('ROLLBACK TO SAVEPOINT layer1_event_master')
        cursor.execute.assert_any_call('RELEASE SAVEPOINT layer1_event_master')

    def test_pending_does_not_query_future_receipts(self):
        cursor = Mock()
        result = svc.get_layer1_stats(cursor, date(2026, 10, 1), datetime(2026, 10, 6))
        self.assertEqual('PENDING', result['check']['status'])
        cursor.execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
