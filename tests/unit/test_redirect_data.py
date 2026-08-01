import unittest
from contextlib import contextmanager
from datetime import date

from tests.unit.support import load_module, module_stub, package_stub


class RedirectDataServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cursor = object()

        @contextmanager
        def connection():
            yield object(), cls.cursor

        stubs = {
            'apps': package_stub('apps'),
            'apps.common': package_stub('apps.common'),
            'apps.common.db': module_stub(
                'apps.common.db', dx_connection=connection,
            ),
            'apps.common.retail_columns': module_stub(
                'apps.common.retail_columns',
                get_retailer_columns=lambda *_: [
                    'item', 'redirect', 'product_url', 'bad-column',
                ],
            ),
            'apps.dx': package_stub('apps.dx'),
            'apps.dx.dx_data': package_stub('apps.dx.dx_data'),
            'apps.dx.dx_data.redirect_data': package_stub(
                'apps.dx.dx_data.redirect_data'
            ),
            'apps.dx.dx_data.redirect_data.redirect_data_repositories': module_stub(
                'apps.dx.dx_data.redirect_data.redirect_data_repositories',
                get_redirect_count_db=lambda cursor, batch_date: 2,
                get_redirect_page_db=lambda cursor, columns, batch_date, page_size, offset: [
                    dict.fromkeys(columns, 'value')
                ],
            ),
        }
        cls.service = load_module(
            'apps/dx/dx_data/redirect_data/redirect_data_services.py',
            'apps.dx.dx_data.redirect_data.redirect_data_services',
            stubs,
        )

    def test_columns_are_base_plus_safe_active_amazon_columns(self):
        columns = self.service.get_amazon_redirect_columns()

        self.assertEqual(
            [
                'id', 'batch_id', 'crawl_datetime', 'account_name', 'redirect',
                'item', 'product_url',
            ],
            columns,
        )

    def test_list_uses_batch_date_and_is_read_only(self):
        result = self.service.get_amazon_redirect_list(
            date(2026, 7, 30), page=1, page_size=20,
        )

        self.assertEqual(2, result['total'])
        self.assertEqual('2026-07-30', result['date'])
        self.assertEqual(1, len(result['items']))


if __name__ == '__main__':
    unittest.main()
