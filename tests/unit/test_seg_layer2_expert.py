import unittest
from datetime import date
from unittest.mock import Mock, patch

from apps.common import seg_retail, null_review_evidence
from apps.dx.dx_layer2 import seg_sources as config, seg_validation as seg
from apps.dx.dx_layer2.data_edit import services as edits
from apps.dx.dx_layer2.null_validation import services as nulls, review_history
from apps.dx.dx_layer2.format_validation import services as formats
from apps.dx.dx_layer2.null_review_state import review_state
from tests.unit.support import ScriptedCursor


DAY = date(2026, 10, 11)
DRYER = 'seg_ldy_dryer'


class ExpertLayer2Tests(unittest.TestCase):
    def test_exact_required_fields_and_scope_isolation(self):
        common = {'item', 'product_url', 'sku', 'retailer_sku_name',
                  'final_sku_price', 'star_rating', 'count_of_reviews', 'count_of_star_ratings'}
        extras = {'seg_tv': {'screen_size'}, 'seg_ref': {'ref_capacity', 'ref_refrigerator_type'},
                  'seg_ldy': {'ldy_capacity', 'ldy_loading_type'}, DRYER: {'capacity', 'loading_type'}}
        for key, fields in extras.items():
            self.assertEqual(common | fields, set(config.get_seg_null_columns(key, 'expert')))
            self.assertEqual((), config.get_seg_format_columns(key, 'Expert'))
        self.assertNotIn(DRYER, seg_retail.SEG_SOURCE_CONFIG)
        self.assertNotIn('Expert', seg.SEG_FORMAT_SOURCE_CONFIG['seg_tv']['retailers'])
        self.assertNotIn('seg_ldy_dryer_retail', formats.VALID_TABLES_FORMAT)
        self.assertIn(config.resolve_seg_table(DRYER), nulls.VALID_TABLES_UPDATE)
        self.assertIn(config.resolve_seg_table(DRYER), edits.VALID_TABLES_UPDATE)

    def test_latest_rows_and_history_ignore_page_type_for_expert(self):
        for key in config.SEG_SOURCE_CONFIG:
            source = config.SEG_SOURCE_CONFIG[key]
            cursor = ScriptedCursor([{'fetchone': ('e1',)},
                                     {'description': [('id',), ('item',)], 'fetchall': [(7, 'I1')]}])
            rows, mapping = seg._latest_rows(cursor, DAY, source, 'Expert')
            self.assertEqual([{'id': 7, 'item': 'I1'}], rows)
            self.assertEqual('e1', mapping['batch_id'])
            for sql, _ in cursor.calls:
                self.assertNotIn('page_type', sql)
                self.assertIn(source['date_column'], sql)
            self.assertIn('source.batch_id IS NOT DISTINCT FROM %s', cursor.calls[1][0])
            history = ScriptedCursor([{'description': [('id',)], 'fetchall': []}])
            seg._history_rows(history, source, 'Expert', date(2026, 10, 9), DAY, ['I1'])
            sql, params = history.calls[0]
            self.assertNotIn('page_type', sql)
            self.assertEqual('2026-10-11', params[0])
        cursor = Mock()
        rows, _ = seg._latest_rows(cursor, date(2026, 10, 10), source, 'Expert')
        self.assertEqual([], rows)
        cursor.execute.assert_not_called()

    def test_null_stats_count_cells_zero_is_present_and_detail_uses_dryer_date(self):
        row = dict.fromkeys(config.get_seg_null_columns(DRYER, 'Expert'), 'value')
        row.update(id=1, item='', product_url=' ', capacity=None, star_rating=0,
                   count_of_reviews='0', crawl_datetime='2026-10-11T11:00:00+09:00')
        mapping = {'inspection_date': str(DAY), 'source_date': str(DAY), 'batch_id': 'e1'}
        with patch.object(seg, '_latest_rows', return_value=([row], mapping)), \
                patch.object(seg, '_load_normal_reviews', return_value={}), \
                patch.object(seg, 'uses_new_policy', return_value=False):
            stats = {'tables': []}
            self.assertEqual(3, seg.append_null_stats(None, DAY, stats, 'seg_ldy_dryer_retail'))
            counts = stats['tables'][0]['retailers'][0]['fields_detail']
            self.assertEqual(0, counts['star_rating'])
            self.assertEqual(1, counts['item'])
            detail = seg.null_detail(None, DAY, DRYER, 'Expert', 'item', days=1)
            self.assertEqual('crawl_datetime', detail['date_column'])
            self.assertIn('crawl_datetime', detail['display_config']['item']['select_columns'])
            self.assertNotIn('page_type', detail['select_cols'])
            self.assertIn('product_url', detail['editable_cols'])
            self.assertEqual({'item', 'product_url', 'capacity'}, set(detail['results'][0]['null_fields']))

    def test_duplicate_item_crosses_main_bsr_rows_but_not_single_row(self):
        base = dict(item='I1', sku='S1', retailer_sku_name='Name', main_rank=1, bsr_rank=1)
        self.assertEqual([], seg.build_duplicate_groups([dict(base, id=1)], 'Expert'))
        rows = [dict(base, id=1, page_type='main'), dict(base, id=2, page_type='bsr')]
        groups = seg.build_duplicate_groups(rows, 'Expert')
        self.assertEqual(1, len(groups))
        self.assertEqual(2, groups[0]['dup_count'])
        self.assertEqual('완전 중복', groups[0]['duplicate_type'])
        rows[1]['sku'] = 'S2'
        self.assertEqual('상품 매핑 충돌', seg.build_duplicate_groups(rows, 'Expert')[0]['duplicate_type'])
        self.assertEqual([], seg.build_duplicate_groups(rows, 'Mediamarkt'))
        self.assertEqual([], seg.build_duplicate_groups([dict(base, item=None), dict(base, item='')], 'Expert'))
        with patch.object(seg, '_latest_rows', return_value=(rows, {'inspection_date': str(DAY)})):
            stats = {'tables': []}
            self.assertEqual(1, seg.append_duplicate_stats(None, DAY, stats, 'seg_ldy_dryer_retail'))
            self.assertEqual(['item'], stats['tables'][0]['duplicate_keys'])
            detail = seg.duplicate_detail(None, DAY, DRYER, 'Expert')
            self.assertTrue(detail['readonly'])
            self.assertNotIn('page_type', detail['select_cols']['group'])
            self.assertIn('crawl_datetime', detail['select_cols']['record'])

    def test_before_start_has_no_dryer_queries_or_findings(self):
        cursor = Mock()
        for fn in (seg.append_null_stats, seg.append_duplicate_stats):
            stats = {'tables': []}
            self.assertEqual(0, fn(cursor, date(2026, 10, 10), stats, 'seg_ldy_dryer_retail'))
            self.assertEqual([], stats['tables'])
        self.assertEqual([], seg.null_detail(cursor, date(2026, 10, 10), DRYER, 'Expert', 'item')['results'])
        cursor.execute.assert_not_called()

    def test_edit_and_review_record_queries_follow_latest_batch_schema(self):
        context = edits._get_seg_edit_context(config.resolve_seg_table(DRYER))
        cursor = Mock()
        edits._select_seg_edit_record(cursor, context, 'item, account_name, item, batch_id', 1, DAY)
        self.assertNotIn('page_type', cursor.execute.call_args.args[0])
        self.assertIn('crawl_datetime', cursor.execute.call_args.args[0])
        cursor = ScriptedCursor([{'fetchone': (None, 'expert', 'I1')}])
        self.assertEqual((None, 'expert', 'I1'), seg.fetch_review_record(cursor, DAY, DRYER, 1, 'capacity'))
        self.assertNotIn('page_type', cursor.calls[0][0])
        self.assertIn('AND FALSE', config.record_scope(config.get_seg_source(DRYER), '2026-10-10'))
        self.assertEqual((), seg.get_review_allowed_columns(DRYER, 'expert', 'format_check'))

    def test_dryer_evidence_and_history_keep_full_product_name(self):
        with patch.object(null_review_evidence, 'load_evidence', return_value=[]) as load:
            review_state(Mock(), DAY, [], ['capacity'], {}, table_name=config.resolve_seg_table(DRYER),
                         country='SEG', product_line=DRYER, retailer='Expert', is_null=lambda v, c: v is None)
            self.assertEqual('LDY_DRYER', load.call_args.kwargs['product_line'])
        self.assertIn('LDY_DRYER', null_review_evidence.PRODUCT_LINES)
        history = review_history._sources()[config.resolve_seg_table(DRYER)]
        self.assertEqual('LDY_DRYER', history['product_line'])
        self.assertEqual('seg_ldy_dryer_retail', history['history_category'])
