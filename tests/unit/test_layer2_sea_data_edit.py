import unittest
from datetime import date
from unittest.mock import Mock

from tests.unit.support import (
    ScriptedCursor,
    load_module,
    module_stub,
    package_stub,
)


SEA_SOURCES = {
    'ref': {
        'product_key': 'ref',
        'product_line': 'sea_ref',
        'source_key': 'sea_ref',
        'table_name': 'public.ref_retail_com',
        'date_column': 'crawl_strdatetime',
    },
    'ldy': {
        'product_key': 'ldy',
        'product_line': 'sea_ldy',
        'source_key': 'sea_ldy',
        'table_name': 'public.ldy_retail_com',
        'date_column': 'crawl_strdatetime',
    },
}


class SEALayer2DataEditTests(unittest.TestCase):
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
                get_editable_columns=lambda product_line, retailer: (
                    ['sku']
                    if product_line == 'sea_ldy' and retailer == 'Lowes'
                    else []
                ),
            ),
            'apps.common.inspection_dates': module_stub(
                'apps.common.inspection_dates',
                resolve_monitoring_date=lambda inspection, country, source_key: {
                    'inspection_date': str(inspection),
                    'source_date': '2026-08-30',
                    'offset_days': -1,
                    'country': country,
                    'source_key': source_key,
                },
            ),
            'apps.common.sea_retail': module_stub(
                'apps.common.sea_retail',
                SEA_RETAIL_SOURCES=SEA_SOURCES,
            ),
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
            'layer2_sea_data_edit_service_under_test',
            stubs,
        )

    def test_ldy_update_is_limited_to_d_minus_one_latest_main_anchor(self):
        cursor = ScriptedCursor([
            {'fetchone': (None, 'Lowes', 'item-1')},
            {},
            {},
        ])

        result = self.service.update_cell_value(
            cursor, Mock(), 'public.ldy_retail_com', 42, 'sku', 'SKU-1',
            date(2026, 8, 31), 'null', 'tester', 'fixed',
        )

        self.assertTrue(result['success'])
        scope_sql, scope_params = cursor.calls[0]
        self.assertIn('FROM public.ldy_retail_com source', scope_sql)
        self.assertIn("IN ('MAIN', 'BSR')", scope_sql)
        self.assertIn('ORDER BY anchor.id DESC', scope_sql)
        self.assertEqual(
            (42, '2026-08-30', '2026-08-30'), scope_params
        )
        self.assertIn(
            'UPDATE public.ldy_retail_com SET sku = %s',
            cursor.calls[1][0],
        )
        self.assertIn('INSERT INTO monitoring_corrections', cursor.calls[2][0])
        self.assertEqual('2026-08-31', str(cursor.calls[2][1][7]))

    def test_ref_and_ldy_are_allow_listed_but_unknown_tables_are_not(self):
        self.assertIn(
            'public.ref_retail_com', self.service.VALID_TABLES_UPDATE
        )
        self.assertIn(
            'public.ldy_retail_com', self.service.VALID_TABLES_UPDATE
        )
        self.assertNotIn(
            'public.ref_retail_com_backup', self.service.VALID_TABLES_UPDATE
        )


if __name__ == '__main__':
    unittest.main()
