import unittest
from datetime import date
from unittest.mock import Mock

from apps.common import inspection_dates, retail_validation, siel_retail
from tests.unit.support import (
    ScriptedCursor,
    load_module,
    module_stub,
    package_stub,
)


SIEL_TV_TABLE = 'dx_siel.dx_siel_tv_retail_com'


class SIELLayer2DataEditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stubs = {
            'apps': package_stub('apps'),
            'apps.common': package_stub('apps.common'),
            'apps.common.monitoring_exclusions': module_stub(
                'apps.common.monitoring_exclusions',
                DISABLED_SOURCE_TABLES=frozenset(),
            ),
            'apps.common.retail_columns': module_stub(
                'apps.common.retail_columns',
                get_editable_columns=lambda *_args, **_kwargs: [],
            ),
            'apps.common.retail_validation': retail_validation,
            'apps.common.inspection_dates': inspection_dates,
            'apps.common.sea_retail': module_stub(
                'apps.common.sea_retail', SEA_RETAIL_SOURCES={},
            ),
            'apps.common.siel_retail': siel_retail,
            'apps.common.tse_retail': module_stub(
                'apps.common.tse_retail',
                TSE_TABLE_TO_PRODUCT_LINE={},
                get_tse_editable_columns=lambda _product_line: (),
                get_tse_product_line_for_table=lambda _table: (
                    (_ for _ in ()).throw(ValueError('not TSE'))
                ),
                resolve_tse_table=lambda _table: (
                    (_ for _ in ()).throw(ValueError('not TSE'))
                ),
            ),
        }
        cls.service = load_module(
            'apps/dx/dx_layer2/data_edit/services.py',
            'layer2_siel_data_edit_service_under_test',
            stubs,
        )

    def test_siel_tables_are_allowlisted_without_backup_tables(self):
        self.assertIn(SIEL_TV_TABLE, self.service.VALID_TABLES_UPDATE)
        self.assertIn(
            'dx_siel.dx_siel_ref_retail_com',
            self.service.VALID_TABLES_UPDATE,
        )
        self.assertIn(
            'dx_siel.dx_siel_ldy_retail_com',
            self.service.VALID_TABLES_UPDATE,
        )
        self.assertNotIn(
            'dx_siel.dx_siel_tv_retail_com_backup',
            self.service.VALID_TABLES_UPDATE,
        )

    def test_format_update_uses_siel_day_batch_redirect_and_audit_scope(self):
        cursor = ScriptedCursor([
            {'fetchone': ('109.22 Centimetres', 'Amazon', 'B0FNCLVRW5')},
            {},
            {},
        ])
        conn = Mock()

        result = self.service.update_cell_value(
            cursor, conn, SIEL_TV_TABLE, 107321, 'screen_size',
            '43 Inches', date(2026, 9, 4), 'format', 'tester',
            '화면 크기 단위 수정',
        )

        self.assertTrue(result['success'])
        select_sql, select_params = cursor.calls[0]
        self.assertIn(f'FROM {SIEL_TV_TABLE} source', select_sql)
        self.assertIn("AT TIME ZONE 'Asia/Seoul'", select_sql)
        self.assertIn("IN ('main', 'bsr')", select_sql)
        self.assertIn(
            "NOT (source.account_name = 'Amazon' AND "
            'source.redirect IS TRUE)',
            select_sql,
        )
        self.assertIn('source.batch_id IS NOT DISTINCT FROM', select_sql)
        self.assertEqual(
            (107321, '2026-09-04', '2026-09-04',
             '2026-09-04', '2026-09-04'),
            select_params,
        )
        self.assertIn(
            f'UPDATE {SIEL_TV_TABLE} SET screen_size = %s',
            cursor.calls[1][0],
        )
        history = cursor.calls[2][1]
        self.assertEqual(2, history[0])
        self.assertEqual('format_check', history[1])
        self.assertEqual(SIEL_TV_TABLE, history[2])
        self.assertEqual('corrected', history[10])

    def test_non_format_source_column_cannot_be_changed(self):
        cursor = ScriptedCursor([
            {'fetchone': ('batch-1', 'Amazon', 'B0FNCLVRW5')},
        ])

        result = self.service.update_cell_value(
            cursor, Mock(), SIEL_TV_TABLE, 107321, 'batch_id',
            'batch-2', date(2026, 9, 4), 'format', 'tester', '',
        )

        self.assertEqual(403, result['status'])
        self.assertEqual(1, len(cursor.calls))
        self.assertNotIn('UPDATE', cursor.calls[0][0])


if __name__ == '__main__':
    unittest.main()
