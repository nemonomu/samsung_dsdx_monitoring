import unittest
from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace
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

    def test_dashboard_omits_report_auto_details_and_preserves_review_counts(self):
        null_validation = {
            'type': 'null', 'auto_reviewed_count': 3, 'reviewed_null_count': 4,
            'auto_null_reviews': [{'record_id': 42, 'reason': '상품페이지 내 항목 부재'}],
            'tables': [{
                'table': 'tse_ref_retail', 'total_issues': 2,
                'auto_reviewed_count': 3, 'reviewed_null_count': 4,
                'retailers': [{'retailer': 'Homepro', 'auto_reviewed_count': 3}],
            }],
        }
        with patch.object(self.service, '_run_with_youtube_fallback',
                          return_value=(null_validation, 2)):
            result = self.service.get_layer_stats(
                RecordingCursor(), date(2026, 9, 13), 'null_validation',
            )

        payload = result['validation_types'][0]
        self.assertNotIn('auto_null_reviews', payload)
        self.assertEqual(3, payload['auto_reviewed_count'])
        self.assertEqual(4, payload['reviewed_null_count'])
        self.assertEqual(null_validation['tables'], payload['tables'])
        self.assertEqual(2, result['summary']['null_issues'])
        self.assertEqual(2, result['summary']['total_issues'])
        # Filtering the UI payload must not mutate the source used by report code.
        self.assertEqual(1, len(null_validation['auto_null_reviews']))

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

    def test_new_null_refresh_supports_all_five_countries_and_three_products(self):
        table_codes = ['tv_retail', 'sea_ref_retail', 'sea_ldy_retail'] + [
            f'{country}_{product}_retail'
            for country in ('sem', 'siel', 'tse', 'seg')
            for product in ('tv', 'ref', 'ldy')
        ]
        for table_code in table_codes:
            with self.subTest(table=table_code):
                cursor = RecordingCursor()
                retailer = {
                    'retailer': 'Example Retailer', 'total': 12,
                    'total_null_count': 1,
                    'fields_detail': {'final_sku_price': 1, 'star_rating': 0},
                    'raw_fields_detail': {'final_sku_price': 2, 'star_rating': 2},
                    'reviewed_fields_detail': {'final_sku_price': 1, 'star_rating': 2},
                    'manual_reviewed_fields_detail': {'final_sku_price': 0, 'star_rating': 1},
                    'auto_reviewed_fields_detail': {'final_sku_price': 1, 'star_rating': 1},
                    'raw_null_count': 4, 'reviewed_null_count': 3,
                    'manual_reviewed_count': 1, 'auto_reviewed_count': 2,
                    'supports_null_auto_review': True,
                }
                validation = {'tables': [
                    {'table': 'unrelated_table', 'retailers': [dict(retailer, total_null_count=99)]},
                    {'table': table_code, 'retailers': [retailer]},
                ]}
                with patch.object(self.service, 'get_null_stats',
                                  return_value=(validation, 1)) as stats:
                    result = self.service.get_retailer_detail(
                        cursor, 'null', table_code, 'Example Retailer', date(2026, 9, 12),
                    )

                stats.assert_called_once_with(cursor, date(2026, 9, 12), include_youtube=False)
                self.assertEqual(retailer['fields_detail'], result['field_counts'])
                for key in (
                    'raw_fields_detail', 'reviewed_fields_detail', 'raw_null_count',
                    'manual_reviewed_fields_detail', 'auto_reviewed_fields_detail',
                    'reviewed_null_count', 'manual_reviewed_count',
                    'auto_reviewed_count', 'supports_null_auto_review',
                ):
                    self.assertEqual(retailer[key], result[key])
                self.assertEqual(1, result['total'])
                self.assertEqual(12, result['total_records'])
                self.assertEqual('2026-09-12', result['date'])
                self.assertEqual([], cursor.calls)

    def test_new_null_refresh_keeps_fields_visible_when_all_are_reviewed(self):
        retailer = {
            'retailer': 'Lowes', 'total': 3, 'total_null_count': 0,
            'fields_detail': {'ref_capacity': 0},
            'raw_fields_detail': {'ref_capacity': 3},
            'reviewed_fields_detail': {'ref_capacity': 3},
            'manual_reviewed_fields_detail': {'ref_capacity': 1},
            'auto_reviewed_fields_detail': {'ref_capacity': 2},
            'raw_null_count': 3, 'reviewed_null_count': 3,
            'manual_reviewed_count': 1, 'auto_reviewed_count': 2,
            'supports_null_auto_review': True,
        }
        with patch.object(self.service, 'get_null_stats', return_value=({
            'tables': [{'table': 'sea_ref_retail', 'retailers': [retailer]}],
        }, 0)):
            result = self.service.get_retailer_detail(
                RecordingCursor(), 'null', 'sea_ref_retail', 'Lowes', date(2026, 9, 13),
            )

        self.assertEqual(0, result['total'])
        self.assertEqual({'ref_capacity': 0}, result['field_counts'])
        self.assertEqual({'ref_capacity': 3}, result['raw_fields_detail'])
        self.assertEqual({'ref_capacity': 1}, result['manual_reviewed_fields_detail'])
        self.assertEqual({'ref_capacity': 2}, result['auto_reviewed_fields_detail'])
        self.assertEqual(2, result['auto_reviewed_count'])

    def test_legacy_display_name_routes_to_new_sea_tv_summary(self):
        with patch.object(self.service, 'get_null_stats', return_value=({
            'tables': [{'table': 'tv_retail', 'retailers': [{
                'retailer': 'Amazon', 'total_null_count': 0,
                'fields_detail': {'item': 0}, 'supports_null_auto_review': True,
            }]}],
        }, 0)) as stats:
            result = self.service.get_retailer_detail(
                RecordingCursor(), 'null', 'TV Retail', 'Amazon', date(2026, 9, 12),
            )
        stats.assert_called_once()
        self.assertEqual({'item': 0}, result['field_counts'])

    def test_new_refresh_rejects_missing_retailer_instead_of_reporting_zero_issues(self):
        with patch.object(self.service, 'get_null_stats', return_value=({
            'tables': [{'table': 'sem_tv_retail', 'retailers': [{'retailer': 'Liverpool'}]}],
        }, 0)):
            result = self.service.get_retailer_detail(
                RecordingCursor(), 'null', 'sem_tv_retail', 'Unknown', date(2026, 9, 12),
            )
        self.assertIn('error', result)
        self.assertNotIn('field_counts', result)

    def test_new_refresh_does_not_expand_pre_cutoff_or_non_null_support(self):
        for validation_type, target_date, table_code in [
            ('null', date(2026, 9, 11), 'sem_tv_retail'),
            ('format', date(2026, 9, 12), 'sem_tv_retail'),
            ('anomaly', date(2026, 9, 12), 'sem_tv_retail'),
            ('null', date(2026, 9, 12), 'unknown_tv_retail'),
            ('null', date(2026, 9, 12), 'seda_tv_retail'),
        ]:
            with self.subTest(validation=validation_type, date=target_date, table=table_code):
                with patch.object(self.service, 'get_null_stats') as stats:
                    result = self.service.get_retailer_detail(
                        RecordingCursor(), validation_type, table_code, 'Retailer', target_date,
                    )
                self.assertIn('error', result)
                stats.assert_not_called()

    def load_api(self):
        @contextmanager
        def connection():
            yield object(), RecordingCursor()

        return load_module(
            'apps/dx/dx_layer2/dashboard/api.py',
            'layer2_dashboard_api_under_test',
            stubs={
                'django.http': module_stub(
                    'django.http', JsonResponse=lambda data, status=200: SimpleNamespace(data=data, status_code=status),
                ),
                'apps.common.db': module_stub('apps.common.db', dx_connection=connection),
                'apps.common.response': module_stub('apps.common.response', log_error=str),
                'apps.common.params': module_stub('apps.common.params', parse_date=date.fromisoformat),
                'apps.dx.dx_layer2.dashboard': module_stub(
                    'apps.dx.dx_layer2.dashboard', services=self.service,
                ),
            },
        )

    def test_endpoint_allows_new_null_section_but_rejects_unknown_categories(self):
        api = self.load_api()
        for table, validation, day, expected_status in [
            ('sem_tv_retail', 'null', '2026-09-12', 200),
            ('sea_ref_retail', 'null', '2026-09-13', 200),
            ('unknown_tv_retail', 'null', '2026-09-12', 400),
            ('seda_tv_retail', 'null', '2026-09-12', 400),
            ('sem_tv_retail', 'null', '2026-09-11', 400),
            ('sem_tv_retail', 'format', '2026-09-12', 400),
            ('TV Retail', 'format', '2026-09-12', 200),
        ]:
            with self.subTest(table=table, validation=validation, day=day):
                request = SimpleNamespace(GET={
                    'table': table, 'type': validation, 'retailer': 'Retailer', 'date': day,
                })
                with patch.object(self.service, 'get_retailer_detail', return_value={}) as detail:
                    response = api.retailer_detail(request)
                self.assertEqual(expected_status, response.status_code)
                if expected_status == 200:
                    detail.assert_called_once()
                else:
                    detail.assert_not_called()


if __name__ == '__main__':
    unittest.main()
