import json
import sqlite3
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

from apps.common.seda_retail import SEDA_SOURCE_CONFIG
from apps.dx.dx_layer2 import seda_format_rules as rules, seda_format_validation as seda
from apps.dx.dx_layer2.format_validation import services, api
from apps.dx.dx_layer2.data_edit import services as edits
from apps.dx.dx_layer2.null_validation import services as reviews
from tests.unit.test_seda_layer2_null import MemoryCursor
from tests.unit.support import ScriptedCursor

DAY = date(2026, 9, 21)


class SedaFormatRulesTests(unittest.TestCase):
    def test_numeric_metadata_and_url_rules(self):
        pairs = {
            'account_name': ('Magalu', 'Wrong'), 'country': ('SEDA', 'SEA'),
            'product': ('TV', 'REF'), 'calendar_week': ('w53', 'w54'),
            'page_type': ('main', 'detail'), 'sku_status': ('Sponsored', 'New'),
            'original_sku_price': ('R$ 2.199,00', 'R$2,199.00'),
            'final_sku_price': ('R$9,99', '-R$9,99'), 'star_rating': ('5.0', '5.1'),
            'count_of_reviews': ('0', '3.5'), 'count_of_star_ratings': ('2300', '-1'),
            'main_rank': ('1', '0'), 'bsr_rank': ('120', '-1'),
            'screen_size': ('15.4 Polegadas', 'Not tv'),
            'product_url': ('https://www.magazineluiza.com.br/tv/p/123', 'https://magazineluiza.com.br.bad.example/tv'),
        }
        for field, (valid, invalid) in pairs.items():
            for value in (valid, invalid, '', None, ' '):
                with self.subTest(field=field, value=value):
                    self.assertEqual(value == invalid, field in rules.evaluate({field: value}, 'seda_tv', 'Magalu'))
        self.assertNotIn('savings', rules.columns('seda_tv'))
        self.assertNotIn('recommendation_intent', rules.columns('seda_tv'))
        self.assertNotIn('screen_size', rules.columns('seda_ref'))

    def test_coupon_delivery_pickup_and_review_structure(self):
        for retailer, valid, invalid in (
            ('Magalu', {'discount_type': 'Coupon R$ 150 off', 'delivery_availability': 'Receive by Friday, December 04', 'pick_up_availability': 'Pick up in store starting tomorrow'},
             {'discount_type': 'Coupon R$ 0 off', 'delivery_availability': 'Receive by Monday, February 31', 'pick_up_availability': 'Fast pickup in 2h'}),
            ('CasasBahia', {'discount_type': 'USE O CUPOM DESCONTO 17%', 'delivery_availability': 'Normal by Tuesday, January 05', 'pick_up_availability': 'Fast pickup in 2h'},
             {'discount_type': 'USE O CUPOM DESCONTO 101%', 'delivery_availability': 'Normal by someday', 'pick_up_availability': 'Pick up soon'}),
        ):
            self.assertEqual({}, rules.evaluate(valid, 'seda_tv', retailer))
            self.assertEqual(set(invalid), set(rules.evaluate(invalid, 'seda_tv', retailer)))
        for value in rules.CASAS_UNAVAILABLE:
            self.assertTrue(rules.valid_delivery(value, 'casasbahia'))
        for value in ('Receive today', 'Receive tomorrow', 'Receive within 2 business days', 'Receive within 1 business day'):
            self.assertTrue(rules.valid_delivery(value, 'magalu'))
        self.assertTrue(rules.valid_review_body('review1 - Muito bom! 👍 ||| review2 - texto\ncontinua'))
        for value in ('text', 'review2 - text', 'review1 - ', 'review1 - text ||| review3 - text', 'review1 - text review2 - text'):
            self.assertFalse(rules.valid_review_body(value), value)


class SedaFormatScopeTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.create_function('BTRIM', 1, lambda value: value.strip() if value is not None else None)
        self.db.execute("ATTACH DATABASE ':memory:' AS dx_seda")
        for product, source in SEDA_SOURCE_CONFIG.items():
            columns = ', '.join(f'{col} {"INTEGER PRIMARY KEY" if col == "id" else "TEXT"}' for col in seda.select_columns(product))
            self.db.execute(f"CREATE TABLE {source['table_name']} ({columns})")
        self.db.execute('''CREATE TABLE monitoring_corrections (record_id INTEGER, column_name TEXT, memo TEXT,
            created_id TEXT, created_at TEXT, reason TEXT, table_name TEXT, crawl_date TEXT, correction_type TEXT, status TEXT)''')
        self.cursor = MemoryCursor(self.db)
        execute = self.cursor.execute
        self.cursor.execute = lambda sql, params=(): execute(
            sql.replace('LEFT(BTRIM(anchor.crawl_strdatetime), 10)', 'SUBSTR(BTRIM(anchor.crawl_strdatetime), 1, 10)')
               .replace('LEFT(BTRIM(source.crawl_strdatetime), 10)', 'SUBSTR(BTRIM(source.crawl_strdatetime), 1, 10)'), params)

    def add(self, product_line='seda_tv', **changes):
        row = dict.fromkeys(seda.select_columns(product_line))
        row.update(account_name='Magalu', item='001', page_type='main', batch_id='batch', crawl_strdatetime='2026-09-20 20:00:00', star_rating='9')
        row.update(changes)
        self.db.execute(f"INSERT INTO {SEDA_SOURCE_CONFIG[product_line]['table_name']} ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})", list(row.values()))

    def test_latest_batch_day_history_groups_and_normal_review(self):
        self.add(id=1, batch_id='older')
        self.add(id=2, crawl_strdatetime='2026-09-19 12:00:00')
        self.add(id=3)
        self.add(id=4, page_type='bsr')
        self.add(id=5, page_type='bsr', batch_id='bsr-only')
        self.add(id=6, crawl_strdatetime='2026-09-21 12:00:00')
        self.add(id=7, item=None)
        detail = services.get_format_detail(self.cursor, DAY, 'seda_tv_retail', 'Magalu', 3)
        self.assertEqual({'star_rating': 3}, detail['field_counts'])
        self.assertEqual({2, 3, 4, 7}, {row['id'] for row in detail['results']})
        self.assertEqual('2026-09-20', detail['editable_date'])
        self.assertEqual(list(rules.DISPLAY_GROUPS[0]), detail['field_display_columns']['star_rating'])
        for key in rules.DISPLAY_GROUPS[0]:
            self.assertIn('source.' + key, detail['field_queries']['star_rating'])
        self.assertIn("'2026-09-20'", detail['field_queries']['star_rating'])
        self.assertIn('source.id IN', detail['field_queries']['star_rating'])
        self.db.execute("INSERT INTO monitoring_corrections (record_id,column_name,table_name,crawl_date,correction_type,status) VALUES (3,'star_rating',?,'2026-09-21','format_check','normal')", (SEDA_SOURCE_CONFIG['seda_tv']['table_name'],))
        detail = seda.format_detail(self.cursor, DAY, 'seda_tv', 'Magalu', 1)
        self.assertEqual(2, detail['total_format_count'])
        validation = {'tables': []}
        self.assertEqual(2, seda.append_format_stats(self.cursor, DAY, validation, 'seda_tv_retail'))
        self.assertEqual(3, validation['tables'][0]['total_checked'])

    def test_bad_metadata_is_not_filtered_out_or_assigned_to_shared_batches(self):
        self.add(id=1, star_rating='5')
        self.add(id=2, page_type='wrong', country='SEA', product='LDY', star_rating='5')
        self.add(id=3, account_name='Wrong', star_rating='5')
        detail = seda.format_detail(self.cursor, DAY, 'seda_tv', 'Magalu', 1)
        self.assertEqual({'page_type': 1, 'country': 1, 'product': 1, 'account_name': 1}, detail['field_counts'])
        selected = seda.select_record(self.cursor, DAY, 'seda_tv', 3, 'account_name', for_edit=True)
        self.assertEqual(('Wrong', 'Magalu', '001', 'batch'), selected)
        self.add(id=4, account_name='CasasBahia', star_rating='5')
        detail = seda.format_detail(self.cursor, DAY, 'seda_tv', 'Magalu', 1)
        self.assertNotIn('account_name', detail['field_counts'])
        self.assertIsNone(seda.select_record(self.cursor, DAY, 'seda_tv', 3, 'account_name'))

    def test_null_batch_selector_scope_and_edit_allowlist(self):
        self.add(id=1, page_type='bsr', batch_id=None)
        self.assertIsNone(seda.select_record(self.cursor, DAY, 'seda_tv', 1, 'star_rating'))
        self.add(id=2, batch_id=None)
        self.assertIsNotNone(seda.select_record(self.cursor, DAY, 'seda_tv', 1, 'star_rating'))
        self.add(id=3, crawl_strdatetime='2026-09-19 12:00:00')
        self.assertIsNone(seda.select_record(self.cursor, DAY, 'seda_tv', 3, 'star_rating'))
        with self.assertRaises(ValueError):
            seda.select_record(self.cursor, DAY, 'seda_tv', 1, 'savings')

    def test_edit_and_normal_confirmation_routes_are_enabled_for_format_only(self):
        table = SEDA_SOURCE_CONFIG['seda_tv']['table_name']
        cursor = ScriptedCursor([{'fetchone': ('9', 'magalu', '001', 'batch')}, {'rowcount': 1}, {'rowcount': 1}])
        result = edits.update_cell_value(cursor, Mock(), table, 1, 'star_rating', '4.8', str(DAY), 'format', 'tester', '')
        self.assertTrue(result['success'])
        self.assertIn('FOR UPDATE OF source', cursor.calls[0][0])
        self.assertEqual('format_check', cursor.calls[2][1][1])
        cursor = ScriptedCursor([{'fetchone': ('9', 'magalu', '001', 'batch')}, {'fetchone': None}, {'rowcount': 1}])
        result = reviews.save_null_review(cursor, Mock(), table, 1, 'star_rating', 'normal', '', 'confirmed', str(DAY), 'format', 'tester')
        self.assertTrue(result['success'])
        self.assertEqual('format_check', cursor.calls[-1][1][1])
        for field in ('savings', 'recommendation_intent', 'sku'):
            cursor = ScriptedCursor([])
            result = edits.update_cell_value(cursor, Mock(), table, 1, field, 'X', str(DAY), 'format', 'tester', '')
            self.assertEqual(403, result['status'])
            self.assertFalse(cursor.calls)

    def test_all_three_products_have_stats_rule_and_api_routes(self):
        for product, source in SEDA_SOURCE_CONFIG.items():
            self.add(product, id=1)
            self.assertIn(source['section_code'], services.VALID_TABLES_FORMAT)
            self.assertIn(product, services.VALID_TABLES_RULES)
            self.assertIn(source['section_code'], api.RETAIL_DEFAULT_HISTORY_TABLES)
            self.assertEqual(set(rules.columns(product)), {rule['field'] for rule in services.get_format_rules(self.cursor, product, 'Magalu')['rules']})
        validation = {'tables': []}
        self.assertEqual(3, seda.append_format_stats(self.cursor, DAY, validation))
        self.assertEqual(3, len(validation['tables']))


if __name__ == '__main__':
    unittest.main()
