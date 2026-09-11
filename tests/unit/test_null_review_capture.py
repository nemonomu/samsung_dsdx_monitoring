"""Integration contract between NULL confirmation and immutable evidence."""

import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from apps.common import null_review_evidence as evidence
from apps.common.inspection_dates import resolve_monitoring_date
from tests.unit.support import ScriptedCursor, load_module, module_stub
from tests.unit.test_layer2_sea_null_validation import common_stubs


class ReviewClock(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 9, 12, 10, 30, tzinfo=evidence.KOREA)
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)


class NullReviewCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stubs = common_stubs()
        stubs['apps.common.inspection_dates'] = module_stub(
            'apps.common.inspection_dates', resolve_monitoring_date=resolve_monitoring_date,
        )
        stubs['apps.common.null_review_evidence'] = evidence
        cls.service = load_module(
            'apps/dx/dx_layer2/null_validation/services.py',
            'null_review_capture_service_under_test', stubs,
        )

    def setUp(self):
        original_clock = evidence._korean_time
        fixed = ReviewClock.now(evidence.KOREA)
        clock = lambda value=None: fixed if value is None else original_clock(value)
        self.clock_patch = patch.object(self.service, 'datetime', ReviewClock)
        self.evidence_clock_patch = patch.object(evidence, '_korean_time', side_effect=clock)
        self.clock_patch.start()
        self.evidence_clock_patch.start()
        self.addCleanup(self.clock_patch.stop)
        self.addCleanup(self.evidence_clock_patch.stop)

    def save(self, cursor, conn, *, day='2026-09-12', kind='null'):
        return self.service.save_null_review(
            cursor, conn, 'public.ref_retail_com', 42, 'ref_capacity',
            'normal', '확인 메모', '상품페이지 내 항목 부재', day, kind, 'reviewer_a',
        )

    def test_save_commits_confirmation_and_server_snapshot_together(self):
        cursor = ScriptedCursor([
            {'fetchone': (None, 'Lowes', '000123')},
            {'fetchone': (42, '000123', 'Fridge A', None, 'Lowes')},
            {'fetchone': None},
            {'fetchone': (51,)},
            {'fetchone': (101,)},
        ])
        conn = Mock()
        result = self.save(cursor, conn)
        self.assertTrue(result['success'])
        self.assertTrue(result['supports_null_auto_review'])
        self.assertEqual(result['normal_review']['correction_id'], 51)
        self.assertEqual(result['normal_review']['evidence_id'], 101)
        self.assertEqual(result['normal_review']['auto_apply_from'], '2026-09-13')
        self.assertEqual(result['normal_review']['original_crawl_date'], '2026-09-12')
        self.assertIn('FOR UPDATE', cursor.calls[1][0])
        self.assertEqual(cursor.calls[1][1], (42, '2026-09-11'))
        self.assertIn('RETURNING id', cursor.calls[3][0])
        snapshot = dict(zip(evidence._EVIDENCE_COLUMNS[1:], cursor.calls[4][1]))
        self.assertEqual(snapshot['item'], '000123')
        self.assertEqual(snapshot['product_name'], 'Fridge A')
        self.assertEqual(snapshot['country'], 'SEA')
        self.assertEqual(snapshot['product_line'], 'REF')
        self.assertEqual(snapshot['value_snapshot'], '{"type": "null", "value": null}')
        conn.commit.assert_called_once_with()
        conn.rollback.assert_not_called()

    def test_snapshot_failure_rolls_back_the_confirmation_too(self):
        class FailedEvidenceCursor(ScriptedCursor):
            def execute(self, sql, params=None):
                if 'INSERT INTO public.monitoring_null_review_evidence' in sql:
                    raise RuntimeError('evidence store unavailable')
                super().execute(sql, params)
        cursor = FailedEvidenceCursor([
            {'fetchone': (None, 'Lowes', '000123')},
            {'fetchone': (42, '000123', 'Fridge A', None, 'Lowes')},
            {'fetchone': None},
            {'fetchone': (51,)},
        ])
        conn = Mock()
        with self.assertRaisesRegex(RuntimeError, 'evidence store unavailable'):
            self.save(cursor, conn)
        conn.commit.assert_not_called()
        conn.rollback.assert_called_once_with()

    def test_changed_or_resolved_value_is_not_confirmed(self):
        for value in ('160 L', ''):
            with self.subTest(value=value):
                cursor = ScriptedCursor([
                    {'fetchone': (None, 'Lowes', '000123')},
                    {'fetchone': (42, '000123', 'Fridge A', value, 'Lowes')},
                ])
                conn = Mock()
                result = self.save(cursor, conn)
                self.assertEqual(result['status_code'], 409)
                self.assertEqual(len(cursor.calls), 2)
                conn.commit.assert_not_called()
                conn.rollback.assert_called_once_with()

    def test_record_outside_inspection_source_date_cannot_be_confirmed(self):
        cursor = ScriptedCursor([
            {'fetchone': (None, 'Lowes', '000123')},
            {'fetchone': None},
        ])
        conn = Mock()
        self.assertEqual(self.save(cursor, conn)['status_code'], 409)
        conn.commit.assert_not_called()

    def test_changed_product_or_retailer_is_rejected_before_save(self):
        for item, retailer in (('another-item', 'Lowes'), ('000123', 'Bestbuy')):
            with self.subTest(item=item, retailer=retailer):
                cursor = ScriptedCursor([
                    {'fetchone': (None, 'Lowes', '000123')},
                    {'fetchone': (42, item, 'Fridge A', None, retailer)},
                ])
                conn = Mock()
                self.assertEqual(self.save(cursor, conn)['status_code'], 409)
                conn.commit.assert_not_called()
                conn.rollback.assert_called_once_with()

    def test_legacy_date_and_non_null_reviews_keep_existing_storage(self):
        for day, kind in (('2026-09-11', 'null'), ('2026-09-12', 'format')):
            with self.subTest(day=day, kind=kind):
                cursor = ScriptedCursor([
                    {'fetchone': (None, 'Lowes', '000123')},
                    {'fetchone': None},
                    {'rowcount': 1},
                ])
                conn = Mock()
                self.assertEqual(self.save(cursor, conn, day=day, kind=kind),
                                 {'success': True, 'status': 'normal'})
                self.assertEqual(len(cursor.calls), 3)
                self.assertTrue(all('monitoring_null_review_evidence' not in sql
                                    for sql, _ in cursor.calls))
                conn.commit.assert_called_once_with()

    def test_future_inspection_date_is_rejected_before_insert(self):
        cursor = ScriptedCursor([{'fetchone': (None, 'Lowes', '000123')}])
        conn = Mock()
        result = self.save(cursor, conn, day='2026-09-13')
        self.assertEqual(result['status_code'], 400)
        self.assertIn('미래', result['error'])
        conn.commit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
