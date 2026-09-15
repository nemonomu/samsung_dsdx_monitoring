"""History contract regression tests; no external database is used."""
import unittest
import ast
from datetime import date
from pathlib import Path

from apps.common.crossfield_history import build_detail_history
from tests.unit.support import ScriptedCursor, load_module, module_stub
from tests.unit import test_layer3_sea_crossfield as sea
from tests.unit import test_layer3_siel_crossfield as siel
from tests.unit import test_layer3_tse_crossfield as tse
from tests.unit import test_layer3_seg_crossfield as seg


class CrossfieldHistoryTests(unittest.TestCase):
    def test_generic_sea_d1_keeps_findings_when_history_lookup_misses_them(self):
        for source_timestamp in ('2026-09-12 08:00:00', ' 2026-09-12 08:00:00 ', None):
            for include_current in (False, True):
                for reviewed in (False, True):
                    with self.subTest(timestamp=source_timestamp, current=include_current,
                                      reviewed=reviewed):
                        finding = dict(id=43, account_name='Bestbuy', item='example',
                                       crawl_datetime=source_timestamp, value='100')
                        rule = dict(rule_id=43, detail_code='price_combination', field1='value',
                                    validation_type='price', error_message='bad value',
                                    select_fields='value', error_details=[finding])
                        validated_dates = []

                        def validate(source_date, section, **kwargs):
                            validated_dates.append(source_date)
                            return dict(rule_results=[rule], table_name='tv_retail_com',
                                        date_col='crawl_datetime')

                        service = load_module('apps/dx/dx_layer3/cross_field/services.py',
                            'generic_d1_history_under_test', {
                                'apps.common.retail_columns': module_stub('apps.common.retail_columns',
                                    get_editable_columns=lambda *_: ['value'],
                                    get_retailer_columns=lambda *_: ['value']),
                                'apps.dx.dx_layer3.dashboard.services': module_stub(
                                    'apps.dx.dx_layer3.dashboard.services',
                                    validate_crossfield=validate,
                                    validate_review_detail_match=lambda *_: {},
                                    get_crossfield_normal_counts=lambda *_: {},
                                    get_all_no_review_texts=lambda *_: '',
                                    load_crossfield_rules=lambda *_: []),
                            })
                        cols = ['id', 'account_name', 'item', 'page_type',
                                'crawl_datetime', 'value', 'product_url']
                        rows = [(i, 'Bestbuy', 'example', 'MAIN', f'2026-09-{i:02d}',
                                 'normal', '') for i in (10, 11)]
                        if include_current:
                            rows.append((43, 'Bestbuy', 'example', 'MAIN',
                                         source_timestamp or '2026-09-12', '100', ''))
                        # Another current-day row must not become an anomaly by item alone.
                        rows.append((44, 'Bestbuy', 'example', 'MAIN', '2026-09-12', 'normal', ''))
                        reviews = [(43, 'value', '', '', None, None)] if reviewed else []
                        cursor = ScriptedCursor([
                            {'description': [(col,) for col in cols], 'fetchall': rows},
                            {'fetchall': reviews},
                        ])
                        result = service.get_cross_field_rule_detail(
                            cursor, date(2026, 9, 12), 'tv', 'sea_tv', 43, 3,
                            inspection_date=date(2026, 9, 13))
                        self.assertEqual([date(2026, 9, 12)], validated_dates)
                        self.assertEqual('2026-09-13', result['inspection_date'])
                        self.assertEqual('2026-09-12', result['source_date'])
                        self.assertEqual(['10', '11', '43'], [r['id'] for r in result['anomalies']])
                        self.assertEqual(['comparison_history', 'comparison_history', 'target'],
                                         [r['row_role'] for r in result['anomalies']])
                        self.assertEqual('2026-09-12', result['anomalies'][-1]['row_source_date'])
                        self.assertEqual(0 if reviewed else 1, result['total_anomalies'])
                        self.assertEqual('2026-09-13', cursor.calls[-1][1][0])

    def test_generic_route_supports_new_retailer_and_rules_without_date(self):
        for days in (3, 4):
            for include_id in (False, True):
                finding = dict(account_name='New retailer', item='same')
                if include_id:
                    finding['id'] = 13
                rule = dict(rule_id=1, detail_code='new_price', field1='value', field2=None,
                            validation_type='price', error_message='bad value',
                            select_fields='value', error_details=[finding])
                service = load_module('apps/dx/dx_layer3/cross_field/services.py',
                    'generic_history_under_test', {
                        'apps.common.retail_columns': module_stub('apps.common.retail_columns',
                            get_editable_columns=lambda *_: ['value'],
                            get_retailer_columns=lambda *_: ['value']),
                        'apps.dx.dx_layer3.dashboard.services': module_stub(
                            'apps.dx.dx_layer3.dashboard.services',
                            validate_crossfield=lambda *_, **kwargs: dict(rule_results=[rule],
                                table_name='tv_retail_com', date_col='crawl_datetime'),
                            validate_review_detail_match=lambda *_: {},
                            get_crossfield_normal_counts=lambda *_: {},
                            get_all_no_review_texts=lambda *_: '',
                            load_crossfield_rules=lambda *_: []),
                    })
                cols = ['id', 'account_name', 'item', 'page_type', 'crawl_datetime', 'value', 'product_url']
                rows = [(i, 'New retailer', 'same', 'MAIN', f'2026-09-{i:02d}', 'value', '')
                        for i in range(14-days, 14)]
                cursor = ScriptedCursor([
                    {'description': [(col,) for col in cols], 'fetchall': rows},
                    {'fetchall': [(rows[0][0], 'value', '', '', None, 'accepted history')]},
                ])
                result = service.get_cross_field_rule_detail(
                    cursor, date(2026,9,13), 'new_tv', 'new_retail', 1, days)
                self.assertEqual(days, len(result['anomalies']))
                self.assertEqual(1, result['total_anomalies'])
                self.assertEqual('target', result['anomalies'][-1]['row_role'])

    def test_every_source_adapter_uses_shared_history_contract(self):
        adapters = []
        folder = Path(__file__).resolve().parents[2] / 'apps/dx/dx_layer3/cross_field'
        for path in folder.glob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for function in tree.body:
                if isinstance(function, ast.FunctionDef) and function.name.endswith('cross_field_rule_detail'):
                    adapters.append(path.name)
                    calls = [node.func.id for node in ast.walk(function)
                             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
                    self.assertIn('build_detail_history', calls, path.name)
        self.assertGreaterEqual(len(adapters), 6)

    def test_future_country_and_retailer_need_no_history_allowlist(self):
        for days in (1, 3, 4):
            rows = [dict(id=i, country='NEW', account_name='New retailer',
                         item='same', collected=f'2026-09-{i:02d}', value=1,
                         normal_review=True) for i in range(8, 14)]
            target = dict(rows[-1], value=None)
            rows += [dict(rows[2], id=101, account_name='Other retailer'),
                     dict(rows[2], id=102, item='other'),
                     dict(rows[-1], id=103),
                     dict(rows[-1], id=104, collected='2026-09-14')]
            result = build_detail_history(rows, [target], '2026-09-13', 'collected', days)
            self.assertEqual(list(range(14-days, 14)), [r['id'] for r in result])
            self.assertEqual(['comparison_history']*(days-1)+['target'],
                             [r['row_role'] for r in result])
            self.assertEqual(1, sum(r['row_role']=='target' for r in result))
            self.assertTrue(all(r['normal_review'] for r in result))
            self.assertEqual([], build_detail_history(rows, [], '2026-09-13', 'collected', days))

    def test_sea_four_day_review_body_repro_includes_normal_and_reviewed_history(self):
        rows = []
        for i, count in enumerate((14, 13, 13, 13), 9):
            rows.append(sea._bestbuy_row(
                id=i, product='LDY', item='J7G5658YZZ',
                crawl_strdatetime=f'2026-09-{i:02d} 18:00:00',
                count_of_reviews='14', count_of_star_ratings='14',
                detailed_review_content=' ||| '.join(f'review{n} - example' for n in range(1,count+1))))
        correction = dict(record_id=10, rule_id=7, column_name='detailed_review_content')
        for days in (3, 4):
            cursor = ScriptedCursor([
                {'fetchall': [sea._rule(7,'review_body_count',retailer='Bestbuy',product_line='sea_ldy')]},
                {'fetchall': rows}, {'fetchall': []}, {'fetchall': [correction]},
            ])
            detail = sea.sea_services.get_sea_cross_field_rule_detail(
                cursor, date(2026,9,13), 'sea_ldy', 7, days)
            self.assertEqual(list(range(13-days,13)), [r['id'] for r in detail['anomalies']])
            self.assertEqual(1, detail['total_anomalies'])
            self.assertIn('10_detailed_review_content', detail['normal_reviews'])
            if days == 4:
                self.assertEqual(14, detail['anomalies'][0]['review_body_count'])
                self.assertNotIn('issue_type', detail['anomalies'][0])

    def test_siel_and_tse_include_normal_price_history_with_current_only_count(self):
        for module, service, factory, product, date_col in (
            (siel, siel.siel_services, siel._flipkart_row, 'siel_tv', 'crawl_datetime'),
            (tse, tse.tse_services, tse._valid_row, 'tse_tv', 'crawl_datetime'),
        ):
            for days in (3, 4):
                with self.subTest(product=product, days=days):
                    rows = [factory(id=i, **{date_col: f'2026-09-{i:02d} 08:00:00'},
                                    final_sku_price='900', original_sku_price='1000') for i in range(10,14)]
                    rows[-1]['final_sku_price']='1000'
                    rule = (module._rule(7, 'final_original_price', 'Flipkart')
                            if module is siel else module._rule(7, 'final_original_price'))
                    cursor = ScriptedCursor([{'fetchall':[rule]}, {'fetchall':rows}, {'fetchall':[]}, {'fetchall':[]}])
                    detail_fn = getattr(service, f'get_{product.split("_")[0]}_cross_field_rule_detail')
                    detail = detail_fn(cursor,date(2026,9,13),product,7,days)
                    self.assertEqual(list(range(14-days,14)),[r['id'] for r in detail['anomalies']])
                    self.assertEqual(1,detail['total_anomalies'])

    def test_seg_regular_rule_includes_normal_history(self):
        fixture = seg.SegReviewHistoryTests()
        for days in (3,4):
            rows = [fixture.row(i,f'2026-09-{i:02d}',20) for i in range(6,10)]
            rows[-1]['original_sku_price']='0'
            detail, _ = fixture.result('final_original_price',rows,detail=True,days=days)
            self.assertEqual(list(range(10-days,10)),[r['id'] for r in detail['anomalies']])
            self.assertEqual(1,detail['total_anomalies'])


if __name__ == '__main__':
    unittest.main()
