import unittest

from tests.unit.support import ScriptedCursor
from tests.unit.test_layer4_email_report_data import load_registry, load_service


class SEAHomeDepotReportTests(unittest.TestCase):
    def test_collection_report_keeps_sea_product_and_d_minus_one(self):
        sources = {s['key']: s for s in load_registry().EMAIL_REPORT_SOURCES}
        for product, count in (('ref', 300), ('ldy', 265)):
            with self.subTest(product=product):
                source = sources[f'sea_{product}']
                retailer = next(r for r in source['retailers'] if r['name'] == 'HomeDepot')
                cursor = ScriptedCursor([
                    {'fetchall': [('item', 'HomeDepot', False),
                                  (f'{product}_capacity', 'HomeDepot', False)]},
                    {'fetchone': ('h20260918_015939',)},
                    {'fetchone': (count, count, 0, count, 1, count, 100)},
                ])
                service = load_service(cursor)
                result = service._query_source(
                    {**source, 'retailers': (retailer,)}, '2026-09-21')
                self.assertEqual('SEA', result['country'])
                self.assertEqual(product.upper(), result['product'])
                self.assertEqual('2026-09-20', result['source_date'])
                self.assertEqual('HomeDepot', result['retailers'][0]['retailer'])
                self.assertEqual(count, result['total_count'])
                self.assertEqual(count, result['main_count'])
                self.assertEqual(100, result['bsr_count'])
                for sql, params in cursor.calls[1:]:
                    self.assertIn("AT TIME ZONE 'America/New_York'", sql)
                    self.assertIn('2026-09-20', params)
                    self.assertNotIn('page_type', sql)
                    self.assertIn(source['table_name'], sql)
                self.assertTrue(source['has_page_type'])
                self.assertEqual('text', source['date_mode'])

        self.assertNotIn('HomeDepot', [r['name'] for r in sources['sea_tv']['retailers']])
        self.assertTrue(sources['sem_ref']['table_name'].startswith('dx_sem.'))

    def test_existing_sea_retailers_keep_main_anchor_and_text_date(self):
        source = next(s for s in load_registry().EMAIL_REPORT_SOURCES if s['key'] == 'sea_ref')
        retailer = {**source['retailers'][0], 'columns': ('item',)}
        cursor = ScriptedCursor([{'fetchone': ('b1',)}, {'fetchone': (2, 2, 0, 2, 1)}])
        load_service(cursor)._query_retailer(cursor, source, retailer, '2026-09-20')
        self.assertIn("= 'main'", cursor.calls[0][0])
        self.assertIn('LEFT(BTRIM(CAST(source.crawl_strdatetime AS TEXT)), 10)', cursor.calls[0][0])
        self.assertNotIn('America/New_York', cursor.calls[0][0])


if __name__ == '__main__':
    unittest.main()
