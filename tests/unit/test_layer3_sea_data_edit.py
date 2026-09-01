import unittest
from unittest.mock import patch

from apps.common import inspection_dates, sea_retail, tse_retail
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
        'apps.common.inspection_dates': inspection_dates,
        'apps.common.sea_retail': sea_retail,
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
