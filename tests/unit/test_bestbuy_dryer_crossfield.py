import unittest
from contextlib import contextmanager
from datetime import date
from unittest.mock import Mock, patch

from django.test import override_settings
from django.core.management.base import CommandError
from apps.common import bestbuy_dryer_crossfield as policy
from apps.dx.dx_layer1.management.commands import setup_bestbuy_dryer_crossfield as setup
from tests.unit.support import ScriptedCursor
from tests.unit.test_layer3_sea_crossfield import sea_services as service, _rule
from tests.unit.test_layer3_sea_data_edit import services as edits, FakeConnection

KEY = 'sea_ldy_dryer'
TABLE = 'public.ldy_dryer_retail'
DAY = date(2026, 10, 13)
FIELDS = ('star_rating', 'count_of_star_ratings', 'count_of_reviews',
          'final_sku_price', 'original_sku_price', 'savings')


def row(**updates):
    value = dict(id=1, account_name='Bestbuy', country='SEA', item='JJ8VPZ6896',
                 sku='DLE6100W', retailer_sku_name='Dryer', product_url='https://www.bestbuy.com/product/dryer/JJ8VPZ6896',
                 crawl_datetime='2026-10-12 19:07:00', batch_id='b_20261012_190628',
                 count_of_reviews='2', count_of_star_ratings='2', star_rating='4.5',
                 final_sku_price='$700', original_sku_price='$900', savings='$200')
    value.update(updates)
    return value


def rules(retailer='Bestbuy', offset=0):
    result = []
    for index, key in enumerate(policy.RULES, offset + 1):
        value = _rule(index, key, retailer, KEY)
        value.update(table_name=TABLE, section_code=KEY + '_retail', date_column='crawl_datetime')
        result.append(value)
    return result


class BestbuyDryerCrossfieldTests(unittest.TestCase):
    def setUp(self):
        exclusion = patch.object(service, 'exclude_page_absent_records', side_effect=lambda cur, day, rows, **kw: (rows, []))
        exclusion.start()
        self.addCleanup(exclusion.stop)

    def test_all_seven_relationships(self):
        self.assertEqual(set(), service.evaluate_sea_row(row(), KEY))
        cases = {
            'review_count_match': dict(count_of_reviews='3'),
            'rating_count_presence': dict(star_rating='Not yet reviewed'),
            'final_original_price': dict(final_sku_price='$901'),
            'savings_missing': dict(savings=None),
            'original_missing': dict(original_sku_price=None),
            'final_missing': dict(final_sku_price=None),
            'savings_amount_match': dict(savings='$199.99'),
        }
        for expected, updates in cases.items():
            self.assertIn(expected, service.evaluate_sea_row(row(**updates), KEY))

    def test_zero_reviews_and_equal_prices_are_normal(self):
        for rating in ('Not yet reviewed', '0', '0.0'):
            self.assertFalse(policy.evaluate(row(star_rating=rating, count_of_reviews='0', count_of_star_ratings='0')))
        for savings in (None, '', '$0', '$0.00'):
            self.assertFalse(policy.evaluate(row(original_sku_price='$700', savings=savings)))
        self.assertEqual({'savings_amount_match'}, policy.evaluate(row(original_sku_price='$700', savings='$1')))
        self.assertFalse(policy.evaluate(row(original_sku_price=None, savings=None)))
        self.assertFalse(policy.evaluate(row(original_sku_price=None, savings='$0')))
        self.assertIn('rating_count_presence', policy.evaluate(row(count_of_reviews='0', count_of_star_ratings='0')))
        self.assertIn('rating_count_presence', policy.evaluate(row(star_rating='Not yet reviewed', count_of_reviews='0')))

    def test_decimal_precision_and_malformed_values(self):
        self.assertFalse(policy.evaluate(row(final_sku_price='$899.99', original_sku_price='$1,149.99', savings='$250')))
        self.assertIn('savings_amount_match', policy.evaluate(row(final_sku_price='$899.99', original_sku_price='$1,149.99', savings='$249.99')))
        self.assertFalse(policy.evaluate(row(count_of_reviews='1,692', count_of_star_ratings='1692')))
        for updates in (dict(star_rating='6'), dict(star_rating='bad'), dict(count_of_reviews='bad'),
                        dict(final_sku_price='$abc'), dict(final_sku_price='$70,0'), dict(savings='$abc'),
                        dict(final_sku_price='$1.001'), dict(savings='-$200')):
            self.assertFalse(policy.evaluate(row(**updates)), updates)

    def test_other_bestbuy_products_and_costco_keep_old_rules(self):
        self.assertIn('review_body_count', service.evaluate_sea_row(row(), 'sea_ldy'))
        self.assertIn('final_original_price', service.evaluate_sea_row(row(account_name='Costco', original_sku_price='$700', savings='$0'), KEY))
        self.assertNotIn('discount_rate_90', policy.evaluate(row(final_sku_price='$1', original_sku_price='$100', savings='$99')))

    def test_rule_ids_and_scope_are_separate_for_costco(self):
        configured = rules() + rules('Costco', 10) + rules('Lowes', 20) + rules('ALL', 30)
        configured.append(dict(rules()[0], rule_id=99, validation_type='review_body_count', detail_code='review_body_count'))
        cur = ScriptedCursor([{'fetchall': configured}])
        loaded = service.load_active_sea_rules(cur, KEY)
        self.assertEqual(14, len(loaded))
        for rule in loaded:
            self.assertEqual(1, len(rule['_retailers']))
            self.assertEqual(1, len(rule['_source_rule_ids']))
            self.assertTrue(set(FIELDS) <= set(rule['select_fields'].split('|')))
            self.assertNotIn('page_type', rule['select_fields'])
            self.assertNotIn('detailed_review_content', rule['select_fields'])
        cur = ScriptedCursor([{'fetchall': []}])
        service.load_latest_sea_rows(cur, DAY, KEY)
        sql, params = cur.calls[0]
        self.assertEqual(('2026-10-12', '2026-10-12'), params)
        self.assertIn('DISTINCT ON (LOWER(TRIM(account_name))', sql)
        self.assertIn('LOWER(TRIM(source.account_name)) = latest.retailer_key', sql)
        self.assertIn('2026-10-12', sql)
        self.assertIn('2026-10-09', sql)
        self.assertNotIn('page_type', sql)

    def test_summary_detail_history_and_normal_confirmation(self):
        current = row(savings='$100')
        costco = row(id=2, account_name='Costco', crawl_datetime='2026-10-12T04:00:00+00:00')
        configured = rules() + rules('Costco', 10)
        def cursor(rows, corrections=()):
            return ScriptedCursor([{'fetchall': configured}, {'fetchall': rows}, {'fetchall': corrections}])
        summary = service.get_sea_cross_field_summary(cursor([current, costco]), DAY, KEY)
        self.assertEqual(['Bestbuy', 'Costco'], [r['retailer'] for r in summary['retailers']])
        self.assertEqual(1, summary['total_anomalies'])
        self.assertEqual(policy.RULES['final_original_price'], next(r for r in summary['rule_summary']
            if r['validation_type'] == 'final_original_price' and r['retailers'] == ['Bestbuy'])['guide_description'])
        prior = row(id=3, crawl_datetime='2026-10-11 19:07:00', batch_id='prior')
        detail = service.get_sea_cross_field_rule_detail(cursor([current, costco, prior]), DAY, KEY, 7, 3)
        self.assertTrue(detail['found'])
        self.assertEqual(1, detail['total_anomalies'])
        self.assertEqual(set(FIELDS), set(detail['editable_columns']))
        # Confirming a Costco rule must not clear a Bestbuy finding.
        wrong = dict(record_id=1, column_name='savings', rule_id=17, memo='checked')
        result = service.get_sea_cross_field_summary(cursor([current, costco], [wrong]), DAY, KEY)
        self.assertEqual(1, result['total_anomalies'])
        result = service.get_sea_cross_field_summary(cursor([current, costco], [dict(wrong, rule_id=7)]), DAY, KEY)
        self.assertEqual(0, result['total_anomalies'])

    def test_edit_and_review_preserve_latest_retailer_batch_and_audit(self):
        for field in FIELDS:
            cur = ScriptedCursor([{'fetchone': ('1', 'batch', 'Bestbuy', 'JJ8VPZ6896')}, {}, {}])
            result = edits.update_cell_value(cur, FakeConnection(), TABLE, 1, field, '2', str(DAY), 'cross_field', 'tester', 'verified', rule_id=7)
            self.assertTrue(result.get('success'), result)
            sql = cur.calls[0][0]
            self.assertNotIn('page_type', sql)
            self.assertIn('LOWER(TRIM(anchor.account_name)) = LOWER(TRIM(source.account_name))', sql)
            self.assertIn('INSERT INTO monitoring_corrections', cur.calls[-1][0])
        cur = ScriptedCursor([{'fetchone': ('$100', 'Bestbuy', 'JJ8VPZ6896')}, {'fetchone': None}, {}])
        result = edits.save_review(cur, FakeConnection(), TABLE, 1, 'savings', 'normal', 'verified', 'checked', str(DAY), 'cross_field', 'tester', rule_id=7)
        self.assertTrue(result.get('success'), result)

    @override_settings(DEBUG=True)
    def test_registration_is_transactional_and_targets_only_bestbuy_dryer(self):
        sql = setup.registration_sql()
        self.assertIn('public.test_monitoring_validation_rules', sql)
        self.assertNotIn('BEGIN;', sql)
        self.assertNotIn('COMMIT;', sql)
        self.assertNotIn('UPDATE public.ldy_dryer_retail', sql)
        self.assertNotIn("= 'costco'", sql)
        self.assertNotIn('monitoring_format_rules', sql)
        conn, cur = Mock(), Mock()
        @contextmanager
        def connection():
            yield conn, cur
        with patch.object(setup, 'dx_connection', connection):
            cur.fetchall.return_value = [('sea_ldy_dryer_retail', 7)]
            setup.Command().handle()
            conn.commit.assert_called_once()
            conn.reset_mock()
            cur.fetchall.return_value = [('sea_ldy_dryer_retail', 6)]
            with self.assertRaises(CommandError):
                setup.Command().handle()
            conn.commit.assert_not_called()
