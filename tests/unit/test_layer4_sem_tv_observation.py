import unittest
from contextlib import contextmanager
from datetime import date
from unittest.mock import Mock, patch

from apps.dx.dx_layer3.cross_field import sem_services as cross_field
from apps.dx.dx_layer4.collection_status import email_services, services
from apps.dx.dx_layer4.report import services as report
from tests.unit.support import ScriptedCursor


START = date(2026, 11, 27)
BEFORE_START = date(2026, 11, 26)


class Layer4SemTvObservationTests(unittest.TestCase):
    def test_collection_status_and_detail_use_same_latest_batch_and_required_fields(self):
        description = [(name,) for name in ('id', 'account_name', 'item', 'final_sku_price', 'sku')]
        cursor = ScriptedCursor([
            {'description': description, 'fetchall': []},
            {'description': description, 'fetchall': [(1, 'Walmart', '001', '', None)]},
            {'description': description, 'fetchall': [(2, "Sam's Club", '002', None, None)]},
            {'description': description, 'fetchall': [(2, "Sam's Club", '002', None, None)]},
        ])

        @contextmanager
        def connection():
            yield Mock(), cursor

        with patch.object(services, 'dx_connection', connection):
            status = services.get_collection_status(START, 'sem_tv')
            detail = services.get_null_detail(START, 'sem_tv', "sAM's club", 'final_sku_price')
            before = services.get_null_detail(BEFORE_START, 'sem_tv', "Sam's Club", 'final_sku_price')
            with self.assertRaises(ValueError):
                services.get_null_detail(START, 'sem_tv', 'Walmart', 'sku')

        self.assertEqual(['Liverpool', 'Walmart', "Sam's Club"], [row['retailer'] for row in status['retailers']])
        self.assertEqual('2026-11-27', status['source_date'])
        seller = status['retailers'][2]
        self.assertEqual(1, next(field['null_count'] for field in seller['columns']
                                 if field['column'] == 'final_sku_price'))
        self.assertNotIn('sku', [field['column'] for field in seller['columns']])
        self.assertEqual([2], [row['id'] for row in detail['rows']])
        self.assertTrue(detail['read_only'])
        self.assertFalse(before['rows'])
        self.assertEqual(4, len(cursor.calls))
        self.assertIn("NULLIF(BTRIM(batch_id), '') IS NOT NULL", cursor.calls[3][0])
        self.assertEqual(('2026-11-27', "Sam's Club", '2026-11-27'), cursor.calls[3][1])

    def test_internal_email_preview_is_separate_from_existing_send_report(self):
        with patch.object(email_services, '_sem_tv_observation_preview', return_value={'retailers': []}) as preview:
            external = email_services.get_email_report_data(START, sources=[])
            preview.assert_not_called()
            internal = email_services.get_email_report_data(START, sources=[], include_sem_tv_preview=True)
            preview.assert_called_once_with(START)
        self.assertNotIn('sem_tv_preview', external)
        self.assertEqual({'retailers': []}, internal['sem_tv_preview'])
        self.assertEqual(external['sources'], internal['sources'])
        self.assertEqual(external['complete'], internal['complete'])

    def test_report_uses_cross_field_counts_without_creating_corrections(self):
        summary = {
            'source_date': str(START),
            'rule_summary': [{'retailer_checks': {'Walmart': {}}},
                             {'retailer_checks': {"Sam's Club": {}}}],
            'retailer_checks': {'Walmart': {'received': 9, 'checked': 6, 'failed': 1, 'review_count': 2},
                                "Sam's Club": {'received': 0, 'checked': 0, 'failed': 0, 'review_count': 0}},
        }
        connection, cursor = Mock(), Mock()

        @contextmanager
        def connect():
            yield connection, cursor

        with patch.object(report, 'dx_connection', connect), \
                patch.object(cross_field, 'get_sem_cross_field_summary', return_value=summary) as load:
            self.assertIsNone(report._sem_tv_observation_summary(BEFORE_START))
            load.assert_not_called()
            result = report._sem_tv_observation_summary(START)
        load.assert_called_once_with(cursor, START, 'sem_tv')
        connection.set_session.assert_called_once_with(readonly=True)
        self.assertEqual('2026-11-27', result['source_date'])
        self.assertEqual([1, 0], [row['failed'] for row in result['retailers']])
        self.assertEqual([2, 0], [row['review_count'] for row in result['retailers']])
        self.assertEqual(2, result['rule_count'])
