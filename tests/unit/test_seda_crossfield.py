"""SEDA rule boundaries, disappearance evidence, counts and edit scope."""

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from apps.common.seda_retail import SEDA_SOURCE_CONFIG, get_seda_crossfield_editable_columns
from apps.dx.dx_layer3.cross_field import seda_rules as rules, seda_services as seda
from tests.unit import test_seda_recommendation_crossfield as fixtures

DAY, SOURCE, edits = fixtures.DAY, fixtures.SOURCE, fixtures.edits


def body(count):
    return ' ||| '.join(f'review{index} - body' for index in range(1, count + 1))


def row(**changes):
    value = dict(account_name='Magalu', page_type='MAIN', main_rank=1, bsr_rank=None,
                 original_sku_price='R$1.299,90', final_sku_price='R$1.199,90',
                 star_rating='4.5', count_of_reviews='5', count_of_star_ratings='5',
                 detailed_review_content=body(5), summarized_review_content='summary')
    value.update(changes)
    return value


class SedaRuleTests(unittest.TestCase):
    def test_each_review_or_price_field_expands_to_all_three(self):
        for group in rules.SEDA_DISPLAY_GROUPS:
            for field in group:
                self.assertEqual(group, rules.expand_display_fields((field,)))
        for spec in rules.SEDA_RULE_SPECS.values():
            for group in rules.SEDA_DISPLAY_GROUPS:
                if set(group) & set(spec['fields']):
                    self.assertTrue(set(group) <= set(spec['display_fields']))
        self.assertEqual(('page_type', 'main_rank'), rules.expand_display_fields(('page_type', 'main_rank')))

    def test_normal_rows_and_aliases(self):
        for retailer in ('Magalu', 'CasasBahia', ' Casas Bahia '):
            self.assertEqual({}, rules.evaluate_seda_row(row(account_name=retailer)))

    def test_page_rank_missing_and_both_allowed(self):
        for page, field in (('MAIN', 'main_rank'), ('BSR', 'bsr_rank')):
            self.assertIn('rank_page_type', rules.evaluate_seda_row(row(page_type=page, **{field: ' '})))
            self.assertNotIn('rank_page_type', rules.evaluate_seda_row(row(page_type=page, main_rank=1, bsr_rank=2)))

    def test_price_order_equal_and_brazilian_currency(self):
        self.assertIn('final_original_price', rules.evaluate_seda_row(row(final_sku_price='R$1.299,91')))
        self.assertNotIn('final_original_price', rules.evaluate_seda_row(row(final_sku_price='R$1.299,90')))
        self.assertEqual(rules.money('R$ 1234,50'), rules.money('R$1.234,50'))
        for value in (None, '', 'NULL', 'R$1,234.50', 'R$1.23,45', 'NaN', '-10'):
            self.assertIsNone(rules.money(value))
            self.assertNotIn('final_original_price', rules.evaluate_seda_row(row(original_sku_price=value)))

    def test_zero_body_is_anomaly_even_unparsed(self):
        for text in ('unstructured body', 'review1 - body'):
            found = rules.evaluate_seda_row(row(count_of_reviews='0', detailed_review_content=text))
            self.assertEqual('anomaly', found['review_zero_body'][0])
            self.assertNotIn('review_body_count', found)
            self.assertNotIn('review_body_over_count', found)

    def test_over_count_counts_distinct_review_numbers(self):
        found = rules.evaluate_seda_row(row(count_of_reviews='1', detailed_review_content=body(2)))
        self.assertEqual('anomaly', found['review_body_over_count'][0])
        self.assertNotIn('review_body_count', found)
        self.assertNotIn('review_body_over_count', rules.evaluate_seda_row(
            row(count_of_reviews='1', detailed_review_content='review1 - text ||| review1 - repeated')))

    def test_lowes_style_body_shortage_is_review_needed(self):
        cases = [dict(detailed_review_content=None),
                 dict(count_of_reviews='20', detailed_review_content=body(19)),
                 dict(detailed_review_content='unstructured body')]
        for changes in cases:
            self.assertEqual('review_needed', rules.evaluate_seda_row(row(**changes))['review_body_count'][0])
        for reviews, count in ((20, 20), (200, 20), (5, 4), (0, 0)):
            self.assertNotIn('review_body_count', rules.evaluate_seda_row(
                row(count_of_reviews=str(reviews), detailed_review_content=body(count))))

    def test_rating_zero_relationship_is_retailer_specific(self):
        for retailer in ('Magalu', 'Casas Bahia'):
            for rating, stars in (('0', '5'), ('4.5', '0')):
                self.assertIn('rating_count_presence', rules.evaluate_seda_row(
                    row(account_name=retailer, star_rating=rating, count_of_star_ratings=stars)))
        magalu = row(count_of_reviews='0', detailed_review_content=None)
        self.assertEqual({}, rules.evaluate_seda_row(magalu))
        self.assertIn('rating_count_presence', rules.evaluate_seda_row({**magalu, 'account_name': 'Casas Bahia'}))

    def test_positive_reviews_require_rating_and_rating_count(self):
        for field in ('star_rating', 'count_of_star_ratings'):
            for value in (None, '', ' ', '0'):
                self.assertIn('reviews_require_rating', rules.evaluate_seda_row(row(**{field: value})))
        for field in ('star_rating', 'count_of_star_ratings', 'count_of_reviews'):
            for value in ('NaN', '-1', 'garbled'):
                found = rules.evaluate_seda_row(row(**{field: value}))
                self.assertNotIn('rating_count_presence', found)
                self.assertNotIn('reviews_require_rating', found)

    def test_count_equality_only_casas_and_upper_bound_only_magalu(self):
        self.assertNotIn('review_gt_star_count', rules.evaluate_seda_row(row(count_of_star_ratings='10')))
        self.assertIn('review_gt_star_count', rules.evaluate_seda_row(row(count_of_star_ratings='4')))
        for stars in ('4', '10'):
            found = rules.evaluate_seda_row(row(account_name='Casas Bahia', count_of_star_ratings=stars))
            self.assertIn('review_count_match', found)
            self.assertNotIn('review_gt_star_count', found)

    def test_savings_excluded_and_recommendation_casas_only(self):
        self.assertEqual({}, rules.evaluate_seda_row(row(savings='Baixou 999%', recommendation_intent='bad')))
        self.assertNotIn('recommendation_intent', get_seda_crossfield_editable_columns('seda_tv', 'Magalu'))
        self.assertIn('recommendation_intent', get_seda_crossfield_editable_columns('seda_tv', 'CasasBahia'))
        self.assertNotIn('savings', get_seda_crossfield_editable_columns('seda_tv'))


class SedaCrossfieldIntegrationTests(unittest.TestCase):
    def setUp(self):
        fixtures.SedaRecommendationTests.setUp(self)
        self.db.execute('DELETE FROM monitoring_validation_rules')
        self.rule_ids = {}
        number = 1
        for product, source in SEDA_SOURCE_CONFIG.items():
            for key, spec in rules.SEDA_RULE_SPECS.items():
                self.rule_ids[(product, key)] = number
                for retailer in spec['retailers']:
                    self.db.execute('INSERT INTO monitoring_validation_rules VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                                    (number, product + '_' + key, 'crossfield', True,
                                     source['section_code'], source['table_name'], retailer, number))
                    number += 1

    def add(self, product='seda_tv', **changes):
        fixtures.SedaRecommendationTests.add(self, product, **row(**changes))

    def detail(self, key, days=3, product='seda_tv'):
        return seda.get_seda_cross_field_rule_detail(self.cursor, DAY, product,
                                                     self.rule_ids[(product, key)], days)

    def test_disappearance_requires_previous_both_and_current_body(self):
        for product in SEDA_SOURCE_CONFIG:
            self.add(product, id=1, crawl_strdatetime='2026-09-19 10:00:00')
            self.add(product, id=2, summarized_review_content=None)
            detail = self.detail('summary_review_disappeared', product=product)
            self.assertEqual((0, 1), (detail['total_anomalies'], detail['total_review_needed']))
            self.assertEqual([(1, 'comparison_history'), (2, 'target')],
                             [(entry['id'], entry['row_role']) for entry in detail['anomalies']])
            self.assertEqual('2026-09-19', detail['anomalies'][1]['previous_source_date'])

    def test_does_not_compare_different_retailer_or_item_or_old_dates(self):
        for index, changes in enumerate((
                dict(account_name='Casas Bahia'), dict(item='other'),
                dict(crawl_strdatetime='2026-09-14 10:00:00'))):
            values = {'crawl_strdatetime': '2026-09-19 10:00:00', **changes}
            self.add(id=index+1, **values)
        self.add(id=4, summarized_review_content=None)
        self.assertEqual(0, self.detail('summary_review_disappeared')['total_findings'])

    def test_nearest_record_wins_not_older_nonempty_summary(self):
        self.add(id=1, crawl_strdatetime='2026-09-18 10:00:00')
        self.add(id=2, crawl_strdatetime='2026-09-19 10:00:00', summarized_review_content=None)
        self.add(id=3, summarized_review_content=None)
        self.assertEqual(0, self.detail('summary_review_disappeared')['total_findings'])
        self.db.execute(f"UPDATE {SOURCE['table_name']} SET summarized_review_content='summary', detailed_review_content=NULL WHERE id=2")
        self.assertEqual(0, self.detail('summary_review_disappeared')['total_findings'])

    def test_current_missing_body_is_not_summary_disappearance(self):
        self.add(id=1, crawl_strdatetime='2026-09-19 10:00:00')
        self.add(id=2, summarized_review_content=None, detailed_review_content=None)
        self.assertEqual(0, self.detail('summary_review_disappeared')['total_findings'])

    def test_evidence_outside_display_window_stays_readonly(self):
        self.add(id=1, crawl_strdatetime='2026-09-15 10:00:00')
        self.add(id=2, summarized_review_content=' ')
        detail = self.detail('summary_review_disappeared', days=1)
        self.assertEqual(['comparison_history', 'target'], [entry['row_role'] for entry in detail['anomalies']])
        self.assertIn('source.id = ANY', detail['queries']['Magalu'])
        edits._select_seda_record(self.cursor, SOURCE['table_name'], ('summarized_review_content',), 1, DAY)
        self.assertIsNone(self.cursor.fetchone())
        edits._select_seda_record(self.cursor, SOURCE['table_name'], ('summarized_review_content',), 2, DAY)
        self.assertIsNotNone(self.cursor.fetchone())

    def test_summary_separates_errors_reviews_and_deduplicates_records(self):
        self.add(id=1, item='zero', count_of_reviews='0')
        self.add(id=2, item='short', account_name='Casas Bahia', count_of_reviews='25', count_of_star_ratings='25', detailed_review_content=body(19))
        self.add(id=3, item='summary', summarized_review_content=None)
        self.add(id=4, item='both', account_name='Casas Bahia', final_sku_price='R$1.300,00', detailed_review_content=None)
        self.add(id=5, item='summary', crawl_strdatetime='2026-09-19 10:00:00')
        result = seda.get_seda_cross_field_summary(self.cursor, DAY, 'seda_tv')
        self.assertEqual((4, 2, 2, 0), (result['total_checked'], result['failed_records'], result['review_needed_records'], result['passed_records']))
        self.assertEqual((2, 3), (result['total_anomalies'], result['total_review_needed']))
        self.assertEqual(11, len(result['rule_summary']))
        self.assertEqual(['Casas Bahia'], next(rule for rule in result['rule_summary'] if rule['rule_key'] == 'review_count_match')['retailers'])

    def test_normal_confirmation_for_one_rule_does_not_hide_other_rule(self):
        self.add(id=1, count_of_reviews='0', final_sku_price='R$1.300,00')
        rule_id = self.rule_ids[('seda_tv', 'review_zero_body')]
        self.db.execute('INSERT INTO monitoring_corrections VALUES (?,3,?,?,?, ?,?,?, ?,?,?,?)',
                        (1, 'cross_field', 'normal', SOURCE['table_name'], str(DAY), rule_id,
                         'detailed_review_content', 'checked', 'reason', 'user', 'now'))
        self.assertEqual(0, self.detail('review_zero_body')['total_findings'])
        self.assertEqual(1, self.detail('final_original_price')['total_anomalies'])

    def test_page_absence_exclusion_precedes_all_rules(self):
        self.add(id=1, count_of_reviews='0')
        with patch.object(seda, 'exclude_page_absent_records', return_value=([], [{'record_id': 1}])):
            result = seda.get_seda_cross_field_summary(self.cursor, DAY, 'seda_tv')
        self.assertEqual((0, 0), (result['total_checked'], result['total_anomalies']))
        self.assertEqual([{'record_id': 1}], result['page_exclusions'])

    def test_latest_prior_main_batch_and_case_normalization(self):
        self.add(id=1, account_name='CasasBahia', batch_id='old', crawl_strdatetime='2026-09-19 10:00:00')
        self.add(id=2, account_name=' Casas Bahia ', batch_id='new', crawl_strdatetime='2026-09-19 11:00:00', summarized_review_content=None)
        self.add(id=3, account_name='CasasBahia', summarized_review_content=None)
        self.assertEqual(0, self.detail('summary_review_disappeared')['total_findings'])

    def test_missing_item_still_has_target_and_query_id_fallback(self):
        self.add(id=1, item=None, count_of_reviews='0')
        detail = self.detail('review_zero_body')
        self.assertEqual(1, detail['total_anomalies'])
        self.assertEqual([], detail['retailer_summary']['Magalu']['items'])
        sql, params = seda._select_sql(SOURCE, '2026-09-20', '2026-09-20', [], 'Magalu', target_ids=[1])
        self.cursor.execute(sql, params)
        self.assertEqual([1], [record[0] for record in self.cursor.fetchall()])

    def test_magalu_summary_edit_and_confirmation_use_current_scope(self):
        for operation in ('edit', 'confirm'):
            cursor, conn = Mock(), Mock()
            if operation == 'edit':
                cursor.fetchone.return_value = (None, 'current', 'Magalu', 'sku-1')
                result = edits.update_cell_value(cursor, conn, SOURCE['table_name'], 2,
                                                 'summarized_review_content', 'summary', DAY,
                                                 'cross_field', 'tester', '', rule_id=19)
            else:
                cursor.fetchone.side_effect = [(None, 'Magalu', 'sku-1'), None]
                result = edits.save_review(cursor, conn, SOURCE['table_name'], 2,
                                           'summarized_review_content', 'normal', '', 'checked',
                                           DAY, 'cross_field', 'tester', rule_id=19)
            self.assertTrue(result['success'])
            conn.commit.assert_called_once()
            sql, params = cursor.execute.call_args_list[0].args
            self.assertIn('FOR UPDATE OF source', sql)
            self.assertIn('magalu', params)
            self.assertIn('2026-09-20', params)

    def test_registration_contains_all_57_scopes_and_no_discount_rule(self):
        script = Path('sql/setup_seda_crossfield.sql').read_text(encoding='utf-8')
        for product in SEDA_SOURCE_CONFIG:
            for key, spec in rules.SEDA_RULE_SPECS.items():
                self.assertEqual(len(spec['retailers']), script.count("'" + product + '_' + key + "'"))
        self.assertNotIn("'savings'", script)

    def test_grouped_fields_in_detail_and_display_sql(self):
        self.add(id=1, account_name='Casas Bahia', count_of_star_ratings='6',
                 final_sku_price='R$1.500,00', savings='Baixou 10%')
        for key, group in (('review_count_match', rules.SEDA_DISPLAY_GROUPS[0]),
                           ('final_original_price', rules.SEDA_DISPLAY_GROUPS[1])):
            detail = self.detail(key)
            self.assertTrue(set(group) <= set(detail['select_fields'].split('|')))
            target = next(entry for entry in detail['anomalies'] if entry['row_role'] == 'target')
            self.assertTrue(set(group) <= target.keys())
            for field in group:
                self.assertIn('source.' + field, detail['queries']['Casas Bahia'])
        self.assertEqual('Baixou 10%', target['savings'])

    def test_registration_is_repeatable_and_preserves_recommendation_id(self):
        self.db.execute('DELETE FROM monitoring_validation_rules')
        self.db.execute('INSERT INTO monitoring_validation_rules VALUES (900, ?, ?, TRUE, ?, ?, ?, 110)',
                        ('seda_tv_recommendation_intent', 'crossfield', 'seda_tv_retail', SOURCE['table_name'], 'CasasBahia'))
        for column in ('section_name', 'detail_name', 'date_column', 'product_line', 'field1', 'field2',
                       'validation_type', 'check_type', 'error_message', 'display_columns', 'select_fields',
                       'query', 'query_detail', 'created_at', 'created_id'):
            self.db.execute(f'ALTER TABLE monitoring_validation_rules ADD COLUMN {column} TEXT')
        script = Path('sql/setup_seda_crossfield.sql').read_text(encoding='utf-8')
        script = (script.replace('public.monitoring_validation_rules', 'monitoring_validation_rules')
                  .replace('ON COMMIT DROP', '').replace('NOW()', 'CURRENT_TIMESTAMP')
                  .replace('COMMIT;', 'DROP TABLE _seda_crossfield_seed; COMMIT;'))
        self.db.executescript(script)
        first = self.db.execute('SELECT id, detail_code, retailer FROM monitoring_validation_rules ORDER BY id').fetchall()
        self.assertEqual(57, len(first))
        self.assertIn((900, 'seda_tv_recommendation_intent', 'Casas Bahia'), first)
        self.db.executescript(script)
        second = self.db.execute('SELECT id, detail_code, retailer FROM monitoring_validation_rules ORDER BY id').fetchall()
        self.assertEqual(first, second)


if __name__ == '__main__':
    unittest.main()
