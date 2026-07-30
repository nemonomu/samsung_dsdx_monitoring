import unittest
from contextlib import contextmanager
from datetime import date

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

    def get_layer1_stats(self, *_args, **_kwargs):
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
            'apps.dx': package_stub('apps.dx'),
            'apps.dx.dx_layer1': package_stub('apps.dx.dx_layer1'),
        }

        service_modules = {
            'retail': 'retail_services',
            'sentiment': 'sentiment_services',
            'youtube': 'youtube_services',
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


if __name__ == '__main__':
    unittest.main()
