import itertools
import unittest
from datetime import date, datetime
from unittest.mock import patch

from apps.common.sem_retail import (
    SEM_COPPEL_EXCLUDED_COLUMNS, SEM_LAYER1_RETAILERS, SEM_SOURCE_CONFIG,
    get_sem_required_columns, normalize_sem_retailer,
)
from apps.dx.dx_layer1.sem_retail import sem_retail_services as layer1
from apps.dx.dx_layer2 import sem_validation as layer2
from apps.dx.dx_layer3.cross_field import sem_services as crossfield
from tests.unit.support import ScriptedCursor


DAY = date(2026, 9, 28)
MAPPING = {'inspection_date': str(DAY), 'source_date': str(DAY), 'offset_days': 0}


def record(**changes):
    return {
        'id': 1, 'batch_id': 'c20260928_000002', 'country': 'SEM',
        'account_name': 'Coppel', 'item': '123', 'sku': 'TEST-1',
        'retailer_sku_name': 'Example',
        'product_url': 'https://www.coppel.com/pdp/example-pm-123',
        'final_sku_price': '$10,499', 'original_sku_price': '$18,699',
        'savings': '$8,200 (43%)', 'star_rating': None,
        'count_of_star_ratings': None, 'count_of_reviews': None,
        'ref_capacity': '250 L', 'ref_refrigerator_type': 'Top Mount',
        'ldy_capacity': '22 kg', 'ldy_loading_type': 'Top Load',
        'main_rank': '1', 'bsr_rank': '1',
        'crawl_datetime': '2026-09-28T00:00:02+00:00', 'calendar_week': 'W40',
        **changes,
    }


def errors(**changes):
    return set(crossfield._failed_rules(record(**changes), 'Coppel', 'sem_ref'))


class CoppelRulesTests(unittest.TestCase):
    def test_scope_and_required_columns_preserve_existing_retailers(self):
        for product in ('sem_ref', 'sem_ldy'):
            self.assertEqual(('Liverpool', 'HomeDepot', 'Coppel'), SEM_LAYER1_RETAILERS[product])
            self.assertEqual('Coppel', normalize_sem_retailer(product, ' coppel '))
            self.assertEqual(8, len(get_sem_required_columns(product, 'Coppel')))
            self.assertEqual(
                set(get_sem_required_columns(product)) - set(SEM_COPPEL_EXCLUDED_COLUMNS),
                set(get_sem_required_columns(product, 'Coppel')),
            )
            for retailer in ('Liverpool', 'HomeDepot'):
                self.assertEqual(11, len(get_sem_required_columns(product, retailer)))
        with self.assertRaises(ValueError):
            normalize_sem_retailer('sem_tv', 'Coppel')

    def test_format_rules_accept_coppel_csv_shapes_and_exclude_review_fields(self):
        for product in ('sem_ref', 'sem_ldy'):
            self.assertEqual([], layer2.evaluate_format(record(), product, 'Coppel'))
            details = layer2.get_format_rule_details(product, 'Coppel')
            self.assertEqual(set(layer2._format_checks(product, 'Coppel')),
                             {r['field'] for r in details})
            for correction in ('null_check', 'format_check'):
                self.assertTrue(set(SEM_COPPEL_EXCLUDED_COLUMNS).isdisjoint(
                    layer2.get_review_allowed_columns(product, correction, 'Coppel')))
        for field, value in (
            ('final_sku_price', '$10,499.00'), ('savings', '$8,200.00 (43%)'),
            ('savings', '$0 (0%)'), ('savings', '$100 (100%)'),
        ):
            self.assertEqual([], layer2.evaluate_format(record(**{field: value}), 'sem_ref', 'Coppel'))
        for field, value in (
            ('product_url', 'https://www.liverpool.com.mx/tienda/pdp/example'),
            ('final_sku_price', '$10499'), ('savings', '-43%'),
            ('savings', '$8,200 (43.5%)'), ('savings', '$8,200 (101%)'),
        ):
            self.assertIn(field, layer2.evaluate_format(record(**{field: value}), 'sem_ref', 'Coppel'))

    def test_all_eight_price_presence_combinations(self):
        expected = {
            (False, False, False): set(),
            (False, False, True): {'coppel_final_missing'},
            (False, True, False): {'coppel_final_missing'},
            (False, True, True): {'coppel_final_missing'},
            (True, False, False): set(),
            (True, False, True): {'coppel_original_missing'},
            (True, True, False): {'coppel_savings_missing'},
            (True, True, True): set(),
        }
        for present in itertools.product((False, True), repeat=3):
            for blank in (None, '', ' '):
                changes = {field: record()[field] if exists else blank
                           for field, exists in zip(
                               ('final_sku_price', 'original_sku_price', 'savings'), present)}
                with self.subTest(present=present, blank=blank):
                    self.assertEqual(expected[present], errors(**changes))

    def test_discount_amount_and_rate_are_independent(self):
        self.assertEqual(set(), errors())
        self.assertEqual({'coppel_savings_amount_match'}, errors(savings='$8,201 (43%)'))
        self.assertEqual({'coppel_savings_rate_match'}, errors(savings='$8,200 (44%)'))
        self.assertEqual({'coppel_savings_amount_match', 'coppel_savings_rate_match'},
                         errors(savings='$8,201 (44%)'))

    def test_discount_percent_uses_exact_floor_boundaries(self):
        for final, savings, expected in (
            ('$70.00', '$30.00 (30%)', set()),
            ('$69.01', '$30.99 (30%)', set()),
            ('$69.00', '$31.00 (30%)', {'coppel_savings_rate_match'}),
            ('$70.01', '$29.99 (30%)', {'coppel_savings_rate_match'}),
            ('$0', '$100 (100%)', set()),
        ):
            with self.subTest(final=final):
                self.assertEqual(expected, errors(final_sku_price=final,
                                                 original_sku_price='$100', savings=savings))

    def test_invalid_formats_do_not_generate_discount_comparison_errors(self):
        for field in ('final_sku_price', 'original_sku_price', 'savings'):
            self.assertEqual(set(), errors(**{field: 'invalid'}))
        self.assertEqual({'original_price_zero'}, errors(original_sku_price='$0'))
        self.assertEqual({'final_original_price'}, errors(original_sku_price='$10,499'))
        self.assertEqual({'final_original_price'}, errors(original_sku_price='$10,000'))
        self.assertEqual(set(), errors(star_rating='5', count_of_star_ratings='1', count_of_reviews='0'))


class CoppelIntegrationTests(unittest.TestCase):
    def latest(self, _cursor, _date, _source, retailer='Liverpool'):
        return ([record(sku=None)] if retailer == 'Coppel' else []), MAPPING

    def test_null_summary_detail_history_and_auto_review_use_eight_fields(self):
        def review(_cursor, _date, _rows, fields, _reviews, **kwargs):
            if kwargs['retailer'] == 'Coppel':
                self.assertTrue(set(SEM_COPPEL_EXCLUDED_COLUMNS).isdisjoint(fields))
            return {}, {}, []

        with patch.object(layer2, '_latest_rows', side_effect=self.latest), \
                patch.object(layer2, '_load_normal_reviews', return_value={}), \
                patch.object(layer2, 'review_state', side_effect=review), \
                patch.object(layer2, '_history_rows', return_value=[record(sku=None)]) as history:
            result = {'tables': []}
            self.assertEqual(2, layer2.append_null_stats(None, DAY, result))
            for table in result['tables'][1:]:
                coppel = next(r for r in table['retailers'] if r['retailer'] == 'Coppel')
                self.assertEqual(8, len(coppel['fields_detail']))
                self.assertEqual(1, coppel['total_null_count'])
            detail = layer2.null_detail(None, DAY, 'sem_ref', 'sku', 3, 'Coppel')
            self.assertEqual(['sku'], detail['results'][0]['null_fields'])
            self.assertEqual('Coppel', history.call_args.kwargs['retailer'])
            for field in SEM_COPPEL_EXCLUDED_COLUMNS:
                self.assertEqual([], layer2.null_detail(None, DAY, 'sem_ref', field, retailer='Coppel')['results'])

    def test_crossfield_summary_queries_and_detail_keep_rule_scope(self):
        def latest(_cursor, _date, _source, retailer='Liverpool'):
            return ([record(savings='$8,201 (43%)')] if retailer == 'Coppel' else []), MAPPING

        with patch.object(crossfield, '_latest_rows', side_effect=latest), \
                patch.object(crossfield, 'exclude_page_absent_records', side_effect=lambda c, d, r, **k: (r, [])), \
                patch.object(crossfield, '_history_rows', return_value=[]) as history:
            summary = crossfield.get_sem_cross_field_summary(None, DAY, 'sem_ref')
            detail = crossfield.get_sem_cross_field_rule_detail(
                None, DAY, 'sem_ref', 'sem_ref:coppel_savings_amount_match', 3)
            review = crossfield.get_sem_cross_field_rule_detail(
                None, DAY, 'sem_ref', 'sem_ref:rating_count_consistency')
        self.assertEqual(1, summary['total_checked'])
        self.assertEqual(1, summary['failed_records'])
        self.assertEqual(1, summary['total_anomalies'])
        for rule in summary['rule_summary']:
            if rule['rule_key'].startswith('coppel_'):
                self.assertEqual(['Coppel'], rule['retailers'])
                self.assertIn("account_name = 'Coppel'", rule['query'])
                self.assertNotIn('HomeDepot', rule['query'])
            elif rule['rule_key'] in ('rating_count_consistency', 'review_rating_count'):
                self.assertNotIn('Coppel', rule['retailers'])
                self.assertNotIn('Coppel', rule['query'])
        self.assertNotIn('Coppel', review['retailer_summary'])
        self.assertEqual(1, detail['total_anomalies'])
        self.assertEqual({'Coppel'}, set(detail['retailer_summary']))
        self.assertEqual('final_sku_price|original_sku_price|savings', detail['select_fields'])
        self.assertIn('savings', detail['retailer_editable_columns']['Coppel'])
        self.assertEqual('Coppel', history.call_args.kwargs['retailer'])

    def test_layer1_keeps_coppel_counts_separate_and_uses_main_count(self):
        def counts(_cursor, product, retailer, _date):
            main, raw, bsr = (85, 94, 94) if product == 'sem_ldy' else (274, 274, 100)
            return {'retailer': retailer, 'batch_id': 'batch', 'main_count': main,
                    'actual_count': raw, 'bsr_count': bsr} if retailer == 'Coppel' else None

        with patch.object(layer1.repo, 'get_latest_batch_counts', side_effect=counts), \
                patch.object(layer1.repo, 'get_previous_main_counts', return_value=[]):
            result = layer1.get_layer1_stats(None, DAY, datetime(2026, 9, 28, 12))
        self.assertEqual(359, result['check']['actual'])
        ldy = next(c for c in result['check']['categories'] if c['product_line'] == 'sem_ldy')
        coppel = next(r for r in ldy['retailers'] if r['retailer'] == 'Coppel')
        self.assertEqual((85, 94, 94, 'OK'),
                         (coppel['main_count'], coppel['raw_count'], coppel['bsr_count'], coppel['status']))

    def test_latest_batch_query_is_scoped_to_coppel(self):
        cursor = ScriptedCursor([{'description': [('id',)], 'fetchall': []}])
        layer2._latest_rows(cursor, DAY, SEM_SOURCE_CONFIG['sem_ref'], 'Coppel')
        self.assertEqual((str(DAY), 'Coppel', str(DAY)), cursor.calls[0][1])
        self.assertIn('source.batch_id IS NOT DISTINCT FROM latest_batch.batch_id', cursor.calls[0][0])
