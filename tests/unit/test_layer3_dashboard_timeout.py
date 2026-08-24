import unittest

from tests.unit.support import load_module, module_stub, package_stub


class TimeoutCursor:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def execute(self, sql, params=None):
        normalized = ' '.join(sql.split())
        self.calls.append((normalized, params))
        if self.fail and normalized.startswith('SELECT COUNT(*)'):
            raise TimeoutError('statement timeout')

    def fetchone(self):
        return (4,)


class Layer3DashboardTimeoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        service_attrs = {
            'validate_table_name': lambda _name: None,
            'load_timeseries_rules': lambda: [],
            'validate_all_category_specs': lambda *_args: [],
            'validate_crossfield': lambda *_args: 0,
            'get_crossfield_normal_counts': lambda *_args: {},
            'get_status': lambda *_args, **_kwargs: 'OK',
            'apply_tv_retail_am_filter': lambda query, *_args: query,
        }
        cls.api = load_module(
            'apps/dx/dx_layer3/dashboard/api.py',
            'apps.dx.dx_layer3.dashboard.api',
            stubs={
                'django': package_stub('django'),
                'django.http': module_stub('django.http', JsonResponse=dict),
                'apps': package_stub('apps'),
                'apps.common': package_stub('apps.common'),
                'apps.common.db': module_stub(
                    'apps.common.db', dx_connection=lambda: None
                ),
                'apps.common.monitoring_exclusions': module_stub(
                    'apps.common.monitoring_exclusions',
                    DISABLED_SOURCE_TABLES=set(),
                ),
                'apps.common.response': module_stub(
                    'apps.common.response', log_error=lambda error: str(error)
                ),
                'apps.common.retail_validation': module_stub(
                    'apps.common.retail_validation',
                    get_tv_validation_condition=lambda: 'TRUE',
                ),
                'apps.common.tse_retail': module_stub(
                    'apps.common.tse_retail', TSE_SOURCE_CONFIG={}
                ),
                'apps.dx': package_stub('apps.dx'),
                'apps.dx.dx_layer3': package_stub('apps.dx.dx_layer3'),
                'apps.dx.dx_layer3.cross_field': package_stub(
                    'apps.dx.dx_layer3.cross_field'
                ),
                'apps.dx.dx_layer3.cross_field.tse_services': module_stub(
                    'apps.dx.dx_layer3.cross_field.tse_services'
                ),
                'apps.dx.dx_layer3.dashboard': package_stub(
                    'apps.dx.dx_layer3.dashboard'
                ),
                'apps.dx.dx_layer3.dashboard.services': module_stub(
                    'apps.dx.dx_layer3.dashboard.services', **service_attrs
                ),
            },
        )

    def test_rule_timeout_is_scoped_and_restored_after_success(self):
        cursor = TimeoutCursor()

        count = self.api._count_timeseries_anomalies(
            cursor, 'SELECT COUNT(*) FROM source', ('2026-08-23',)
        )

        self.assertEqual(4, count)
        self.assertEqual([
            'SAVEPOINT layer3_timeseries_rule',
            "SELECT set_config('statement_timeout', %s, true)",
            'SELECT COUNT(*) FROM source',
            'ROLLBACK TO SAVEPOINT layer3_timeseries_rule',
            'RELEASE SAVEPOINT layer3_timeseries_rule',
        ], [sql for sql, _params in cursor.calls])

    def test_timeout_rolls_back_rule_without_poisoning_transaction(self):
        cursor = TimeoutCursor(fail=True)

        with self.assertRaises(TimeoutError):
            self.api._count_timeseries_anomalies(
                cursor, 'SELECT COUNT(*) FROM source', ()
            )

        self.assertEqual(
            'ROLLBACK TO SAVEPOINT layer3_timeseries_rule',
            cursor.calls[-2][0],
        )
        self.assertEqual(
            'RELEASE SAVEPOINT layer3_timeseries_rule',
            cursor.calls[-1][0],
        )


if __name__ == '__main__':
    unittest.main()
