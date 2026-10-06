"""Costco rollout regression tests, isolated from environment and live DBs."""
import unittest
from datetime import date, datetime
from unittest.mock import Mock, patch

from apps.common import costco_layer2 as policy
from apps.common import null_review_evidence as reviews
from tests.unit.support import ScriptedCursor, load_module
from tests.unit.test_layer2_sea_null_validation import common_stubs, db_rows
from tests.unit.test_layer2_sea_format_duplicate import common_stubs as anomaly_stubs
from tests.unit import test_layer2_sea_data_edit as edit_tests
from tests.unit import test_null_review_evidence as evidence_tests


class CostcoLayer2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stubs = common_stubs()
        rows = db_rows()
        sample = rows[0]
        for product, fields in policy.NULL_COLUMNS.items():
            rows.extend(dict(sample, table_name=f'public.{product}_retail_com',
                             check_name=f'costco_{product}', group_display_name='Costco',
                             date_column='crawl_datetime' if product == 'tv' else 'crawl_strdatetime',
                             check_column=field) for field in (*fields, 'savings'))
        stubs['apps.common.db'].execute_dx_query = lambda *_: rows
        cls.null = load_module('apps/dx/dx_layer2/null_validation/services.py',
                              'costco_null_under_test', stubs)
        cls.anomaly = load_module('apps/dx/dx_layer2/anomaly_validation/services.py',
                                 'costco_anomaly_under_test', anomaly_stubs())
        edit_tests.SEALayer2DataEditTests.setUpClass()
        cls.edit = edit_tests.SEALayer2DataEditTests.service

    def test_exact_null_columns_and_all_prices_ratings_visible(self):
        config = self.null.load_null_check_config()
        for product, fields in policy.NULL_COLUMNS.items():
            category = 'tv_retail' if product == 'tv' else f'sea_{product}_retail'
            self.assertEqual(set(fields), set(config[category]['checks']['costco']['columns']))
            self.assertEqual(10 if product == 'tv' else 11, len(fields))
            for field in fields:
                displayed = policy.display_columns(product, field)
                self.assertTrue(set((*policy.METRICS, *policy.PRICES)) <= set(displayed))
                self.assertEqual(len(displayed), len(set(displayed)))

    def test_utc_to_kst_and_launch_boundary(self):
        for stamp in ('2026-10-03T15:00:00+00:00', '2026-10-03 15:00:00'):
            row = policy.annotate_source_date({'account_name': 'Costco', 'crawl_datetime': stamp})
            self.assertEqual('2026-10-04', row['_source_date'])
            self.assertEqual(stamp, row['crawl_datetime'])
        sql = policy.source_date_sql('crawl_datetime', retailer='Costco')
        self.assertIn("'Asia/Seoul'", sql)
        self.assertIn("'2026-10-04'", sql)

    def test_latest_batch_null_scope_includes_unranked_rows(self):
        for product in policy.NULL_COLUMNS:
            source = self.null._get_sea_null_source_for_table(f'public.{product}_retail_com')
            cursor = ScriptedCursor([{'fetchone': ('batch-2',)}])
            self.assertEqual('batch-2', self.null._get_sea_null_anchor_batch(cursor, source, '2026-10-05', 'Costco'))
            sql, _ = cursor.calls[0]
            self.assertIn('ORDER BY anchor.id DESC', sql)
            self.assertNotIn('page_type', sql)
            scope, params = self.null._build_sea_null_scope(source, '2026-10-05', 'Costco', 'batch-2')
            self.assertIn('batch_id = %s', scope)
            self.assertNotIn('page_type', scope)
            self.assertEqual(['2026-10-05', 'Costco', 'batch-2'], params)

    def test_duplicate_item_is_scoped_to_one_batch_and_combined_ranks(self):
        row = dict(id=1, batch_id='a', account_name='Costco', item='123',
                   retailer_sku_name='Product', page_type=None, main_rank='1', bsr_rank='2')
        group = self.anomaly.build_sea_duplicate_groups
        self.assertEqual([], group([row], 'Costco'))
        self.assertEqual([], group([row, dict(row, id=2, batch_id='b')], 'Costco'))
        self.assertEqual(1, len(group([row, dict(row, id=2)], 'Costco')))

    def test_tv_duplicate_fetch_never_queries_nonexistent_sku(self):
        cursor = ScriptedCursor([{'fetchall': []}])
        source = self.anomaly.SEA_RETAIL_SOURCES['tv']
        self.anomaly._fetch_sea_duplicate_rows(cursor, '2026-10-05', source, 'Costco')
        sql, params = cursor.calls[0]
        self.assertNotIn('source.sku', sql)
        self.assertIn('source.batch_id IS NOT DISTINCT FROM latest_batch.batch_id', sql)
        self.assertEqual(('2026-10-05', 'Costco') * 2, params)
        cursor = ScriptedCursor([])
        self.assertEqual([], self.anomaly._fetch_sea_duplicate_rows(cursor, '2026-10-03', source, 'Costco'))
        self.assertEqual([], cursor.calls)

    def test_all_null_fields_and_price_fields_can_be_edited_with_audit(self):
        registry = {key: dict(source, product_line='tv' if key == 'tv' else 'sea_' + key)
                    for key, source in self.null.SEA_RETAIL_SOURCES.items()}
        for product, fields in policy.NULL_COLUMNS.items():
            for field in set((*fields, *policy.PRICES)):
                cursor = ScriptedCursor([{'fetchone': (None, 'Costco', '123')}, {}, {}])
                with patch.object(self.edit, 'SEA_RETAIL_SOURCES', registry), patch.object(
                        self.edit, 'resolve_monitoring_date', return_value={'source_date': '2026-10-05'}):
                    result = self.edit.update_cell_value(cursor, Mock(), f'public.{product}_retail_com',
                                                        42, field, '1', date(2026, 10, 6), 'null', 'tester', 'fixed')
                self.assertTrue(result.get('success'), result)
                self.assertIn('ORDER BY anchor.id DESC', cursor.calls[0][0])
                self.assertEqual((42, '2026-10-05', '2026-10-05'), cursor.calls[0][1])
                self.assertIn('INSERT INTO monitoring_corrections', cursor.calls[-1][0])

    def test_outside_latest_batch_cannot_be_updated(self):
        cursor = ScriptedCursor([{'fetchone': None}])
        result = self.edit.update_cell_value(cursor, Mock(), 'public.ref_retail_com',
                                            42, 'sku', 'x', date(2026, 10, 6), 'null', 'tester', '')
        self.assertEqual(404, result['status'])
        self.assertEqual(1, len(cursor.calls))

    def test_rating_detail_returns_all_three_null_fields_and_prices(self):
        for product in policy.NULL_COLUMNS:
            date_col = 'crawl_datetime' if product == 'tv' else 'crawl_strdatetime'
            record = dict(id=42, account_name='Costco', item='123', retailer_sku_name='Product',
                          batch_id='b', **{date_col: '2026-10-04T16:00:00+00:00'},
                          **{field: None for field in (*policy.METRICS, *policy.PRICES)})
            cursor = ScriptedCursor([{'fetchone': ('b',)},
                                    {'description': [(key,) for key in record], 'fetchall': [tuple(record.values())]},
                                    {}, {}, {}, {}, {}])
            mapping = dict(inspection_date='2026-10-06', source_date='2026-10-05',
                           offset_days=-1, source_key='sea_' + product)
            with patch.object(self.null, 'resolve_monitoring_date', return_value=mapping):
                result = self.null.get_null_detail(cursor, date(2026, 10, 6),
                    'tv_retail' if product == 'tv' else f'sea_{product}_retail', 'Costco', 1, 'star_rating')
            self.assertEqual(list(policy.METRICS), result['results'][0]['null_fields'])
            self.assertEqual('2026-10-05 01:00:00', result['results'][0][date_col])
            self.assertEqual('2026-10-05', result['results'][0]['_source_date'])
            self.assertTrue(set((*policy.METRICS, *policy.PRICES)) <= set(result['editable_cols']))
            self.assertEqual(3, result['raw_null_count'])
            for metric in policy.METRICS:
                self.assertIn(metric, cursor.calls[1][0])

    def test_tv_cleanup_is_costco_only_and_outside_scope_never_deleted(self):
        cursor = ScriptedCursor([{'fetchall': []}])
        with patch.object(self.anomaly, 'resolve_monitoring_date', return_value={'source_date': '2026-10-05'}):
            result = self.anomaly.cleanup_duplicates(cursor, Mock(), 'costco_tv_retail', [42],
                                                      '2026-10-06', 'tester')
        self.assertEqual(0, result['deleted_count'])
        self.assertEqual(1, len(cursor.calls))
        self.assertEqual(('2026-10-05', 'costco', 42, '2026-10-05'), cursor.calls[0][1])
        self.assertIn('t.batch_id IS NOT DISTINCT FROM latest.batch_id', cursor.calls[0][0])

    def test_metric_reviews_manual_only_but_specs_carry(self):
        helper = evidence_tests.NullReviewEvidenceTests()
        helper.setUp()
        context = dict(helper.context, retailer='Costco')
        now = datetime(2026, 10, 4, 13, tzinfo=reviews.KOREA)
        for field in (*policy.METRICS, *policy.PRICES, 'ref_capacity'):
            record = dict(helper.record, **{field: None})
            metadata, evidence, _ = helper.capture(record=record, context=context, column=field,
                                                   day='2026-10-04', now=now)
            self.assertFalse(helper.match(evidence, record=record, context=context,
                                           column=field, day='2026-10-04')['auto_applied'])
            match = helper.match(evidence, record=dict(record, id=43), context=context,
                                 column=field, day='2026-10-05')
            if field == 'ref_capacity':
                self.assertTrue(match['auto_applied'])
            else:
                self.assertFalse(metadata['auto_eligible'])
                self.assertIsNone(match)

    def test_page_absence_from_spec_links_all_metrics_only_on_same_day(self):
        helper = evidence_tests.NullReviewEvidenceTests()
        helper.setUp()
        context = dict(helper.context, retailer='Costco')
        record = dict(helper.record, **{field: None for field in (*policy.METRICS, *policy.PRICES)})
        for reason in ('상품페이지 없음', '수집 대상 제품 아님'):
            _, evidence, _ = helper.capture(record=record, context=context, reason=reason,
                                            day='2026-10-04', now=datetime(2026, 10, 4, 13, tzinfo=reviews.KOREA))
            for field in (*policy.METRICS, *policy.PRICES):
                linked = reviews.linked_null_review(record, field, '2026-10-04', [evidence], **context)
                if reason == '상품페이지 없음':
                    self.assertTrue(linked['auto_applied'])
                else:
                    self.assertIsNone(linked)
                self.assertIsNone(reviews.linked_null_review(dict(record, id=43), field,
                                                             '2026-10-05', [evidence], **context))


if __name__ == '__main__':
    unittest.main()
