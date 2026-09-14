import itertools
import unittest
from datetime import date
from unittest.mock import Mock, patch

from apps.common.sem_retail import (
    SEM_SOURCE_CONFIG, get_sem_editable_columns, get_sem_required_columns,
    normalize_sem_retailer,
)
from apps.dx.dx_layer2 import sem_validation as layer2
from apps.dx.dx_layer2.data_edit import services as edit2
from apps.dx.dx_layer2.format_validation import services as formats
from apps.dx.dx_layer2.null_validation import services as nulls
from apps.dx.dx_layer3.cross_field import sem_services as crossfield
from apps.dx.dx_layer3.data_edit import services as edit3
from tests.unit.support import ScriptedCursor


DAY = date(2026, 9, 11)
MAPPING = {'inspection_date': str(DAY), 'source_date': str(DAY), 'offset_days': 0}
TABLE = SEM_SOURCE_CONFIG['sem_ref']['table_name']


def record(**changes):
    return {
        'id': 1, 'batch_id': 'batch', 'country': 'SEM',
        'account_name': 'HomeDepot', 'item': '123', 'sku': 'TEST-1',
        'retailer_sku_name': 'Example',
        'product_url': 'https://www.homedepot.com.mx/p/example-123',
        'final_sku_price': '$7,350.00', 'original_sku_price': '$10,000.00',
        'savings': '-26%', 'star_rating': '4.5',
        'count_of_star_ratings': '2', 'count_of_reviews': '2',
        'ref_capacity': '90.39 L', 'ref_refrigerator_type': 'Top Mount',
        'ldy_capacity': '20 kg', 'ldy_loading_type': 'Front Load',
        'main_rank': '1', 'bsr_rank': '1',
        'crawl_datetime': '2026-09-11T04:45:29+00:00',
        'calendar_week': '2026-W37', **changes,
    }


def errors(**changes):
    return set(crossfield._failed_rules(record(**changes), 'HomeDepot', 'sem_ref'))


class HomeDepotRulesTests(unittest.TestCase):
    def test_scope_null_columns_and_retailer_edit_permissions(self):
        for product in ('sem_ref', 'sem_ldy'):
            self.assertEqual(('Liverpool', 'HomeDepot'), SEM_SOURCE_CONFIG[product]['retailers'])
            self.assertEqual('HomeDepot', normalize_sem_retailer(product, ' homedepot '))
            self.assertIn('sku', get_sem_required_columns(product))
            self.assertEqual(11, len(get_sem_required_columns(product)))
            self.assertNotIn('savings', get_sem_required_columns(product))
            self.assertIn('savings', get_sem_editable_columns(product, 'HomeDepot'))
            self.assertNotIn('savings', get_sem_editable_columns(product, 'Liverpool'))
        with self.assertRaises(ValueError):
            normalize_sem_retailer('sem_tv', 'HomeDepot')

    def test_formats_and_popup_share_the_homedepot_rules(self):
        for product in ('sem_ref', 'sem_ldy'):
            self.assertEqual([], layer2.evaluate_format(record(), product, 'HomeDepot'))
            details = formats.get_format_rules(None, product, 'HomeDepot')['rules']
            self.assertEqual(set(layer2._format_checks(product, 'HomeDepot')), {
                rule['field'] for rule in details
            })
            self.assertEqual('2026-W37', next(r['pattern'] for r in details if r['field'] == 'calendar_week'))
        self.assertEqual([], layer2.evaluate_format({}, 'sem_ref', 'HomeDepot'))
        for field, value in (
            ('calendar_week', 'W37'), ('calendar_week', '2026-W54'),
            ('product_url', 'https://www.liverpool.com.mx/tienda/pdp/example'),
            ('final_sku_price', '$10000.00'), ('original_sku_price', '$10.0'),
            ('savings', '26%'), ('savings', '-26.5%'), ('savings', '-101%'),
            ('star_rating', '5.1'), ('count_of_reviews', '-1'),
            ('main_rank', '0'), ('bsr_rank', '-1'),
            ('ref_refrigerator_type', 'Side-by-Side'),
        ):
            with self.subTest(field=field, value=value):
                self.assertIn(field, layer2.evaluate_format(record(**{field: value}), 'sem_ref', 'HomeDepot'))
        for value in ('-0%', '-100%'):
            self.assertNotIn('savings', layer2.evaluate_format(record(savings=value), 'sem_ref', 'HomeDepot'))

    def test_all_eight_presence_combinations(self):
        expected = {
            (False, False, False): set(),
            (False, False, True): {'final_missing'},
            (False, True, False): {'final_missing'},
            (False, True, True): {'final_missing'},
            (True, False, False): set(),
            (True, False, True): {'original_missing'},
            (True, True, False): {'savings_missing'},
            (True, True, True): set(),
        }
        for present in itertools.product((False, True), repeat=3):
            for blank in (None, '', '   '):
                values = dict(zip(
                    ('final_sku_price', 'original_sku_price', 'savings'),
                    (value if exists else blank for value, exists in zip(
                        ('$7,350.00', '$10,000.00', '-26%'), present,
                    )),
                ))
                with self.subTest(present=present, blank=blank):
                    self.assertEqual(expected[present], errors(**values))

    def test_discount_interval_includes_lower_boundary_only(self):
        for final, savings, expected in (
            ('$7,400.00', '-26%', set()),
            ('$7,350.00', '-26%', set()),
            ('$7,300.01', '-26%', set()),
            ('$7,300.00', '-26%', {'savings_rate_match'}),
            ('$7,400.01', '-26%', {'savings_rate_match'}),
            ('$7,350.00', '-27%', {'savings_rate_match'}),
            ('$0.00', '-100%', set()),
            ('$9,999.99', '-0%', set()),
        ):
            with self.subTest(final=final, savings=savings):
                self.assertEqual(expected, errors(final_sku_price=final, savings=savings))

    def test_prerequisites_do_not_cascade_into_discount_errors(self):
        for field in ('final_sku_price', 'original_sku_price', 'savings'):
            with self.subTest(field=field):
                self.assertEqual(set(), errors(**{field: 'invalid'}))
        self.assertEqual({'original_price_zero'}, errors(original_sku_price='$0.00'))
        self.assertEqual({'final_original_price'}, errors(final_sku_price='$10,000.00'))
        self.assertEqual({'final_original_price'}, errors(final_sku_price='$10,001.00'))
        self.assertEqual({'final_missing'}, errors(final_sku_price=None, savings='invalid'))

    def test_zero_consistency_compares_both_counts_and_no_page_rule(self):
        for rating, stars, reviews in (('0', '2', '2'), ('4.5', '0', '2'), ('4.5', '2', '0')):
            self.assertIn('rating_count_consistency', errors(
                star_rating=rating, count_of_star_ratings=stars, count_of_reviews=reviews,
            ))
        self.assertEqual(set(), errors(star_rating='0', count_of_star_ratings='0', count_of_reviews='0'))
        self.assertEqual({'rating_count_consistency'}, errors(count_of_reviews=None))
        self.assertEqual(set(), errors(page_type='MAIN', main_rank=None))
        self.assertEqual(set(), errors(star_rating='invalid'))

    def test_liverpool_still_ignores_savings(self):
        row = record(account_name='Liverpool', savings='invalid')
        self.assertEqual([], crossfield._failed_rules(row))
        with patch.object(crossfield, '_latest_rows', return_value=([], MAPPING)):
            summary = crossfield.get_sem_cross_field_summary(None, DAY, 'sem_tv')
        self.assertEqual(4, len(summary['rule_summary']))


class HomeDepotIntegrationTests(unittest.TestCase):
    def latest(self, _cursor, _date, source, retailer='Liverpool'):
        if source['source_key'] == 'sem_tv':
            return [], MAPPING
        row = record(id=2 if retailer == 'HomeDepot' else 1, account_name=retailer, sku=None)
        if retailer == 'Liverpool':
            row.update(calendar_week='W37', product_url='https://www.liverpool.com.mx/tienda/pdp/example',
                       ref_refrigerator_type='French Door', savings=None)
        return [row], MAPPING

    def test_null_and_format_summary_include_each_retailer_once(self):
        with patch.object(layer2, '_latest_rows', side_effect=self.latest), \
                patch.object(layer2, '_load_normal_reviews', return_value={}):
            null_result, format_result = {'tables': []}, {'tables': []}
            self.assertEqual(4, layer2.append_null_stats(None, DAY, null_result))
            self.assertEqual(0, layer2.append_format_stats(None, DAY, format_result))
        for table in null_result['tables'][1:]:
            self.assertEqual(2, table['total_records'])
            self.assertEqual(['Liverpool', 'HomeDepot'], [r['retailer'] for r in table['retailers']])
            self.assertEqual([1, 1], [r['fields_detail']['sku'] for r in table['retailers']])

    def test_detail_routes_keep_retailer_and_savings(self):
        with patch.object(layer2, '_latest_rows', return_value=([record(savings='invalid', sku=None)], MAPPING)) as latest, \
                patch.object(layer2, '_load_normal_reviews', return_value={}), \
                patch.object(layer2, '_history_rows', return_value=[]) as history:
            result = formats.get_format_detail(None, DAY, 'sem_ref_retail', 'HomeDepot', 3)
            self.assertEqual({'savings': 1}, result['field_counts'])
            self.assertIn('savings', result['column_names'])
            self.assertIn('savings', result['editable_cols'])
            self.assertEqual('HomeDepot', latest.call_args.kwargs['retailer'])
            self.assertEqual('HomeDepot', history.call_args.kwargs['retailer'])
            detail = nulls.get_null_detail(None, DAY, 'sem_ref_retail', 'HomeDepot', 1, 'sku')
            self.assertEqual('HomeDepot', detail['query_retailer'])

    def test_latest_and_history_sql_scope_same_batch_to_retailer(self):
        source = SEM_SOURCE_CONFIG['sem_ref']
        cursor = ScriptedCursor([{'description': [('id',)], 'fetchall': []}])
        layer2._latest_rows(cursor, DAY, source, retailer='HomeDepot')
        sql, params = cursor.calls[0]
        self.assertEqual((str(DAY), 'HomeDepot', str(DAY)), params)
        self.assertIn('LOWER(BTRIM(source.account_name)) = LOWER(BTRIM(latest_batch.account_name))', sql)
        cursor = ScriptedCursor([{'description': [('id',)], 'fetchall': []}])
        layer2._history_rows(cursor, source, DAY, DAY, ['123'], retailer='HomeDepot')
        sql, params = cursor.calls[0]
        self.assertEqual('HomeDepot', params[2])
        self.assertIn('LOWER(BTRIM(source.account_name)) = LOWER(BTRIM(latest.account_name))', sql)

    def test_crossfield_aggregate_and_history_keep_retailer_permissions(self):
        def latest(_cursor, _date, _source, retailer='Liverpool'):
            return [record(id=2 if retailer == 'HomeDepot' else 1,
                           account_name=retailer, original_sku_price='$0.00')], MAPPING
        with patch.object(crossfield, '_latest_rows', side_effect=latest), \
                patch.object(crossfield, '_history_rows', return_value=[]) as history:
            summary = crossfield.get_sem_cross_field_summary(None, DAY, 'sem_ref')
            detail = crossfield.get_sem_cross_field_rule_detail(
                None, DAY, 'sem_ref', 'sem_ref:original_price_zero', days=3,
            )
        self.assertEqual(8, len(summary['rule_summary']))
        self.assertEqual(2, summary['total_checked'])
        self.assertEqual(2, detail['total_anomalies'])
        self.assertEqual(1, detail['retailer_summary']['HomeDepot']['count'])
        self.assertEqual(1, detail['retailer_summary']['Liverpool']['count'])
        self.assertEqual(2, history.call_count)
        self.assertEqual('HomeDepot', history.call_args.kwargs['retailer'])
        self.assertNotIn('savings', detail['retailer_editable_columns']['Liverpool'])
        self.assertIn('savings', detail['retailer_editable_columns']['HomeDepot'])
        self.assertNotIn('rank_page_type', {r['rule_key'] for r in summary['rule_summary']})

    def test_homedepot_only_rules_expose_all_three_price_columns(self):
        def latest(_cursor, _date, _source, retailer='Liverpool'):
            return [record(account_name=retailer, savings=None)], MAPPING
        with patch.object(crossfield, '_latest_rows', side_effect=latest):
            result = crossfield.get_sem_cross_field_rule_detail(
                None, DAY, 'sem_ref', 'sem_ref:savings_missing',
            )
        self.assertEqual(1, result['total_anomalies'])
        self.assertEqual(0, result['retailer_summary']['Liverpool']['count'])
        self.assertEqual('HomeDepot', result['anomalies'][0]['account_name'])
        self.assertEqual('final_sku_price|original_sku_price|savings', result['select_fields'])

    def test_savings_edit_is_allowed_only_for_homedepot_in_both_layers(self):
        for module in (edit2, edit3):
            for retailer in ('Liverpool', 'HomeDepot'):
                row = ('-25%', retailer, '123', 'batch') if module is edit2 else ('-25%', 'batch', retailer, '123')
                cursor = ScriptedCursor([{'fetchone': row}, {}, {}])
                conn = Mock()
                args = (cursor, conn, TABLE, 2, 'savings', '-26%', DAY)
                if module is edit2:
                    result = module.update_cell_value(*args, 'format', 'tester', '')
                else:
                    result = module.update_cell_value(*args, 'cross_field', 'tester', '', None)
                with self.subTest(layer=module.__name__, retailer=retailer):
                    if retailer == 'Liverpool':
                        self.assertEqual(403, result['status'])
                        self.assertEqual(1, len(cursor.calls))
                        conn.commit.assert_not_called()
                    else:
                        self.assertTrue(result['success'])
                        self.assertIn('UPDATE', cursor.calls[1][0])
                        self.assertIn('LOWER(BTRIM(anchor.account_name)) = LOWER(BTRIM(source.account_name))', cursor.calls[0][0])
                        if module is edit3:
                            conn.commit.assert_called_once()
                        else:
                            # Layer 2 commits at its API transaction boundary.
                            self.assertIn('INSERT INTO monitoring_corrections', cursor.calls[2][0])

    def test_savings_format_review_uses_actual_retailer(self):
        for retailer in ('Liverpool', 'HomeDepot'):
            cursor = ScriptedCursor([{'fetchone': ('invalid', retailer, '123')}, {'fetchone': None}, {}])
            result = nulls.save_null_review(
                cursor, Mock(), TABLE, 2, 'savings', 'normal', '',
                '해당 값 정상 확인', DAY, 'format', 'tester',
            )
            if retailer == 'HomeDepot':
                self.assertTrue(result['success'])
                self.assertEqual('HomeDepot', cursor.calls[2][1][13])
            else:
                self.assertEqual(400, result['status_code'])
                self.assertEqual(1, len(cursor.calls))


if __name__ == '__main__':
    unittest.main()
