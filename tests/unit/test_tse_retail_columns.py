import unittest

from tests.unit.support import load_module, module_stub


class TseRetailColumnLoaderTests(unittest.TestCase):
    def test_separates_null_and_edit_only_columns(self):
        rows = [
            {
                'product_line': 'tse_tv',
                'column_name': 'final_sku_price',
                'retailer': 'homepro',
                'skip_missing_check': False,
                'is_editable': True,
            },
            {
                'product_line': 'tse_tv',
                'column_name': 'savings',
                'retailer': 'homepro',
                'skip_missing_check': True,
                'is_editable': True,
            },
            {
                'product_line': 'tse_ref',
                'column_name': 'ref_refrigerator_type',
                'retailer': 'homepro',
                'skip_missing_check': True,
                'is_editable': False,
            },
            {
                'product_line': 'tse_ldy',
                'column_name': 'ldy_loading_type',
                'retailer': 'homepro',
                'skip_missing_check': True,
                'is_editable': False,
            },
        ]
        module = load_module(
            'apps/common/retail_columns.py',
            'tse_retail_columns_under_test',
            stubs={
                'apps.common.db': module_stub(
                    'apps.common.db',
                    execute_dx_query=lambda *args, **kwargs: rows,
                    dx_table=lambda name: name,
                ),
                'apps.common.response': module_stub(
                    'apps.common.response',
                    log_error=lambda *args, **kwargs: None,
                ),
            },
        )

        loaded = module.load_tse_retail_columns()
        homepro = loaded['tse_tv']['Homepro']
        self.assertEqual(homepro['required_columns'], ['final_sku_price'])
        self.assertEqual(
            homepro['editable_columns'],
            ['final_sku_price', 'savings'],
        )
        self.assertEqual(
            loaded['tse_ref']['Homepro']['required_columns'], [],
        )
        self.assertEqual(
            loaded['tse_ref']['Homepro']['editable_columns'], [],
        )
        self.assertEqual(
            loaded['tse_ldy']['Homepro']['required_columns'], [],
        )
        self.assertEqual(
            loaded['tse_ldy']['Homepro']['editable_columns'], [],
        )


if __name__ == '__main__':
    unittest.main()
