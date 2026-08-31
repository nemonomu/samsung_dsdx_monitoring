import unittest
from datetime import date, datetime

from tests.unit.support import load_module


class InspectionDateResolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resolver = load_module(
            'apps/common/inspection_dates.py',
            'tests._inspection_dates_under_test',
        )

    def test_all_fifteen_sources_follow_the_country_offsets(self):
        results = self.resolver.resolve_monitoring_dates('2026-08-20')

        self.assertEqual(15, len(results))
        by_country = {}
        for result in results:
            by_country.setdefault(result['country'], []).append(result)

        self.assertEqual(
            ['SEA', 'SEDA', 'SEG', 'SIEL', 'TSE'],
            list(by_country),
        )
        for country in ('SEA', 'SEDA'):
            self.assertEqual(3, len(by_country[country]))
            self.assertEqual(
                {'2026-08-19'},
                {item['source_date'] for item in by_country[country]},
            )
            self.assertEqual(
                {-1}, {item['offset_days'] for item in by_country[country]}
            )
        for country in ('SEG', 'SIEL', 'TSE'):
            self.assertEqual(3, len(by_country[country]))
            self.assertEqual(
                {'2026-08-20'},
                {item['source_date'] for item in by_country[country]},
            )
            self.assertEqual(
                {0}, {item['offset_days'] for item in by_country[country]}
            )

    def test_calendar_boundaries_include_year_month_and_leap_day(self):
        cases = (
            ('2026-01-01', '2025-12-31'),
            ('2026-03-01', '2026-02-28'),
            ('2024-03-01', '2024-02-29'),
        )

        for inspection_date, expected_source_date in cases:
            with self.subTest(inspection_date=inspection_date):
                result = self.resolver.resolve_monitoring_date(
                    inspection_date, 'SEA', 'sea_tv'
                )
                self.assertEqual(expected_source_date, result['source_date'])

    def test_invalid_dates_fail_closed_without_fallback(self):
        invalid_values = (
            None,
            '',
            '2026-8-20',
            '2026/08/20',
            '2026-02-30',
            '0001-01-01',
            datetime(2026, 8, 20, 12, 0),
        )

        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(self.resolver.MonitoringDateError):
                    self.resolver.resolve_monitoring_date(
                        value, 'SEA', 'sea_tv'
                    )

    def test_date_object_is_accepted(self):
        result = self.resolver.resolve_monitoring_date(
            date(2026, 8, 20), 'TSE', 'tse_ldy'
        )

        self.assertEqual('2026-08-20', result['inspection_date'])
        self.assertEqual('2026-08-20', result['source_date'])

    def test_youtube_uses_the_sea_d_minus_one_contract(self):
        result = self.resolver.resolve_youtube_monitoring_date('2026-08-31')

        self.assertEqual('2026-08-31', result['inspection_date'])
        self.assertEqual('2026-08-30', result['source_date'])
        self.assertEqual(-1, result['offset_days'])
        self.assertEqual('SEA', result['country'])
        self.assertEqual('sea_youtube', result['source_key'])

    def test_unknown_or_mismatched_country_and_source_fail_closed(self):
        invalid_cases = (
            ('US', 'sea_tv'),
            ('SEA', 'unknown_tv'),
            ('SEA', 'seda_tv'),
            (['SEA'], 'sea_tv'),
            ('SEA', ['sea_tv']),
        )

        for country, source_key in invalid_cases:
            with self.subTest(country=country, source_key=source_key):
                with self.assertRaises(self.resolver.MonitoringDateError):
                    self.resolver.resolve_monitoring_date(
                        '2026-08-20', country, source_key
                    )

    def test_resolver_sources_match_existing_email_execution_registry(self):
        registry = load_module(
            'apps/dx/dx_layer4/collection_status/email_registry.py',
            'tests._email_registry_for_inspection_dates',
        )

        expected = {
            (item['key'], item['country'], item['product'])
            for item in registry.EMAIL_REPORT_SOURCES
        }
        self.assertEqual(expected, set(self.resolver.SOURCE_DEFINITIONS))


if __name__ == '__main__':
    unittest.main()
