import unittest
from datetime import date
from unittest.mock import patch

from tests.unit.support import (
    ScriptedCursor,
    load_module,
    module_stub,
    package_stub,
)


class RecordingCursor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((' '.join(sql.split()), params))


class Layer2DashboardIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stubs = {
            'apps': package_stub('apps'),
            'apps.common': package_stub('apps.common'),
            'apps.common.retail_columns': module_stub(
                'apps.common.retail_columns', validate_field=lambda *_: None
            ),
            'apps.common.retail_validation': module_stub(
                'apps.common.retail_validation',
                get_tv_validation_condition=lambda alias=None: (
                    f"NOT ({alias + '.' if alias else ''}account_name = 'Amazon' "
                    f"AND {alias + '.' if alias else ''}redirect IS TRUE)"
                ),
            ),
            'apps.common.response': module_stub(
                'apps.common.response', log_error=lambda error: str(error)
            ),
            'apps.dx': package_stub('apps.dx'),
            'apps.dx.dx_layer2': package_stub('apps.dx.dx_layer2'),
            'apps.dx.dx_layer2.common': package_stub(
                'apps.dx.dx_layer2.common'
            ),
            'apps.dx.dx_layer2.common.context': module_stub(
                'apps.dx.dx_layer2.common.context',
                get_status=lambda count: 'OK' if count == 0 else 'CRITICAL',
            ),
            'apps.dx.dx_layer2.null_validation': package_stub(
                'apps.dx.dx_layer2.null_validation'
            ),
            'apps.dx.dx_layer2.null_validation.services': module_stub(
                'apps.dx.dx_layer2.null_validation.services',
                get_null_stats=lambda *_args, **_kwargs: ({}, 0),
                get_non_product_exclusion_condition=lambda table: (
                    "NOT EXISTS (SELECT 1 FROM tv_item_mst non_product "
                    "WHERE non_product.is_product IS FALSE)"
                    if table == 'tv_retail_com' else ''
                ),
            ),
            'apps.dx.dx_layer2.format_validation': package_stub(
                'apps.dx.dx_layer2.format_validation'
            ),
            'apps.dx.dx_layer2.format_validation.services': module_stub(
                'apps.dx.dx_layer2.format_validation.services',
                get_format_stats=lambda *_: ({}, 0),
                get_tv_format_errors=lambda *_: [],
                validate_tv_field=lambda *_: None,
            ),
            'apps.dx.dx_layer2.anomaly_validation': package_stub(
                'apps.dx.dx_layer2.anomaly_validation'
            ),
            'apps.dx.dx_layer2.anomaly_validation.services': module_stub(
                'apps.dx.dx_layer2.anomaly_validation.services',
                get_anomaly_stats=lambda *_args, **_kwargs: ({}, 0),
            ),
        }
        cls.service = load_module(
            'apps/dx/dx_layer2/dashboard/services.py',
            'layer2_dashboard_service_under_test',
            stubs,
        )

    def test_failure_rolls_back_and_retries_without_youtube(self):
        cursor = RecordingCursor()
        include_values = []

        def stats(_cursor, _target_date, include_youtube=True):
            include_values.append(include_youtube)
            if include_youtube:
                raise RuntimeError('youtube query failed')
            return {'tables': [{'table': 'tv_retail'}]}, 3

        result = self.service._run_with_youtube_fallback(
            cursor,
            date(2026, 7, 29),
            stats,
            'layer2_youtube_test',
        )

        self.assertEqual([True, False], include_values)
        self.assertEqual(3, result[1])
        self.assertEqual('tv_retail', result[0]['tables'][0]['table'])
        self.assertEqual([
            'SAVEPOINT layer2_youtube_test',
            'ROLLBACK TO SAVEPOINT layer2_youtube_test',
            'RELEASE SAVEPOINT layer2_youtube_test',
        ], [sql for sql, _params in cursor.calls])

    def test_success_releases_without_retry(self):
        cursor = RecordingCursor()
        include_values = []

        def stats(_cursor, _target_date, include_youtube=True):
            include_values.append(include_youtube)
            return {'tables': [{'table': 'tv_retail'}, {'table': 'youtube'}]}, 0

        result = self.service._run_with_youtube_fallback(
            cursor,
            date(2026, 7, 29),
            stats,
            'layer2_youtube_test',
        )

        self.assertEqual([True], include_values)
        self.assertEqual(2, len(result[0]['tables']))
        self.assertEqual([
            'SAVEPOINT layer2_youtube_test',
            'RELEASE SAVEPOINT layer2_youtube_test',
        ], [sql for sql, _params in cursor.calls])

    def test_section_stats_runs_only_requested_validation(self):
        cursor = RecordingCursor()
        null_result = ({'type': 'null', 'tables': []}, 7)
        with patch.object(
            self.service, '_run_with_youtube_fallback',
            return_value=null_result,
        ) as null_stats, patch.object(
            self.service, 'get_format_stats'
        ) as format_stats, patch.object(
            self.service, 'get_anomaly_stats'
        ) as anomaly_stats:
            result = self.service.get_layer_stats(
                cursor, date(2026, 8, 23), 'null_validation'
            )

        null_stats.assert_called_once()
        format_stats.assert_not_called()
        anomaly_stats.assert_not_called()
        self.assertEqual(['null'], [
            item['type'] for item in result['validation_types']
        ])
        self.assertEqual(7, result['summary']['null_issues'])
        self.assertEqual(7, result['summary']['total_issues'])

    def test_rejects_unknown_section(self):
        with self.assertRaises(ValueError):
            self.service.get_layer_stats(
                RecordingCursor(), date(2026, 8, 23), 'unknown'
            )

    def test_null_detail_excludes_item_master_non_products(self):
        cursor = ScriptedCursor([
            {'fetchall': []},
            {'fetchone': (0,)},
        ])

        self.service.get_retailer_detail(
            cursor, 'null', 'TV Retail', 'Amazon', date(2026, 8, 3)
        )

        self.assertEqual(2, len(cursor.calls))
        for sql, _params in cursor.calls:
            self.assertIn('FROM tv_item_mst non_product', sql)
            self.assertIn('non_product.is_product IS FALSE', sql)


if __name__ == '__main__':
    unittest.main()
