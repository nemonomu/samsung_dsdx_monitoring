"""Bestbuy and Costco dryer formats use their observed source shapes and raw days."""
import re
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from apps.common.source_dates import source_date_value
from tests.unit.support import ScriptedCursor, load_module
from tests.unit.test_layer2_sea_format_duplicate import common_stubs


SQL = (Path(__file__).resolve().parents[2] / 'sql/setup_bestbuy_costco_dryer_format.sql').read_text(encoding='utf-8')


def pattern(name):
    match = re.search(r"\('" + re.escape(name) + r"', 'regex', \$re\$(.*?)\$re\$", SQL)
    if not match:
        raise AssertionError(f'missing SQL pattern: {name}')
    return re.compile(match.group(1))


class BestbuyCostcoDryerFormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = load_module(
            'apps/dx/dx_layer2/format_validation/services.py',
            'bestbuy_costco_dryer_format_test', common_stubs(),
        )

    def test_retailers_share_section_but_use_distinct_fields(self):
        source = self.service.SEA_RETAIL_SOURCES['ldy_dryer']
        self.assertEqual(('Bestbuy', 'Costco', 'HomeDepot', 'Lowes'), source['retailers'])
        self.assertEqual('public.ldy_dryer_retail', source['table_name'])
        for retailer in ('Bestbuy', 'Costco'):
            fields = self.service._get_sea_format_fields('ldy_dryer', retailer)
            self.assertEqual(14, len(fields))
            self.assertIn('crawl_datetime', fields)
            self.assertIn('loading_type', fields)
            self.assertNotIn('page_type', fields)
            self.assertNotIn('product', fields)

    def test_observed_shapes_and_malformed_values(self):
        samples = {
            'SEA_DRYER_BESTBUY_ITEM': ('J3KHVG3GZ6', 'J3K-HVG3GZ6'),
            'SEA_DRYER_COSTCO_ITEM': ('4201041292', 'A201041292'),
            'SEA_DRYER_BESTBUY_URL': ('https://www.bestbuy.com/product/dryer/J3KHVG3GZ6', 'https://www.costco.com/p/dryer'),
            'SEA_DRYER_COSTCO_URL': ('https://www.costco.com/p/-/dryer/4201041292', 'https://www.bestbuy.com/product/dryer'),
            'SEA_DRYER_BESTBUY_TIME': ('2026-10-18 18:37:16', '2026-10-18T18:37:16'),
            'SEA_DRYER_COSTCO_TIME': ('2026-10-18T00:17:30-04:00', '2026-10-18 00:17:30'),
            'SEA_DRYER_BESTBUY_WEEK': ('w42', '2026-W42'),
            'SEA_DRYER_COSTCO_WEEK': ('2026-W42', 'w42'),
            'SEA_DRYER_USD': ('$1,049.99', '$1,04.99'),
            'SEA_DRYER_COUNT': ('1,024', '-1'),
            'SEA_DRYER_BESTBUY_RATING': ('Not yet reviewed', '5.1'),
            'SEA_DRYER_BESTBUY_CAPACITY': ('2.3Cu.Ft.', '2.3 L'),
            'SEA_DRYER_COSTCO_CAPACITY': ('5.3 cu ft.', '5.3 L'),
        }
        for name, (valid, invalid) in samples.items():
            with self.subTest(name=name):
                self.assertTrue(pattern(name).fullmatch(valid))
                self.assertFalse(pattern(name).fullmatch(invalid))
        self.assertEqual('2026-10-18', source_date_value('2026-10-18T23:17:30-04:00'))

    def test_detail_and_query_use_raw_source_day_and_latest_batch(self):
        source = self.service.SEA_RETAIL_SOURCES['ldy_dryer']
        cursor = ScriptedCursor([{'fetchall': []}])
        self.service._fetch_sea_format_rows(cursor, date(2026, 10, 18),
                                            date(2026, 10, 18), source, 'Costco')
        query, params = cursor.calls[0]
        self.assertIn('source.batch_id IS NOT DISTINCT FROM latest.batch_id', query)
        self.assertIn('LEFT(BTRIM(CAST(source.crawl_datetime AS TEXT)), 10)', query)
        self.assertNotIn('AT TIME ZONE', query)
        self.assertEqual(('2026-10-18', '2026-10-18', 'Costco') * 2, params)
        row = {'id': 42, 'batch_id': 'c1', 'country': 'SEA', 'account_name': 'Costco',
               'item': '4201041292', 'crawl_datetime': '2026-10-18T23:17:30-04:00'}
        with patch.object(self.service, '_fetch_sea_format_rows', return_value=[row]), patch.object(
                self.service, '_load_sea_format_normal_reviews', return_value={}):
            detail = self.service._get_sea_format_detail(
                Mock(), '2026-10-19', 'sea_ldy_dryer_retail', 'Costco', 1, True)
        self.assertEqual('2026-10-18', detail['source_date'])
        self.assertEqual('2026-10-18', detail['results'][0]['_source_date'])
        self.assertNotIn('crawl_datetime', detail['editable_cols'])
        self.assertIn('capacity', detail['editable_cols'])


if __name__ == '__main__':
    unittest.main()
