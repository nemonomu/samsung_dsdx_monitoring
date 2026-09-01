import unittest
from datetime import date
from unittest.mock import patch

from tests.unit.support import (
    ScriptedCursor,
    load_module,
    module_stub,
    package_stub,
)


SEA_SOURCES = {
    'tv': {
        'key': 'tv', 'product_key': 'tv', 'product_line': 'tv',
        'source_key': 'sea_tv', 'category': 'TV',
        'table_name': 'public.tv_retail_com',
        'backup_table': 'public.tv_retail_com_backup_all',
        'date_column': 'crawl_datetime',
        'retailers': ('Amazon', 'Bestbuy', 'Walmart'),
    },
    'ref': {
        'key': 'sea_ref', 'product_key': 'ref',
        'product_line': 'sea_ref', 'source_key': 'sea_ref',
        'category': 'REF', 'table_name': 'public.ref_retail_com',
        'backup_table': 'public.ref_retail_com_backup',
        'date_column': 'crawl_strdatetime',
        'retailers': ('Bestbuy', 'Lowes'),
    },
    'ldy': {
        'key': 'sea_ldy', 'product_key': 'ldy',
        'product_line': 'sea_ldy', 'source_key': 'sea_ldy',
        'category': 'LDY', 'table_name': 'public.ldy_retail_com',
        'backup_table': 'public.ldy_retail_com_backup',
        'date_column': 'crawl_strdatetime',
        'retailers': ('Bestbuy', 'Lowes'),
    },
}


def resolve_date(inspection_date, _country, source_key):
    return {
        'inspection_date': str(inspection_date),
        'source_date': '2026-08-31',
        'offset_days': -1,
        'source_key': source_key,
    }


def common_stubs():
    return {
        'apps': package_stub('apps'),
        'apps.common': package_stub('apps.common'),
        'apps.common.db': module_stub(
            'apps.common.db', dx_table=lambda table: table,
        ),
        'apps.common.retail_columns': module_stub(
            'apps.common.retail_columns',
            validate_field=lambda *_args, **_kwargs: None,
            build_format_error_sql=lambda *_args, **_kwargs: 'FALSE',
            build_per_field_error_sql=lambda *_args, **_kwargs: [],
            get_editable_columns=lambda product, _retailer: (
                ['detailed_review_content']
                if product in {'sea_ref', 'sea_ldy'} else []
            ),
            get_duplicate_key_columns=lambda *_args, **_kwargs: None,
            get_retailer_list=lambda: ['Amazon', 'Bestbuy', 'Walmart'],
            get_retail_duplicate_keys=lambda *_args, **_kwargs: [],
        ),
        'apps.common.retail_validation': module_stub(
            'apps.common.retail_validation',
            get_tv_validation_condition=lambda *_args: 'TRUE',
        ),
        'apps.common.monitoring_exclusions': module_stub(
            'apps.common.monitoring_exclusions',
            DISABLED_SOURCE_TABLES=frozenset(),
        ),
        'apps.common.inspection_dates': module_stub(
            'apps.common.inspection_dates',
            resolve_monitoring_date=resolve_date,
        ),
        'apps.common.sea_retail': module_stub(
            'apps.common.sea_retail', SEA_RETAIL_SOURCES=SEA_SOURCES,
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
    }


class SEAFormatValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = load_module(
            'apps/dx/dx_layer2/format_validation/services.py',
            'layer2_sea_format_service_under_test',
            common_stubs(),
        )

    def test_ref_and_ldy_are_allow_listed_with_only_approved_fields(self):
        self.assertTrue({
            'sea_ref_retail', 'sea_ldy_retail',
        }.issubset(self.service.VALID_TABLES_FORMAT))
        self.assertTrue({
            'ref_retail_com', 'ldy_retail_com',
        }.issubset(self.service.VALID_TABLES_RULES))

        common = set(self.service.SEA_FORMAT_COMMON_FIELDS)
        self.assertTrue({
            'item', 'product_url', 'page_type', 'count_of_reviews',
            'count_of_star_ratings', 'star_rating', 'final_sku_price',
            'original_sku_price', 'savings', 'detailed_review_content',
        }.issubset(common))
        self.assertFalse({
            'recommendation_intent', 'main_rank', 'bsr_rank',
            'ref_refrigerator_type', 'sku', 'retailer_sku_name',
        } & common)

    def test_row_evaluation_uses_only_the_approved_field_list(self):
        calls = []

        def validate(_table, field, _value, *_args, **_kwargs):
            calls.append(field)
            return 'item 형식 오류' if field == 'item' else None

        with patch.object(self.service, 'validate_field', validate):
            errors = self.service.evaluate_sea_format_row(
                {'item': 'bad-value'}, 'ref', 'Bestbuy'
            )

        self.assertEqual({'item': 'item 형식 오류'}, errors)
        self.assertEqual(
            set(self.service._get_sea_format_fields('ref')), set(calls)
        )
        self.assertNotIn('ref_refrigerator_type', calls)
        self.assertNotIn('recommendation_intent', calls)

    def test_query_uses_latest_main_batch_and_includes_main_and_bsr(self):
        cursor = ScriptedCursor([{'fetchall': []}])
        rows = self.service._fetch_sea_format_rows(
            cursor, date(2026, 8, 30), date(2026, 8, 31),
            SEA_SOURCES['ref'], 'Bestbuy',
        )

        self.assertEqual([], rows)
        sql, params = cursor.calls[0]
        self.assertIn('WITH latest_batches AS', sql)
        self.assertIn("= 'MAIN'", sql)
        self.assertIn("IN ('MAIN', 'BSR')", sql)
        self.assertIn('source.batch_id IS NOT DISTINCT FROM', sql)
        self.assertEqual(
            ('2026-08-30', '2026-08-31', 'Bestbuy',
             '2026-08-30', '2026-08-31', 'Bestbuy'),
            params,
        )

    def test_detail_maps_inspection_to_d_minus_one_and_shows_two_days(self):
        target = {
            'id': 10, 'item': 'A1', 'crawl_strdatetime': '2026-08-31',
            'detailed_review_content': 'bad', 'product_url': 'https://x',
        }
        history = {
            'id': 9, 'item': 'A1', 'crawl_strdatetime': '2026-08-30',
            'detailed_review_content': 'review1 - ok',
            'product_url': 'https://x',
        }

        def evaluate(row, *_args):
            return (
                {'detailed_review_content': '본문 형식 오류'}
                if row['id'] == 10 else {}
            )

        with patch.object(
            self.service, '_fetch_sea_format_rows',
            side_effect=[[target], [history, target]],
        ), patch.object(
            self.service, '_load_sea_format_normal_reviews', return_value={},
        ), patch.object(
            self.service, 'evaluate_sea_format_row', side_effect=evaluate,
        ):
            result = self.service._get_sea_format_detail(
                object(), '2026-09-01', 'sea_ref_retail', 'Bestbuy', 2
            )

        self.assertEqual('2026-09-01', result['inspection_date'])
        self.assertEqual('2026-08-31', result['source_date'])
        self.assertEqual('2026-08-31', result['editable_date'])
        self.assertEqual(2, result['history_days'])
        self.assertEqual([9, 10], [row['id'] for row in result['results']])
        self.assertNotIn('batch_id', result['column_names'])
        self.assertIn('product_url', result['column_names'])
        self.assertIn('detailed_review_content', result['editable_cols'])


class SEADuplicateValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = load_module(
            'apps/dx/dx_layer2/anomaly_validation/services.py',
            'layer2_sea_duplicate_service_under_test',
            common_stubs(),
        )

    def test_same_item_in_different_page_types_is_not_a_duplicate(self):
        groups = self.service.build_sea_duplicate_groups([
            {'id': 1, 'page_type': 'main', 'item': 'A1', 'sku': 'S1'},
            {'id': 2, 'page_type': 'bsr', 'item': 'A1', 'sku': 'S1'},
        ])
        self.assertEqual([], groups)

    def test_duplicate_groups_distinguish_exact_and_mapping_conflict(self):
        groups = self.service.build_sea_duplicate_groups([
            {
                'id': 1, 'page_type': 'main', 'item': 'A1', 'sku': 'S1',
                'retailer_sku_name': 'Name 1',
            },
            {
                'id': 2, 'page_type': 'main', 'item': 'A1', 'sku': 'S1',
                'retailer_sku_name': 'Name 1',
            },
            {
                'id': 3, 'page_type': 'bsr', 'item': 'B1', 'sku': 'S2',
                'retailer_sku_name': 'Name 2',
            },
            {
                'id': 4, 'page_type': 'bsr', 'item': 'B1', 'sku': 'S3',
                'retailer_sku_name': 'Name 3',
            },
        ])

        self.assertEqual(2, len(groups))
        self.assertEqual(
            {'완전 중복', '상품 매핑 충돌'},
            {group['duplicate_type'] for group in groups},
        )

        blank_conflict = self.service.build_sea_duplicate_groups([
            {
                'id': 5, 'page_type': 'main', 'item': 'C1', 'sku': '',
                'retailer_sku_name': '',
            },
            {
                'id': 6, 'page_type': 'main', 'item': 'C1', 'sku': 'S4',
                'retailer_sku_name': 'Name 4',
            },
        ])
        self.assertEqual('상품 매핑 충돌', blank_conflict[0]['duplicate_type'])

    def test_detail_uses_d_minus_one_and_hides_batch_id(self):
        rows = [
            {'id': 1, 'page_type': 'main', 'item': 'A1', 'sku': 'S1'},
            {'id': 2, 'page_type': 'main', 'item': 'A1', 'sku': 'S1'},
        ]
        with patch.object(
            self.service, '_fetch_sea_duplicate_rows', return_value=rows,
        ) as fetch:
            result = self.service._get_sea_anomaly_detail(
                object(), '2026-09-01', 'sea_ldy_retail', 'Lowes', 1, 20
            )

        fetch.assert_called_once_with(
            unittest.mock.ANY, date(2026, 8, 31),
            SEA_SOURCES['ldy'], 'Lowes',
        )
        self.assertEqual('2026-08-31', result['source_date'])
        self.assertFalse(result['readonly'])
        self.assertEqual(
            'public.ldy_retail_com_backup', result['backup_table']
        )
        self.assertNotIn('batch_id', result['select_cols']['record'])
        self.assertIn('product_url', result['select_cols']['record'])

    def test_cleanup_limits_ids_to_latest_batch_and_writes_both_backups(self):
        records = [
            (1, {
                'id': 1, 'page_type': 'main', 'item': 'A1',
                'account_name': 'Bestbuy',
            }),
            (2, {
                'id': 2, 'page_type': 'main', 'item': 'A1',
                'account_name': 'Bestbuy',
            }),
        ]
        cursor = ScriptedCursor([
            {'fetchall': records},
            {},
            {}, {},
            {}, {},
            {'rowcount': 2},
        ])

        result = self.service.cleanup_duplicates(
            cursor, object(), 'sea_ref_retail', [1, 2],
            '2026-09-01', 'tester',
        )

        self.assertTrue(result['success'])
        self.assertEqual(2, result['deleted_count'])
        self.assertEqual(
            'public.ref_retail_com_backup', result['backup_table']
        )
        self.assertEqual(
            'monitoring_duplicate_deletes', result['audit_backup_table']
        )
        select_sql, select_params = cursor.calls[0]
        self.assertIn('WITH latest_batches AS', select_sql)
        self.assertIn("IN ('MAIN', 'BSR')", select_sql)
        self.assertEqual('2026-08-31', select_params[0])
        self.assertIn(
            'INSERT INTO public.ref_retail_com_backup', cursor.calls[1][0]
        )
        self.assertEqual(
            'DELETE FROM public.ref_retail_com WHERE id IN (%s, %s)',
            cursor.calls[-1][0],
        )


if __name__ == '__main__':
    unittest.main()
