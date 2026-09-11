import unittest
from contextlib import contextmanager
from datetime import date
from unittest.mock import Mock, patch

from tests.unit.support import ScriptedCursor, load_module, module_stub


class Layer4ReportAutoNullTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = load_module(
            'apps/dx/dx_layer4/report/services.py',
            'layer4_report_auto_null_under_test',
            stubs={
                'apps.common.db': module_stub(
                    'apps.common.db', dx_connection=None,
                ),
            },
        )

    def test_auto_applied_null_is_included_in_daily_report_payload(self):
        type_summary = {}
        reason_summary = []
        table_summary = {}
        details = []
        auto_reviews = [{
            'table_name': 'dx_tse.dx_tse_ldy_retail_com',
            'record_id': 4934,
            'column_name': 'sku',
            'memo': '',
            'created_id': 'y.k.kim',
            'retailer': 'Homepro',
            'item': '888213600004',
            'original_crawl_date': '2026-08-23',
            'original_created_at': '2026-08-23 15:21:18',
        }]

        self.service._merge_tse_auto_null_reviews(
            auto_reviews,
            type_summary,
            reason_summary,
            table_summary,
            details,
        )

        self.assertEqual(1, type_summary['null_check']['normal'])
        self.assertEqual(1, reason_summary[0]['count'])
        self.assertEqual('해당값정상 확인 (자동 적용)', reason_summary[0]['reason'])
        self.assertEqual(
            1,
            table_summary['dx_tse.dx_tse_ldy_retail_com'][
                'null_check'
            ]['normal'],
        )
        self.assertTrue(details[0]['auto_applied'])
        self.assertEqual('해당값정상 확인 (자동 적용)', details[0]['reason'])
        self.assertEqual('2026-08-23', details[0]['original_crawl_date'])

    def test_each_auto_reason_and_its_original_evidence_are_preserved(self):
        reasons = [
            '수집 대상 제품 아님',
            '상품페이지 내 항목 부재',
            '해당값 정상 확인',
        ]
        reviews = [{
            'table_name': 'public.ref_retail_com',
            'record_id': index,
            'column_name': 'ref_capacity',
            'reason': reason,
            'created_id': 'reviewer',
            'evidence_id': 100 + index,
            'correction_id': 200 + index,
            'original_crawl_date': '2026-09-12',
            'original_created_at': '2026-09-12T10:00:00+09:00',
            'revoked_at': '2026-09-15T12:00:00+09:00',
        } for index, reason in enumerate(reasons, 1)]
        type_summary, reason_summary, table_summary, details = {}, [], {}, []

        self.service._merge_auto_null_reviews(
            reviews, type_summary, reason_summary, table_summary, details,
        )

        self.assertEqual(3, type_summary['null_check']['normal'])
        self.assertEqual(
            {f'{reason} (자동 적용)': 1 for reason in reasons},
            {row['reason']: row['count'] for row in reason_summary},
        )
        self.assertEqual(reasons, [row['original_reason'] for row in details])
        self.assertEqual(101, details[0]['evidence_id'])
        self.assertEqual(201, details[0]['correction_id'])
        self.assertEqual('reviewer', details[0]['created_id'])
        self.assertEqual(
            '2026-09-15T12:00:00+09:00', details[0]['revoked_at'],
        )

    def test_legacy_report_preserves_its_existing_count_and_reason(self):
        review = {
            'table_name': 'dx_tse.dx_tse_ref_retail_com',
            'record_id': 1, 'column_name': 'ref_capacity',
            'reason': '해당 값 정상 확인',
        }
        details = [{
            **review, 'correction_type': 'null_check', 'status': 'normal',
        }]
        type_summary = {'null_check': {'normal': 1}}
        reason_summary = []
        table_summary = {}

        self.service._merge_tse_auto_null_reviews(
            [review], type_summary, reason_summary, table_summary, details,
        )

        self.assertEqual(2, type_summary['null_check']['normal'])
        self.assertEqual('해당값정상 확인 (자동 적용)', details[-1]['reason'])

    def test_auto_cells_do_not_duplicate_manual_corrected_or_auto_cells(self):
        table_name = 'public.ref_retail_com'
        details = [{
            'table_name': 'ref_retail_com',
            'record_id': record_id,
            'column_name': 'ref_capacity',
            'correction_type': 'null_check',
            'status': status,
        } for record_id, status in [(1, 'normal'), (2, 'corrected')]]
        # A cross-field review of the same cell is not a NULL review.
        details.append({
            'table_name': table_name, 'record_id': 3,
            'column_name': 'ref_capacity', 'correction_type': 'cross_field',
            'status': 'normal',
        })
        type_summary = {'null_check': {'normal': 1, 'corrected': 1}}
        reason_summary = []
        table_summary = {}
        reviews = [{
            'table_name': table_name, 'record_id': str(record_id),
            'column_name': 'ref_capacity', 'reason': '상품페이지 내 항목 부재',
        } for record_id in [1, 2, 3, 3]]

        for _ in range(2):
            self.service._merge_auto_null_reviews(
                reviews, type_summary, reason_summary, table_summary, details,
            )

        self.assertEqual(2, type_summary['null_check']['normal'])
        self.assertEqual(1, type_summary['null_check']['corrected'])
        self.assertEqual(4, len(details))
        self.assertEqual(1, reason_summary[0]['count'])
        self.assertEqual(1, table_summary[table_name]['null_check']['normal'])

    def test_date_boundary_selects_exactly_one_auto_policy(self):
        legacy_loader = Mock(return_value=['legacy'])
        new_loader = Mock(return_value=['new'])
        module_name = 'apps.dx.dx_layer2.null_validation.services'
        stub = module_stub(
            module_name,
            get_tse_auto_applied_null_reviews=legacy_loader,
            get_auto_applied_null_reviews=new_loader,
        )
        cursor = object()
        with patch.dict('sys.modules', {module_name: stub}):
            before = self.service._load_auto_null_reviews(
                cursor, date(2026, 9, 11),
            )
            after = self.service._load_auto_null_reviews(
                cursor, date(2026, 9, 12),
            )

        self.assertEqual(['legacy'], before)
        self.assertEqual(['new'], after)
        legacy_loader.assert_called_once_with(cursor, date(2026, 9, 11))
        new_loader.assert_called_once_with(cursor, date(2026, 9, 12))

    def test_full_report_loads_and_counts_auto_reviews_once(self):
        cursor = ScriptedCursor([{'fetchall': []} for _ in range(8)])

        @contextmanager
        def connection():
            yield object(), cursor

        review = {
            'table_name': 'dx_sem.dx_sem_ref_retail_com',
            'record_id': 10, 'column_name': 'ref_capacity',
            'reason': '상품페이지 내 항목 부재',
        }
        with patch.object(self.service, 'dx_connection', connection), \
                patch.object(self.service, '_load_auto_null_reviews',
                             return_value=[review]) as loader:
            result = self.service.get_report_data('2026-09-13')

        loader.assert_called_once_with(cursor, '2026-09-13')
        self.assertEqual(1, result['type_summary']['null_check']['normal'])
        self.assertEqual(1, len(result['details']))
        self.assertEqual(
            result['details'],
            result['grouped_details']['null_check'][review['table_name']],
        )

    def test_legacy_sea_retailer_is_filled_from_source_record(self):
        details = [
            {
                'table_name': 'public.ref_retail_com',
                'record_id': 101,
                'retailer': '',
            },
            {
                'table_name': 'public.ldy_retail_com',
                'record_id': 202,
                'retailer': 'Retail',
            },
            {
                'table_name': 'public.ref_retail_com',
                'record_id': 303,
                'retailer': 'Bestbuy',
            },
        ]
        cursor = ScriptedCursor([
            {'fetchall': [(101, 'Lowes')]},
            {'fetchall': [(202, 'Bestbuy')]},
        ])

        self.service._fill_sea_retailer_names(cursor, details)

        self.assertEqual('Lowes', details[0]['retailer'])
        self.assertEqual('Bestbuy', details[1]['retailer'])
        self.assertEqual('Bestbuy', details[2]['retailer'])
        self.assertEqual(2, len(cursor.calls))
        self.assertIn('FROM public.ref_retail_com', cursor.calls[0][0])
        self.assertIn('FROM public.ldy_retail_com', cursor.calls[1][0])


if __name__ == '__main__':
    unittest.main()
