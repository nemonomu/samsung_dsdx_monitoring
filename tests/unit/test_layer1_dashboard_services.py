import unittest
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

from tests.unit.support import load_module, module_stub, package_stub


class RecordingCursor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((' '.join(sql.split()), params))


class StatsService:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def get_layer1_stats(self, *_args, **_kwargs):
        self.calls.append((_args, _kwargs))
        if self.error:
            raise self.error
        return self.result


class Layer1DashboardIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        empty_service = module_stub('empty_layer1_service')
        stubs = {
            'apps': package_stub('apps'),
            'apps.common': package_stub('apps.common'),
            'apps.common.db': module_stub(
                'apps.common.db', dx_connection=lambda: None
            ),
            'apps.common.response': module_stub(
                'apps.common.response', log_error=lambda error: str(error)
            ),
            'apps.common.dx_schedules': module_stub(
                'apps.common.dx_schedules',
                load_collection_schedules=lambda: [],
                is_target_date=lambda *_: False,
            ),
            'apps.common.monitoring_exclusions': module_stub(
                'apps.common.monitoring_exclusions',
                DISABLED_CHECK_TYPES=frozenset({
                    'market_trend',
                    'market_demand',
                    'market_promotion',
                    'market_competitor',
                    'market_competitor_event',
                }),
            ),
            'apps.dx': package_stub('apps.dx'),
            'apps.dx.dx_layer1': package_stub('apps.dx.dx_layer1'),
        }

        service_modules = {
            'retail': 'retail_services',
            'sentiment': 'sentiment_services',
            'youtube': 'youtube_services',
            'siel_retail': 'siel_retail_services',
            'tse_retail': 'tse_retail_services',
            'market_trend': 'market_trend_services',
            'market_demand': 'market_demand_services',
            'market_competitor': 'market_competitor_services',
            'market_competitor_event': 'market_competitor_event_services',
            'market_promotion': 'market_promotion_services',
        }
        for package_name, module_name in service_modules.items():
            package_path = f'apps.dx.dx_layer1.{package_name}'
            module_path = f'{package_path}.{module_name}'
            stubs[package_path] = package_stub(package_path)
            stubs[module_path] = empty_service

        macro_module = module_stub('apps.dx.dx_layer1.macro.macro_services')
        for name in (
            'macro_capital_stock_svc', 'macro_net_interest_svc',
            'macro_potential_gdp_svc', 'macro_gdp_ppp_nominal_svc',
            'macro_gdp_ppp_real_svc', 'macro_disposable_income_real_svc',
            'macro_cpi_svc', 'macro_disposable_income_nominal_svc',
            'macro_household_debt_svc', 'macro_rpi_svc',
        ):
            setattr(macro_module, name, empty_service)
        stubs['apps.dx.dx_layer1.macro'] = package_stub(
            'apps.dx.dx_layer1.macro'
        )
        stubs['apps.dx.dx_layer1.macro.macro_services'] = macro_module

        cls.service = load_module(
            'apps/dx/dx_layer1/dashboard/services.py',
            'layer1_dashboard_service_under_test',
            stubs,
        )

    def _run_dashboard(self, youtube_service):
        cursor = RecordingCursor()
        retail_service = StatsService({
            'check': {
                'name': 'TV Retail',
                'check_type': 'retail',
                'status': 'OK',
            },
            'failed_items': [],
        })

        @contextmanager
        def connection():
            yield object(), cursor

        self.service.dx_connection = connection
        self.service._get_active_services = lambda _target: (
            [('youtube', youtube_service), ('retail', retail_service)],
            {'youtube', 'retail'},
            {'youtube', 'retail'},
        )
        result = self.service.get_dashboard_stats(date(2026, 7, 29))
        return result, cursor

    def test_youtube_empty_check_rolls_back_and_preserves_tv(self):
        result, cursor = self._run_dashboard(StatsService({
            'check': None,
            'failed_items': [],
        }))

        self.assertNotIn('error', result)
        self.assertEqual(['retail'], [c['check_type'] for c in result['checks']])
        self.assertEqual('Consumer (YouTube)', result['failed_items'][0]['source'])
        self.assertEqual([
            'SAVEPOINT layer1_youtube_monitoring',
            'ROLLBACK TO SAVEPOINT layer1_youtube_monitoring',
            'RELEASE SAVEPOINT layer1_youtube_monitoring',
        ], [sql for sql, _params in cursor.calls])

    def test_youtube_exception_rolls_back_and_preserves_tv(self):
        result, cursor = self._run_dashboard(StatsService(
            error=RuntimeError('youtube query failed')
        ))

        self.assertNotIn('error', result)
        self.assertEqual(['retail'], [c['check_type'] for c in result['checks']])
        self.assertIn(
            'ROLLBACK TO SAVEPOINT layer1_youtube_monitoring',
            [sql for sql, _params in cursor.calls],
        )

    def test_tse_exception_rolls_back_and_preserves_tv(self):
        cursor = RecordingCursor()
        retail_service = StatsService({
            'check': {
                'name': 'TV Retail',
                'check_type': 'retail',
                'status': 'OK',
            },
            'failed_items': [],
        })

        @contextmanager
        def connection():
            yield object(), cursor

        self.service.dx_connection = connection
        self.service._get_active_services = lambda _target: (
            [
                ('tse_retail', StatsService(error=RuntimeError('tse query failed'))),
                ('retail', retail_service),
            ],
            {'tse_retail', 'retail'},
            {'tse_retail', 'retail'},
        )

        result = self.service.get_dashboard_stats(date(2026, 8, 10))

        self.assertNotIn('error', result)
        self.assertEqual(['retail'], [c['check_type'] for c in result['checks']])
        self.assertEqual('TSE Retail', result['failed_items'][0]['source'])
        self.assertEqual([
            'SAVEPOINT layer1_tse_retail_monitoring',
            'ROLLBACK TO SAVEPOINT layer1_tse_retail_monitoring',
            'RELEASE SAVEPOINT layer1_tse_retail_monitoring',
        ], [sql for sql, _params in cursor.calls])

    def test_siel_exception_rolls_back_and_preserves_tv(self):
        cursor = RecordingCursor()
        retail_service = StatsService({
            'check': {
                'name': 'SEA Retail',
                'check_type': 'retail',
                'status': 'OK',
            },
            'failed_items': [],
        })

        @contextmanager
        def connection():
            yield object(), cursor

        self.service.dx_connection = connection
        original_services = self.service._get_active_services
        self.service._get_active_services = lambda _target: (
            [
                (
                    'siel_retail',
                    StatsService(error=RuntimeError('siel query failed')),
                ),
                ('retail', retail_service),
            ],
            {'siel_retail', 'retail'},
            {'siel_retail', 'retail'},
        )
        try:
            result = self.service.get_dashboard_stats(date(2026, 8, 11))
        finally:
            self.service._get_active_services = original_services

        self.assertNotIn('error', result)
        self.assertEqual(['retail'], [c['check_type'] for c in result['checks']])
        self.assertEqual('SIEL Retail', result['failed_items'][0]['source'])
        self.assertEqual([
            'SAVEPOINT layer1_siel_retail_monitoring',
            'ROLLBACK TO SAVEPOINT layer1_siel_retail_monitoring',
            'RELEASE SAVEPOINT layer1_siel_retail_monitoring',
        ], [sql for sql, _params in cursor.calls])

    def test_siel_service_receives_explicit_kst_clock(self):
        cursor = RecordingCursor()
        siel_service = StatsService({
            'check': {
                'name': 'SIEL Retail',
                'check_type': 'siel_retail',
                'status': 'COLLECTING',
            },
            'failed_items': [],
        })
        expected_now = datetime(
            2026, 8, 11, 8, 59,
            tzinfo=timezone(timedelta(hours=9)),
        )

        @contextmanager
        def connection():
            yield object(), cursor

        self.service.dx_connection = connection
        original_services = self.service._get_active_services
        self.service._get_active_services = lambda _target: (
            [('siel_retail', siel_service)],
            {'siel_retail'},
            {'siel_retail'},
        )
        original_clock = self.service._get_siel_kst_now
        self.service._get_siel_kst_now = lambda: expected_now
        try:
            self.service.get_dashboard_stats(date(2026, 8, 11))
        finally:
            self.service._get_siel_kst_now = original_clock
            self.service._get_active_services = original_services

        self.assertIs(expected_now, siel_service.calls[0][0][2])
        self.assertEqual(timedelta(hours=9), expected_now.utcoffset())

    def test_tse_service_receives_explicit_kst_clock(self):
        cursor = RecordingCursor()
        tse_service = StatsService({
            'check': {
                'name': 'TSE Retail',
                'check_type': 'tse_retail',
                'status': 'COLLECTING',
            },
            'failed_items': [],
        })
        expected_now = datetime(
            2026, 8, 25, 10, 59,
            tzinfo=timezone(timedelta(hours=9)),
        )

        @contextmanager
        def connection():
            yield object(), cursor

        self.service.dx_connection = connection
        self.service._get_active_services = lambda _target: (
            [('tse_retail', tse_service)],
            {'tse_retail'},
            {'tse_retail'},
        )
        original_clock = self.service._get_tse_kst_now
        self.service._get_tse_kst_now = lambda: expected_now
        try:
            self.service.get_dashboard_stats(date(2026, 8, 25))
        finally:
            self.service._get_tse_kst_now = original_clock

        self.assertIs(expected_now, tse_service.calls[0][0][2])
        self.assertEqual(timedelta(hours=9), expected_now.utcoffset())

    def test_stopped_market_services_are_not_activated(self):
        self.service.load_collection_schedules = lambda: [
            {'check_type': 'retail', 'schedule_type': 'daily'},
            {'check_type': 'market_trend', 'schedule_type': 'daily'},
            {'check_type': 'market_demand', 'schedule_type': 'weekly'},
            {'check_type': 'market_promotion', 'schedule_type': 'weekly'},
            {'check_type': 'market_competitor', 'schedule_type': 'quarterly'},
            {'check_type': 'market_competitor_event', 'schedule_type': 'monthly'},
        ]
        self.service.check_target_date = lambda *_: True

        service_order, daily_types, target_types = self.service._get_active_services(
            date(2026, 8, 5)
        )

        self.assertEqual(
            ['retail'],
            [check_type for check_type, _service in service_order],
        )
        self.assertEqual({'retail'}, daily_types)
        self.assertEqual({'retail'}, target_types)

    def test_primary_cards_are_sorted_without_reordering_other_checks(self):
        checks = [
            {'check_type': 'macro_cpi'},
            {'check_type': 'youtube'},
            {'check_type': 'sentiment'},
            {'check_type': 'retail'},
            {'check_type': 'siel_retail'},
            {'check_type': 'tse_retail'},
            {'check_type': 'macro_rpi'},
        ]

        ordered = self.service._sort_checks_for_display(checks)

        self.assertEqual(
            [
                'retail', 'siel_retail', 'tse_retail', 'youtube',
                'macro_cpi', 'sentiment', 'macro_rpi',
            ],
            [check['check_type'] for check in ordered],
        )
        self.assertEqual(
            ['macro_cpi', 'sentiment', 'macro_rpi'],
            [
                check['check_type']
                for check in ordered
                if check['check_type'] not in {
                    'retail', 'siel_retail', 'tse_retail', 'youtube'
                }
            ],
        )


if __name__ == '__main__':
    unittest.main()
