import unittest
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from tests.unit.support import load_module, module_stub, package_stub


class RecordingCursor:
    def __init__(self, *, one=(0,), rows=()):
        self.one = one
        self.rows = list(rows)
        self.calls = []

    def execute(self, query, params):
        self.calls.append((query, params))

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.rows


class RedirectDataRepositoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repository = load_module(
            'apps/dx/dx_data/redirect_data/redirect_data_repositories.py',
            'redirect_data_repository_under_test',
            {},
        )

    def test_siel_query_uses_kst_date_and_allow_listed_table(self):
        source = {
            'table_name': 'dx_siel.dx_siel_ref_retail_com',
            'date_mode': 'timestamp_kst',
        }
        cursor = RecordingCursor(one=(3,))

        count = self.repository.get_redirect_count_db(
            cursor, source, date(2026, 8, 31),
        )

        self.assertEqual(3, count)
        sql, params = cursor.calls[0]
        self.assertIn('FROM dx_siel.dx_siel_ref_retail_com source', sql)
        self.assertIn("AT TIME ZONE 'Asia/Seoul'", sql)
        self.assertIn('source.redirect IS TRUE', sql)
        self.assertEqual(['2026-08-31', '2026-08-31'], params)

    def test_sea_query_preserves_batch_date_scope(self):
        source = {
            'table_name': 'public.tv_retail_com',
            'date_mode': 'batch',
        }
        cursor = RecordingCursor(rows=[(1, 'SEA')])

        rows = self.repository.get_redirect_page_db(
            cursor, source, ['id', 'country'], date(2026, 7, 30), 20, 0,
        )

        self.assertEqual([{'id': 1, 'country': 'SEA'}], rows)
        sql, params = cursor.calls[0]
        self.assertIn('FROM public.tv_retail_com source', sql)
        self.assertIn("from '([0-9]{8})'", sql)
        self.assertEqual(['20260730', 20, 0], params)

    def test_unknown_table_fails_closed(self):
        with self.assertRaises(ValueError):
            self.repository.get_redirect_count_db(
                RecordingCursor(),
                {'table_name': 'public.unsafe', 'date_mode': 'batch'},
                date(2026, 8, 31),
            )


class RedirectDataServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cursor = object()
        cls.repository_calls = []

        @contextmanager
        def connection():
            yield object(), cls.cursor

        def get_count(cursor, source, target_date):
            cls.repository_calls.append(('count', source, target_date))
            return 2

        def get_page(cursor, source, columns, target_date, page_size, offset):
            cls.repository_calls.append((
                'page', source, columns, target_date, page_size, offset,
            ))
            return [dict.fromkeys(columns, 'value')]

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
            'apps.common.sea_retail': module_stub(
                'apps.common.sea_retail',
                SEA_RETAIL_SOURCES={
                    'tv': {'table_name': 'public.tv_retail_com'},
                },
            ),
            'apps.common.siel_retail': module_stub(
                'apps.common.siel_retail',
                SIEL_SOURCE_CONFIG={
                    'siel_tv': {
                        'category': 'TV',
                        'table_name': 'dx_siel.dx_siel_tv_retail_com',
                    },
                    'siel_ref': {
                        'category': 'REF',
                        'table_name': 'dx_siel.dx_siel_ref_retail_com',
                    },
                    'siel_ldy': {
                        'category': 'LDY',
                        'table_name': 'dx_siel.dx_siel_ldy_retail_com',
                    },
                },
            ),
            'apps.dx': package_stub('apps.dx'),
            'apps.dx.dx_data': package_stub('apps.dx.dx_data'),
            'apps.dx.dx_data.redirect_data': package_stub(
                'apps.dx.dx_data.redirect_data'
            ),
            'apps.dx.dx_data.redirect_data.redirect_data_repositories': module_stub(
                'apps.dx.dx_data.redirect_data.redirect_data_repositories',
                get_redirect_count_db=get_count,
                get_redirect_page_db=get_page,
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
                'id', 'country', 'product', 'batch_id', 'crawl_datetime',
                'account_name', 'page_type', 'item', 'sku',
                'retailer_sku_name', 'product_url', 'redirect',
            ],
            columns,
        )

    def test_list_uses_batch_date_and_is_read_only(self):
        result = self.service.get_amazon_redirect_list(
            date(2026, 7, 30), page=1, page_size=20,
        )

        self.assertEqual(2, result['total'])
        self.assertEqual('2026-07-30', result['date'])
        self.assertEqual('SEA', result['country'])
        self.assertEqual('TV', result['product'])
        self.assertEqual(1, len(result['items']))

    def test_siel_country_and_product_select_an_allow_listed_source(self):
        self.repository_calls.clear()

        result = self.service.get_amazon_redirect_list(
            date(2026, 8, 31), page=2, page_size=20,
            country='siel', product='ref',
        )

        self.assertEqual('SIEL', result['country'])
        self.assertEqual('REF', result['product'])
        self.assertIn('country', result['columns'])
        self.assertIn('final_sku_price', result['columns'])
        count_call = self.repository_calls[0]
        self.assertEqual('dx_siel.dx_siel_ref_retail_com', count_call[1]['table_name'])
        self.assertEqual('timestamp_kst', count_call[1]['date_mode'])
        page_call = self.repository_calls[1]
        self.assertEqual(20, page_call[-1])

    def test_unknown_country_product_scope_fails_closed(self):
        with self.assertRaises(ValueError):
            self.service.get_redirect_source('SEA', 'REF')

    def test_page_exposes_country_and_product_controls(self):
        root = Path(__file__).resolve().parents[2]
        template = (
            root / 'apps/dx/dx_data/templates/dx_data/redirect_data.html'
        ).read_text(encoding='utf-8')
        script = (
            root / 'apps/dx/dx_data/static/dx_data/js/redirect_data.js'
        ).read_text(encoding='utf-8')

        self.assertIn('id="redirectCountry"', template)
        self.assertIn('<option value="SIEL">SIEL</option>', template)
        self.assertIn('id="redirectProduct"', template)
        self.assertIn("SIEL: ['TV', 'REF', 'LDY']", script)
        self.assertIn('country: scope.country', script)
        self.assertIn('product: scope.product', script)


if __name__ == '__main__':
    unittest.main()
