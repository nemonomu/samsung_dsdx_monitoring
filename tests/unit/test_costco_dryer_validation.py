"""Dryer schema, date scope, review and rule routing regressions; no live DB."""
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock, patch

from apps.common import costco_layer2 as policy
from apps.common import sea_retail
from apps.dx.dx_layer2 import null_review_state
from tests.unit.support import ScriptedCursor, load_module
from tests.unit.test_layer2_sea_null_validation import common_stubs, db_rows
from tests.unit.test_layer2_sea_format_duplicate import common_stubs as anomaly_stubs
from tests.unit import test_layer2_sea_data_edit as edit_tests
from tests.unit import test_layer2_dashboard_services as dashboard_tests
from tests.unit.test_layer3_sea_crossfield import sea_services as cross
from tests.unit.test_costco_crossfield import row, rule, FIELDS
from tests.unit.test_layer3_sea_data_edit import services as cross_edits, FakeConnection
from tests.unit.test_null_review_evidence import NullReviewEvidenceTests


TABLE = 'public.ldy_dryer_retail'
KEY = 'sea_ldy_dryer'
CATEGORY = KEY + '_retail'
DAY = date(2026, 10, 11)


def dryer_rule(key='savings_amount_match', **updates):
    value = rule(key, 'ldy_dryer')
    value.update(table_name=TABLE, date_column='crawl_datetime', **updates)
    return value


def dryer_row(**updates):
    value = row('tv', crawl_datetime='2026-10-10T04:00:00+00:00',
                sku=None, capacity='7.4 cu. ft.', loading_type=None)
    for field in ('page_type', 'product', 'detailed_review_content', 'recommendation_intent'):
        value.pop(field, None)
    value.update(updates)
    return value


class CostcoDryerValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stubs = common_stubs()
        rows = [dict(db_rows()[0], table_name=TABLE, date_column='crawl_datetime',
                     category=CATEGORY, check_name='costco_sea_ldy_dryer',
                     group_display_name='Costco', check_column=field)
                for field in (*policy.NULL_COLUMNS['ldy_dryer'], 'sku', 'loading_type', 'savings')]
        stubs['apps.common.db'].execute_dx_query = lambda *_: rows
        cls.null = load_module('apps/dx/dx_layer2/null_validation/services.py',
                              'dryer_null_under_test', stubs)
        cls.anomaly = load_module('apps/dx/dx_layer2/anomaly_validation/services.py',
                                 'dryer_anomaly_under_test', anomaly_stubs())
        edit_tests.SEALayer2DataEditTests.setUpClass()
        cls.edit = edit_tests.SEALayer2DataEditTests.service

    def test_only_requested_columns_and_layers_are_enabled(self):
        config = self.null.load_null_check_config()[CATEGORY]
        fields = config['checks']['costco']['columns']
        self.assertEqual(set((*policy.COMMON, 'capacity')), set(fields))
        self.assertEqual(10, len(fields))
        self.assertNotIn('ldy_dryer', policy.FORMAT_COLUMNS)
        self.assertNotIn('ldy_dryer', sea_retail.SEA_RETAIL_SOURCES)
        self.assertNotIn('ldy_dryer', policy.sources(sea_retail.SEA_RETAIL_SOURCES))
        self.assertEqual(('Bestbuy', 'Costco', 'HomeDepot'), self.null.SEA_RETAIL_SOURCES['ldy_dryer']['retailers'])

    def test_null_anchor_edit_and_confirmation_use_real_schema_and_launch_date(self):
        source = policy.dryer_source()
        cursor = ScriptedCursor([])
        self.assertIsNone(self.null._get_sea_null_anchor_batch(cursor, source, '2026-10-08', 'Costco'))
        self.assertEqual([], cursor.calls)
        cursor = ScriptedCursor([{'fetchone': ('batch',)}])
        self.assertEqual('batch', self.null._get_sea_null_anchor_batch(cursor, source, '2026-10-09', 'Costco'))
        sql, _ = cursor.calls[0]
        self.assertIn('2026-10-09', sql)
        self.assertNotIn('Asia/Seoul', sql)
        self.assertIn('LEFT(BTRIM(CAST(', sql)
        self.assertNotIn('page_type', sql)
        query, retailers = self.null._build_sea_latest_batch_record_query(source, 'capacity')
        self.assertNotIn('page_type', query)
        self.assertNotIn('crawl_strdatetime', query)
        self.assertEqual(['bestbuy', 'costco'], retailers)
        self.assertIn(TABLE, self.null.VALID_TABLES_UPDATE)
        self.assertEqual(('SEA', 'LDY_DRYER'), self.null._null_evidence_save_source(TABLE)[:2])
        for field in (*policy.NULL_COLUMNS['ldy_dryer'], *policy.PRICES):
            cursor = ScriptedCursor([{'fetchone': (None, 'Costco', '123')}, {}, {}])
            with patch.object(self.edit, 'resolve_monitoring_date', return_value={'source_date': '2026-10-10'}):
                result = self.edit.update_cell_value(cursor, Mock(), TABLE, 42, field, '1', DAY, 'null', 'tester', 'fixed')
            self.assertTrue(result.get('success'), result)
            self.assertNotIn('page_type', cursor.calls[0][0])
            self.assertIn('2026-10-09', cursor.calls[0][0])
            self.assertIn('INSERT INTO monitoring_corrections', cursor.calls[-1][0])

    def test_null_detail_has_query_and_review_controls(self):
        record = dryer_row(capacity=None)
        cursor = ScriptedCursor([{'fetchone': ('batch',)},
                                {'description': [(key,) for key in record], 'fetchall': [tuple(record.values())]},
                                {}, {}, {}, {}, {}])
        with patch.object(self.null, 'resolve_monitoring_date', return_value=dict(
                inspection_date=str(DAY), source_date='2026-10-10', offset_days=-1, source_key=KEY)):
            result = self.null.get_null_detail(cursor, DAY, CATEGORY, 'Costco', 1, 'capacity')
        self.assertEqual(1, result['raw_null_count'])
        self.assertIn('capacity', result['editable_cols'])
        self.assertNotIn('sku', result['editable_cols'])
        self.assertNotIn('loading_type', result['editable_cols'])
        self.assertEqual('2026-10-10', result['results'][0]['_source_date'])
        self.assertIn(TABLE, str(result))
        for sql, _ in cursor.calls[:2]:
            self.assertNotIn('page_type', sql)
            self.assertNotIn('crawl_strdatetime', sql)

    def test_null_review_uses_dryer_evidence_namespace(self):
        with patch.object(null_review_state.null_review_evidence, 'load_evidence', return_value=[]) as evidence:
            null_review_state.review_state(Mock(), DAY, [], ['capacity'], {},
                table_name=TABLE, country='SEA', product_line=KEY, retailer='Costco',
                is_null=lambda value, field: value is None)
        self.assertEqual('LDY_DRYER', evidence.call_args.kwargs['product_line'])

    def test_null_confirmation_saves_evidence_and_capacity_can_carry(self):
        cursor = ScriptedCursor([
            {'fetchone': (None, 'Costco', '123')},
            {'fetchone': (42, '123', 'Dryer', None, 'Costco')},
            {'fetchone': None}, {'fetchone': (101,)},
        ])
        with patch.object(self.null, 'resolve_monitoring_date', return_value={'source_date': '2026-10-10'}), patch.object(
                null_review_state.null_review_evidence, 'save_manual_evidence', return_value={'auto_eligible': True}) as saved:
            result = self.null.save_null_review(cursor, Mock(), TABLE, 42, 'capacity',
                'normal', 'checked', '상품페이지 내 항목 부재', str(DAY), 'null', 'tester')
        self.assertTrue(result.get('success'), result)
        self.assertEqual('LDY_DRYER', saved.call_args.kwargs['product_line'])
        self.assertIn('INSERT INTO monitoring_corrections', cursor.calls[-1][0])
        helper = NullReviewEvidenceTests()
        helper.setUp()
        context = dict(table_name=TABLE, country='SEA', product_line='LDY_DRYER', retailer='Costco')
        record = dict(id=42, item='123', retailer_sku_name='Dryer', capacity=None)
        _, evidence, _ = helper.capture(record=record, context=context, column='capacity',
            day='2026-10-10', now=datetime(2026, 10, 10, 13, tzinfo=null_review_state.null_review_evidence.KOREA))
        match = helper.match(evidence, record=dict(record, id=43), context=context, column='capacity', day=str(DAY))
        self.assertTrue(match['auto_applied'])
        self.assertIsNone(helper.match(evidence, record=dict(record, retailer_sku_name='Different'),
                                      context=context, column='capacity', day=str(DAY)))

    def test_duplicates_are_latest_item_only_and_readonly(self):
        source = policy.dryer_source()
        cursor = ScriptedCursor([{'fetchall': []}])
        self.anomaly._fetch_sea_duplicate_rows(cursor, '2026-10-10', source, 'Costco')
        sql, _ = cursor.calls[0]
        self.assertNotIn('page_type', sql)
        self.assertIn('source.batch_id IS NOT DISTINCT FROM latest_batch.batch_id', sql)
        first = dryer_row(id=1, item='123', batch_id='a', main_rank=1, bsr_rank=1)
        groups = self.anomaly.build_sea_duplicate_groups
        self.assertEqual([], groups([first], 'Costco'))
        self.assertEqual([], groups([first, dict(first, id=2, batch_id='b')], 'Costco'))
        self.assertEqual(1, len(groups([first, dict(first, id=2)], 'Costco')))
        cursor = ScriptedCursor([])
        result = self.anomaly.cleanup_duplicates(cursor, Mock(), CATEGORY, [1], DAY, 'tester')
        self.assertEqual(403, result['status'])
        self.assertEqual([], cursor.calls)

    def test_crossfield_filters_other_retailers_and_missing_columns(self):
        cursor = ScriptedCursor([{'fetchall': [dryer_rule('review_count_match'),
            dryer_rule('review_count_match', retailer='Lowes'),
            dryer_rule('review_count_match', retailer='ALL')]}])
        rules = cross.load_active_sea_rules(cursor, KEY)
        self.assertEqual(1, len(rules))
        self.assertEqual(['Costco'], rules[0]['_retailers'])
        self.assertNotIn('detailed_review_content', rules[0]['select_fields'])
        query = cross.build_sea_display_query(DAY, KEY, rules[0], retailer='Costco')
        for absent in ('detailed_review_content', 'page_type', 'crawl_strdatetime'):
            self.assertNotIn(absent, query)
        self.assertIn(TABLE, query)
        self.assertIn('2026-10-09', query)

    def test_crossfield_same_seven_rules_and_matching_summary_detail(self):
        data = dryer_row(savings='$101')
        def cursor():
            return ScriptedCursor([{'fetchall': [dryer_rule()]},
                                   {'fetchall': [data]}, {'fetchall': []}])
        with patch.object(cross, 'exclude_page_absent_records', side_effect=lambda cur, day, rows, **kw: (rows, [])) as excluded:
            summary = cross.get_sea_cross_field_summary(cursor(), DAY, KEY)
            detail = cross.get_sea_cross_field_rule_detail(cursor(), DAY, KEY, 1)
        self.assertEqual(1, summary['total_anomalies'])
        self.assertEqual(summary['total_anomalies'], detail['total_anomalies'])
        self.assertEqual('LDY_DRYER', excluded.call_args.kwargs['product_line'])
        self.assertEqual(set(FIELDS), set(detail['editable_columns']))
        self.assertEqual(set(), cross.evaluate_sea_row(dryer_row()))
        self.assertEqual({'savings_amount_match'}, cross.evaluate_sea_row(data))
        cur = ScriptedCursor([{'fetchall': []}])
        cross.load_latest_sea_rows(cur, DAY, KEY)
        sql, params = cur.calls[0]
        self.assertEqual(('2026-10-10', '2026-10-10'), params)
        self.assertNotIn('page_type', sql)
        self.assertIn('2026-10-09', sql)

    def test_crossfield_edit_retains_audit_and_latest_scope(self):
        for field in FIELDS:
            cur = ScriptedCursor([{'fetchone': ('1', None, 'Costco', 'item-1')}, {}, {}])
            with patch.object(cross_edits, 'get_editable_columns', return_value=list(FIELDS)):
                result = cross_edits.update_cell_value(cur, FakeConnection(), TABLE,
                    42, field, '2', str(DAY), 'cross_field', 'tester', 'verified', rule_id=1)
            self.assertTrue(result.get('success'), result)
            self.assertNotIn('page_type', cur.calls[0][0])
            self.assertIn('INSERT INTO monitoring_corrections', cur.calls[-1][0])
        cur = ScriptedCursor([{'fetchone': ('101', 'Costco', 'item-1')}, {'fetchone': None}, {}])
        result = cross_edits.save_review(cur, FakeConnection(), TABLE, 42, 'savings',
            'normal', 'verified', 'checked', str(DAY), 'cross_field', 'tester', rule_id=1)
        self.assertTrue(result.get('success'), result)
        self.assertIn('2026-10-09', cur.calls[0][0])
        self.assertIn('INSERT INTO monitoring_corrections', cur.calls[-1][0])

    def test_registration_scripts_only_target_dryer(self):
        for name in ('layer2', 'crossfield'):
            sql = Path(f'sql/setup_costco_dryer_{name}.sql').read_text(encoding='utf-8')
            self.assertIn(TABLE, sql)
            self.assertNotIn('public.ldy_retail_com', sql)
            self.assertNotIn("'sea_ldy_retail'", sql)

    def test_dashboard_review_and_history_use_dryer_category(self):
        from apps.dx.dx_layer2.null_validation import review_history
        source = review_history._sources()['ldy_dryer_retail']
        self.assertEqual('LDY_DRYER', source['product_line'])
        self.assertEqual(CATEGORY, source['history_category'])
        dashboard_tests.Layer2DashboardIsolationTests.setUpClass()
        service = dashboard_tests.Layer2DashboardIsolationTests.service
        self.assertTrue(service.supports_null_auto_detail('null', CATEGORY, DAY))
        self.assertFalse(service.supports_null_auto_detail('format', CATEGORY, DAY))


if __name__ == '__main__':
    unittest.main()
