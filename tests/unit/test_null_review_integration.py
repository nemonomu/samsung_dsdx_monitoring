"""NULL evidence integration across batches, countries, counts and detail rows."""

import json
import unittest
from datetime import date, datetime
from unittest.mock import Mock, patch

from apps.common import null_review_evidence as evidence
from apps.common.inspection_dates import resolve_monitoring_date
from apps.dx.dx_layer2 import null_review_state, sem_validation, seg_validation
from tests.unit.support import ScriptedCursor, load_module
from tests.unit.test_layer2_sea_null_validation import common_stubs as sea_stubs
from tests.unit.test_layer2_siel_null_validation import (
    common_stubs as siel_stubs, minimal_config,
)
from tests.unit.test_layer2_tse_null_validation import (
    common_stubs as tse_stubs, tse_columns_config,
)


DAY = date(2026, 9, 13)


def captured_evidence(context, *, record=None, reason='상품페이지 내 항목 부재',
                      column='sku'):
    record = record or {
        'id': 41, 'item': 'item-1', 'retailer_sku_name': 'Product A', 'sku': None,
    }
    cursor = ScriptedCursor([{'fetchone': (101,)}])
    evidence.save_manual_evidence(
        cursor, correction_id=51, inspection_date='2026-09-12',
        record=record, column_name=column, reason=reason,
        reviewer='reviewer', memo='페이지 확인',
        now=datetime(2026, 9, 12, 10, tzinfo=evidence.KOREA), **context,
    )
    params = cursor.calls[0][1]
    row = dict(zip(evidence._EVIDENCE_COLUMNS[1:], params))
    row.update(id=101, value_snapshot=json.loads(row['value_snapshot']))
    return row


def current_record(**changes):
    return {
        'id': 42, 'item': 'item-1', 'retailer_sku_name': 'Product A',
        'sku': None, **changes,
    }


class NullReviewStateTests(unittest.TestCase):
    def test_counts_union_actual_null_cells_and_retain_original_reason(self):
        context = dict(table_name='public.ref_retail_com', country='SEA',
                       product_line='REF', retailer='Lowes')
        row = captured_evidence(context)
        records = [current_record(), current_record(id=43, item='item-2'),
                   current_record(id=44, item='item-3', sku='real-sku')]
        manual = {'43_sku': {'reason': '수집 대상 제품 아님'},
                  '44_sku': {'reason': 'stale approval'}}
        with patch.object(evidence, 'load_evidence', return_value=[row]):
            reviews, stats, logs = null_review_state.review_state(
                Mock(), DAY, records, ['sku'], manual, **context,
                is_null=lambda value, _field: value is None,
            )
        self.assertEqual(2, stats['raw_null_count'])
        self.assertEqual(1, stats['auto_reviewed_count'])
        self.assertEqual(1, stats['manual_reviewed_count'])
        self.assertEqual({'sku': 2}, stats['reviewed_fields_detail'])
        self.assertEqual({'sku': 1}, stats['manual_reviewed_fields_detail'])
        self.assertEqual({'sku': 1}, stats['auto_reviewed_fields_detail'])
        self.assertEqual('상품페이지 내 항목 부재', reviews['42_sku']['reason'])
        self.assertNotIn('44_sku', reviews)
        self.assertIn('44_sku', manual)
        self.assertEqual('2026-09-12', logs[0]['original_crawl_date'])
        self.assertEqual(51, logs[0]['correction_id'])

    def test_field_counts_separate_automatic_manual_and_pending_nulls(self):
        context = dict(table_name='public.ref_retail_com', country='SEA',
                       product_line='REF', retailer='Lowes')
        records = [
            current_record(final_sku_price=None, star_rating=None),
            current_record(id=43, item='item-2', final_sku_price='100', star_rating='4.5'),
            current_record(id=44, item='item-3', final_sku_price='150', star_rating='4.6'),
        ]
        basis = dict(records[0], id=41)
        approvals = [
            captured_evidence(context, record=basis, column=column)
            for column in ('sku', 'final_sku_price')
        ]
        manual = {
            '43_sku': {'reason': '상품페이지 내 항목 부재'},
            '42_star_rating': {'reason': '해당값 정상 확인'},
        }
        with patch.object(evidence, 'load_evidence', return_value=approvals):
            reviews, stats, logs = null_review_state.review_state(
                Mock(), DAY, records, ['sku', 'final_sku_price', 'star_rating'],
                manual, **context, is_null=lambda value, _field: value is None,
            )
        self.assertEqual(
            {'sku': 3, 'final_sku_price': 1, 'star_rating': 1},
            stats['raw_fields_detail'],
        )
        self.assertEqual(
            {'sku': 1, 'final_sku_price': 1, 'star_rating': 0},
            stats['auto_reviewed_fields_detail'],
        )
        self.assertEqual(
            {'sku': 1, 'final_sku_price': 0, 'star_rating': 1},
            stats['manual_reviewed_fields_detail'],
        )
        self.assertEqual(
            {'sku': 2, 'final_sku_price': 1, 'star_rating': 1},
            stats['reviewed_fields_detail'],
        )
        self.assertEqual(5, stats['raw_null_count'])
        self.assertEqual(2, stats['auto_reviewed_count'])
        self.assertEqual(2, stats['manual_reviewed_count'])
        self.assertEqual(4, stats['reviewed_null_count'])
        self.assertNotIn('44_sku', reviews)
        self.assertEqual(2, len(logs))

    def test_resolved_cell_metadata_before_cutoff_is_unchanged(self):
        context = dict(table_name='public.ref_retail_com', country='SEA',
                       product_line='REF', retailer='Lowes')
        manual = {'42_sku': {'reason': '수집 대상 제품 아님'}}
        with patch.object(evidence, 'load_evidence') as loader:
            reviews, stats, logs = null_review_state.review_state(
                Mock(), date(2026, 9, 11), [current_record(sku='real-sku')],
                ['sku'], manual, **context,
                is_null=lambda value, _field: value is None,
            )
        loader.assert_not_called()
        self.assertEqual(manual, reviews)
        self.assertEqual(0, stats['reviewed_null_count'])
        self.assertEqual([], logs)

    def test_changed_same_day_value_cannot_fall_back_to_legacy_manual_row(self):
        context = dict(table_name='public.ref_retail_com', country='SEA',
                       product_line='REF', retailer='Lowes')
        row = captured_evidence(context)
        with patch.object(evidence, 'load_evidence', return_value=[row]):
            reviews, stats, _logs = null_review_state.review_state(
                Mock(), date(2026, 9, 12), [current_record(id=41, sku='')],
                ['sku'], {'41_sku': {'reason': 'legacy row'}}, **context,
                is_null=lambda value, _field: value in (None, ''),
            )
        self.assertNotIn('41_sku', reviews)
        self.assertEqual(0, stats['reviewed_null_count'])


class CountryNullIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sea = load_module(
            'apps/dx/dx_layer2/null_validation/services.py',
            'new_null_sea_service_under_test', sea_stubs(),
        )
        cls.siel = load_module(
            'apps/dx/dx_layer2/null_validation/services.py',
            'new_null_siel_service_under_test', siel_stubs(),
        )
        cls.tse = load_module(
            'apps/dx/dx_layer2/null_validation/services.py',
            'new_null_tse_service_under_test', tse_stubs(),
        )

    def test_sem_and_seg_summary_and_history_keep_auto_reviewed_row(self):
        for module, country, retailer, product_line in (
                (sem_validation, 'SEM', 'Liverpool', 'sem_tv'),
                (seg_validation, 'SEG', 'OTTO', 'seg_tv')):
            with self.subTest(country=country):
                source = dict(getattr(module, f'{country}_SOURCE_CONFIG')[product_line])
                source['retailers'] = (retailer,)
                context = dict(table_name=source['table_name'], country=country,
                               product_line='TV', retailer=retailer)
                captured = captured_evidence(context)
                record = current_record(country=country, account_name=retailer,
                                        crawl_strdatetime='2026-09-13 09:00:00')
                mapping = dict(inspection_date='2026-09-13', source_date='2026-09-13')
                required_name = ('get_sem_required_columns' if country == 'SEM'
                                 else 'get_seg_null_columns')
                with patch.object(module, f'{country}_SOURCE_CONFIG', {product_line: source}), \
                     patch.object(module, '_latest_rows', return_value=([record], mapping)), \
                     patch.object(module, '_load_normal_reviews', return_value={}), \
                     patch.object(module, required_name, return_value=('sku',)), \
                     patch.object(module, '_history_rows', return_value=[
                         {**record, 'id': 41, 'crawl_strdatetime': '2026-09-12 09:00:00'},
                         record,
                     ]), \
                     patch.object(evidence, 'load_evidence', return_value=[captured]):
                    validation = {'tables': []}
                    count = module.append_null_stats(Mock(), DAY, validation)
                    if country == 'SEM':
                        detail = module.null_detail(Mock(), DAY, product_line, 'sku', days=3)
                    else:
                        detail = module.null_detail(Mock(), DAY, product_line, retailer, 'sku', days=3)
                self.assertEqual(0, count)
                self.assertEqual(1, validation['tables'][0]['auto_reviewed_count'])
                self.assertEqual(1, validation['tables'][0]['raw_null_count'])
                retailer_stats = validation['tables'][0]['retailers'][0]
                self.assertEqual({'sku': 1}, retailer_stats['auto_reviewed_fields_detail'])
                self.assertEqual({'sku': 0}, retailer_stats['manual_reviewed_fields_detail'])
                self.assertEqual(1, len(validation['auto_null_reviews']))
                self.assertEqual([41, 42], [row['id'] for row in detail['results']])
                self.assertIn('42_sku', detail['normal_reviews'])
                self.assertNotIn('41_sku', detail['normal_reviews'])
                self.assertTrue(detail['supports_null_auto_review'])
                self.assertEqual({'sku': 1}, detail['auto_reviewed_fields_detail'])
                self.assertEqual({'sku': 0}, detail['manual_reviewed_fields_detail'])

    def test_tse_new_summary_and_detail_never_consult_old_carry_forward(self):
        runtime = self.tse._get_tse_runtime()
        runtime = {**runtime, 'sources': {'tse_tv': runtime['sources']['tse_tv']}}
        context = dict(table_name=runtime['sources']['tse_tv']['table_name'],
                       country='TSE', product_line='TV', retailer='homepro')
        captured = captured_evidence(context)
        summary_cursor = ScriptedCursor([
            {'fetchone': ('batch-13', 1, 0, 0, 1)},
            {'fetchall': [(42, 'item-1', 'Product A', 'TSE', 'Homepro', None)]},
            {'fetchall': []},
            {'fetchone': (0, None)},
        ])
        record = current_record(country='TSE', account_name='Homepro',
                                crawl_datetime='2026-09-13T09:00:00+09:00')
        detail_cursor = ScriptedCursor([
            {'description': [(key,) for key in record],
             'fetchall': [tuple(record.values())]},
            {'fetchall': []},
        ])
        with patch.object(self.tse, '_load_tse_recent_normal_reviews',
                          side_effect=AssertionError('legacy rule used')), \
             patch.object(evidence, 'load_evidence', return_value=[captured]):
            tables, count = self.tse._get_tse_null_tables(
                summary_cursor, DAY, runtime, tse_columns_config(),
            )
            detail = self.tse._get_tse_null_detail(
                detail_cursor, DAY, 'tse_tv_retail', 'Homepro', 'sku',
                runtime, tse_columns_config(),
            )
        self.assertEqual(0, count)
        self.assertEqual(1, tables[0]['auto_reviewed_count'])
        self.assertEqual(1, tables[0]['retailers'][0]['auto_reviewed_fields_detail']['sku'])
        self.assertEqual([42], [row['id'] for row in detail['results']])
        self.assertTrue(detail['normal_reviews']['42_sku']['auto_applied'])
        self.assertEqual({'sku': 1}, detail['auto_reviewed_fields_detail'])
        self.assertEqual({'sku': 0}, detail['manual_reviewed_fields_detail'])
        self.assertEqual([], self.tse.get_tse_auto_applied_null_reviews(Mock(), DAY))

    def test_sea_and_siel_details_keep_confirmed_nulls_with_visible_metadata(self):
        for service, country, retailer, category, source_date in (
                (self.sea, 'SEA', 'Lowes', 'sea_ref_retail', '2026-09-12'),
                (self.siel, 'SIEL', 'Flipkart', 'siel_ref_retail', '2026-09-13')):
            with self.subTest(country=country):
                table = ('public.ref_retail_com' if country == 'SEA'
                         else 'dx_siel.dx_siel_ref_retail_com')
                context = dict(table_name=table, country=country,
                               product_line='REF', retailer=retailer)
                captured = captured_evidence(context)
                record = current_record(account_name=retailer, country=country,
                                        crawl_strdatetime=source_date,
                                        crawl_datetime=source_date)
                cursor = ScriptedCursor([
                    {'fetchone': ('batch-13',)},
                    {'description': [(key,) for key in record],
                     'fetchall': [tuple(record.values())]},
                    {'fetchall': []},
                ])
                config_patch = (
                    patch.object(service, 'load_null_check_config',
                                 return_value=minimal_config('siel_ref', 'Flipkart', 'sku'))
                    if country == 'SIEL' else patch.object(
                        service, 'load_null_check_config', wraps=service.load_null_check_config)
                )
                with config_patch, \
                     patch.object(service, 'resolve_monitoring_date', resolve_monitoring_date), \
                     patch.object(evidence, 'load_evidence', return_value=[captured]):
                    detail = service.get_null_detail(cursor, DAY, category, retailer, 1, 'sku')
                self.assertEqual([42], [row['id'] for row in detail['results']])
                self.assertEqual(1, detail['auto_reviewed_count'])
                self.assertEqual(source_date, detail['source_date'])
                self.assertTrue(detail['normal_reviews']['42_sku']['auto_applied'])
                self.assertEqual({'sku': 1}, detail['auto_reviewed_fields_detail'])
                self.assertEqual({'sku': 0}, detail['manual_reviewed_fields_detail'])

    def test_tse_related_null_detail_drops_reason_for_a_resolved_cell(self):
        related_columns = self.tse.TSE_REVIEW_NULL_COLUMNS
        runtime = {
            **self.tse._get_tse_runtime(),
            'max_required': lambda _product: related_columns,
        }
        config = tse_columns_config()
        config['tse_tv']['Homepro']['required_columns'] = list(related_columns)
        record = current_record(
            country='TSE', account_name='Homepro',
            crawl_datetime='2026-09-13T09:00:00+09:00',
            star_rating='4.5', count_of_star_ratings=None, count_of_reviews=None,
        )
        cursor = ScriptedCursor([
            {'description': [(key,) for key in record],
             'fetchall': [tuple(record.values())]},
            {'fetchall': [
                (42, 'star_rating', '수정 전 NULL 확인', 'reviewer',
                 datetime(2026, 9, 13, 10), '상품페이지 내 항목 부재'),
                (42, 'count_of_star_ratings', '페이지 확인', 'reviewer',
                 datetime(2026, 9, 13, 10), '해당값 정상 확인'),
            ]},
        ])
        with patch.object(evidence, 'load_evidence', return_value=[]):
            detail = self.tse._get_tse_null_detail(
                cursor, DAY, 'tse_tv_retail', 'Homepro', 'star_rating',
                runtime, config,
            )
        self.assertEqual([42], [row['id'] for row in detail['results']])
        self.assertEqual('4.5', detail['results'][0]['star_rating'])
        self.assertEqual(
            ['count_of_star_ratings', 'count_of_reviews'],
            detail['results'][0]['null_fields'],
        )
        self.assertNotIn('42_star_rating', detail['normal_reviews'])
        self.assertEqual(
            '해당값 정상 확인',
            detail['normal_reviews']['42_count_of_star_ratings']['reason'],
        )
        self.assertNotIn('42_count_of_reviews', detail['normal_reviews'])
        self.assertEqual(2, detail['raw_null_count'])
        self.assertEqual(1, detail['manual_reviewed_count'])
        self.assertEqual(0, detail['auto_reviewed_count'])

    def test_tse_without_new_evidence_remains_unreviewed_after_cutoff(self):
        runtime = self.tse._get_tse_runtime()
        record = current_record(country='TSE', account_name='Homepro',
                                crawl_datetime='2026-09-13T09:00:00+09:00')
        cursor = ScriptedCursor([
            {'description': [(key,) for key in record],
             'fetchall': [tuple(record.values())]},
            {'fetchall': []},
        ])
        old_reviews = [{
            'record_id': 41, 'column_name': 'sku',
            'item': 'item-1', 'retailer_sku_name': 'Product A',
            'reason': '해당값정상 확인', 'crawl_date': date(2026, 9, 11),
        }]
        with patch.object(self.tse, '_load_tse_recent_normal_reviews',
                          return_value=old_reviews) as legacy_loader, \
             patch.object(evidence, 'load_evidence', return_value=[]):
            result = self.tse._get_tse_null_detail(
                cursor, DAY, 'tse_tv_retail', 'Homepro', 'sku',
                runtime, tse_columns_config(),
            )
        legacy_loader.assert_not_called()
        self.assertEqual([42], [row['id'] for row in result['results']])
        self.assertEqual(['sku'], result['results'][0]['null_fields'])
        self.assertEqual({}, result['normal_reviews'])
        self.assertEqual(1, result['raw_null_count'])
        self.assertEqual(0, result['reviewed_null_count'])

    def test_tse_evidence_database_error_is_not_reported_as_zero_issues(self):
        cursor = ScriptedCursor([
            {}, {'fetchone': ('batch-13', 1, 0, 0, 1)},
            {'fetchall': [(42, 'item-1', 'Product A', 'TSE', 'Homepro', None)]},
            {'fetchall': []}, {}, {},
        ])
        with patch.object(self.tse, 'load_null_check_config', return_value={}), \
             patch.object(evidence, 'load_evidence',
                          side_effect=RuntimeError('evidence unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'evidence unavailable'):
                self.tse.get_null_stats(cursor, DAY, include_youtube=False)
        self.assertIn('ROLLBACK TO SAVEPOINT', cursor.calls[-2][0])

    def test_tse_new_log_keeps_all_manual_reasons_without_legacy_expiry(self):
        table = 'dx_tse.dx_tse_tv_retail_com'
        cursor = ScriptedCursor([{'fetchall': [(
            51, table, 41, 'Homepro', 'item-1', 'sku',
            '수집 대상 제품 아님', '', date(2026, 9, 12), 'reviewer',
            datetime(2026, 9, 12, 10), 101, 'Product A',
            datetime(2026, 9, 12, 10, tzinfo=evidence.KOREA),
            date(2026, 9, 13), None,
        )]}])
        with patch.object(self.tse, 'get_auto_applied_null_reviews', return_value=[]):
            result = self.tse.get_tse_null_review_logs(cursor, date(2026, 9, 12))
        self.assertIsNone(result['recheck_days'])
        self.assertTrue(result['supports_null_auto_review'])
        self.assertEqual('수집 대상 제품 아님', result['logs'][0]['reason'])
        self.assertEqual(101, result['logs'][0]['evidence_id'])
        self.assertNotIn('14', result['logs'][0]['handling'])
        self.assertNotIn('correction.reason IN', cursor.calls[0][0])


if __name__ == '__main__':
    unittest.main()
