import unittest
from unittest.mock import patch

from apps.common import (
    inspection_dates,
    retail_validation,
    sea_retail,
    seg_retail,
    siel_retail,
    tse_retail,
)
from tests.unit.support import ScriptedCursor, load_module, module_stub, package_stub


services = load_module(
    'apps/dx/dx_layer3/data_edit/services.py',
    'layer3_sea_data_edit_service_under_test',
    {
        'apps': package_stub('apps'),
        'apps.common': package_stub('apps.common'),
        'apps.common.monitoring_exclusions': module_stub(
            'apps.common.monitoring_exclusions',
            DISABLED_SOURCE_TABLES=frozenset(),
        ),
        'apps.common.retail_columns': module_stub(
            'apps.common.retail_columns',
            get_editable_columns=lambda *_: [],
        ),
        'apps.common.retail_price': module_stub(
            'apps.common.retail_price',
            PRICE_EDITABLE_COLUMNS=frozenset({
                'original_sku_price', 'final_sku_price', 'savings',
            }),
        ),
        'apps.common.inspection_dates': inspection_dates,
        'apps.common.retail_validation': retail_validation,
        'apps.common.sea_retail': sea_retail,
        'apps.common.seg_retail': seg_retail,
        'apps.common.siel_retail': siel_retail,
        'apps.common.tse_retail': tse_retail,
    },
)


class FakeConnection:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class SeaLayer3DataEditTests(unittest.TestCase):
    table_name = 'public.ref_retail_com'

    def test_field_missing_defaults_allow_ref_and_ldy_source_fields_and_audit(self):
        for product in ('sea_ref', 'sea_ldy'):
            table = sea_retail.get_sea_retail_source(product)['table_name']
            for retailer in ('Bestbuy', 'Lowes'):
                for field in sea_retail.get_sea_field_missing_editable_columns(product, retailer):
                    with self.subTest(product=product, retailer=retailer, field=field):
                        cursor = ScriptedCursor([{'fetchone': (None, None, retailer, 'fixture-item')}, {}, {}])
                        conn = FakeConnection()
                        result = services.update_cell_value(cursor, conn, table, 31, field,
                            'corrected', '2026-09-22', 'field_missing', 'tester', 'site checked')
                        self.assertTrue(result['success'])
                        self.assertEqual((31, '2026-09-21', '2026-09-21'), cursor.calls[0][1])
                        self.assertIn('UPDATE ' + table, cursor.calls[1][0])
                        self.assertEqual('field_missing', cursor.calls[2][1][1])
                        self.assertEqual('2026-09-22', cursor.calls[2][1][7])
                        self.assertEqual(1, conn.commits)

    def test_field_missing_defaults_do_not_enable_other_fields_retailers_or_crossfield(self):
        for field, retailer, correction_type in [
            ('batch_id', 'Lowes', 'field_missing'),
            ('ref_capacity', 'Unknown', 'field_missing'),
            ('ref_capacity', 'Lowes', 'cross_field'),
            ('ldy_capacity', 'Lowes', 'field_missing'),
        ]:
            with self.subTest(field=field, retailer=retailer, correction_type=correction_type):
                cursor = ScriptedCursor([{'fetchone': (None, None, retailer, 'fixture-item')}])
                conn = FakeConnection()
                result = services.update_cell_value(cursor, conn, self.table_name, 31, field,
                    'changed', '2026-09-22', correction_type, 'tester', None)
                self.assertEqual(403, result['status'])
                self.assertEqual(0, conn.commits)
                self.assertFalse(any('UPDATE ' in sql for sql, _ in cursor.calls))

    def test_field_missing_cannot_update_a_record_outside_current_source_scope(self):
        cursor = ScriptedCursor([{'fetchone': None}])
        conn = FakeConnection()
        result = services.update_cell_value(cursor, conn, self.table_name, 31, 'sku',
            'changed', '2026-09-22', 'field_missing', 'tester', None)
        self.assertEqual(404, result['status'])
        self.assertEqual(0, conn.commits)

    def test_sea_ref_and_ldy_are_exactly_allowlisted(self):
        self.assertIn('public.ref_retail_com', services.VALID_TABLES_UPDATE)
        self.assertIn('public.ldy_retail_com', services.VALID_TABLES_UPDATE)
        self.assertNotIn('public.any_retail_com', services.VALID_TABLES_UPDATE)

    @patch.object(services, 'get_editable_columns',
                  return_value=['final_sku_price'])
    def test_update_uses_d_minus_one_anchor_but_audits_inspection_date(
            self, _editable):
        cursor = ScriptedCursor([
            {'fetchone': ('$900', None, 'Lowes', 'L-1')},
            {},
            {},
        ])
        conn = FakeConnection()

        result = services.update_cell_value(
            cursor, conn, self.table_name, 20, 'final_sku_price', '$890',
            '2026-08-31', 'cross_field', 'tester', '가격 확인', 71,
        )

        self.assertTrue(result['success'])
        source_sql, source_params = cursor.calls[0]
        self.assertIn('FROM public.ref_retail_com source', source_sql)
        self.assertIn("IN ('MAIN', 'BSR')", source_sql)
        self.assertIn("= 'MAIN'", source_sql)
        self.assertEqual((20, '2026-08-30', '2026-08-30'), source_params)
        self.assertIn('UPDATE public.ref_retail_com', cursor.calls[1][0])
        history_params = cursor.calls[2][1]
        self.assertEqual('2026-08-31', history_params[7])
        self.assertEqual(71, history_params[-1])
        self.assertEqual(1, conn.commits)

    @patch.object(services, 'get_editable_columns',
                  return_value=['detailed_review_content'])
    def test_review_body_can_be_edited_on_the_current_sea_source_date(
            self, _editable):
        cursor = ScriptedCursor([
            {'fetchone': (
                'review1 - old', None, 'Lowes', 'L-REVIEW-1',
            )},
            {},
            {},
        ])
        conn = FakeConnection()

        result = services.update_cell_value(
            cursor, conn, 'public.ldy_retail_com', 31,
            'detailed_review_content', 'review1 - corrected',
            '2026-08-31', 'cross_field', 'tester',
            '리뷰본문 수정', 73,
        )

        self.assertTrue(result['success'])
        source_sql, source_params = cursor.calls[0]
        self.assertIn('FROM public.ldy_retail_com source', source_sql)
        self.assertEqual((31, '2026-08-30', '2026-08-30'), source_params)
        update_sql, update_params = cursor.calls[1]
        self.assertIn(
            'UPDATE public.ldy_retail_com SET detailed_review_content = %s',
            update_sql,
        )
        self.assertEqual(('review1 - corrected', 31), update_params)
        self.assertEqual(1, conn.commits)

    def test_normal_review_uses_same_source_scope_and_inspection_date(self):
        cursor = ScriptedCursor([
            {'fetchone': ('$900', 'Bestbuy', 'B-1')},
            {'fetchone': None},
            {},
        ])
        conn = FakeConnection()

        result = services.save_review(
            cursor, conn, 'ldy_retail_com', 30, 'final_sku_price', 'normal',
            '실제 정상', '사이트 확인', '2026-08-31',
            'cross_field', 'tester', 72,
        )

        self.assertTrue(result['success'])
        source_sql, source_params = cursor.calls[0]
        self.assertIn('FROM public.ldy_retail_com source', source_sql)
        self.assertEqual((30, '2026-08-30', '2026-08-30'), source_params)
        duplicate_params = cursor.calls[1][1]
        self.assertEqual('2026-08-31', duplicate_params[-1])
        insert_params = cursor.calls[2][1]
        self.assertEqual('2026-08-31', insert_params[7])
        self.assertEqual(72, insert_params[-1])
        self.assertEqual(1, conn.commits)


if __name__ == '__main__':
    unittest.main()
