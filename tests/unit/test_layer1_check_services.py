import unittest
from unittest.mock import Mock, patch

from tests.unit.support import ScriptedCursor, load_module, module_stub, package_stub


class Layer1CheckServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = load_module(
            'apps/dx/dx_layer1/common/services.py',
            'layer1_check_services_under_test',
            {
                'apps': package_stub('apps'),
                'apps.common': package_stub('apps.common'),
                'apps.common.db': module_stub(
                    'apps.common.db',
                    dx_table=lambda name: 'test_' + name,
                ),
                'apps.common.monitoring_exclusions': module_stub(
                    'apps.common.monitoring_exclusions',
                    DISABLED_CHECK_TYPES=frozenset(),
                ),
            },
        )

    @staticmethod
    def _tse_section():
        return {
            'section': 'tse_retail',
            'status': 'OK',
            'memo': '',
            'details': [
                {
                    'category': 'TV', 'retailer': 'Homepro',
                    'expected_count': 300, 'actual_count': 300,
                    'rate': 100, 'status': 'OK',
                },
                {
                    'category': 'REF', 'retailer': 'Homepro',
                    'expected_count': 300, 'actual_count': 300,
                    'rate': 100, 'status': 'OK',
                },
                {
                    'category': 'LDY', 'retailer': 'Homepro',
                    'expected_count': 300, 'actual_count': 282,
                    'rate': 94, 'status': 'OK',
                },
            ],
        }

    def test_tse_first_confirmation_is_persisted_at_98_percent(self):
        cursor = ScriptedCursor([
            {},
            {'fetchone': (41,)},
        ])
        connection = Mock()

        result = self.service.save_check(
            cursor, connection, '2026-08-12', 1, 1,
            [self._tse_section()], 'tester',
        )

        self.assertIn('tse_retail', self.service.ALL_SECTIONS)
        self.assertTrue(result['success'])
        self.assertEqual(2, len(cursor.calls))
        insert_params = cursor.calls[1][1]
        self.assertEqual('tse_retail', insert_params[2])
        self.assertEqual((900, 882, 98), insert_params[3:6])
        connection.commit.assert_called_once_with()
        connection.rollback.assert_not_called()

    def test_tse_completion_is_allowed_at_98_percent(self):
        cursor = ScriptedCursor([
            {'fetchone': (0,)},
            {},
            {'fetchone': (41,)},
            {},
            {},
            {},
        ])
        connection = Mock()

        result = self.service.save_check(
            cursor, connection, '2026-08-12', 1, 2,
            [self._tse_section()], 'tester',
        )

        self.assertTrue(result['success'])
        self.assertEqual(6, len(cursor.calls))
        update_params = cursor.calls[1][1]
        self.assertEqual((900, 882, 98), update_params[:3])
        self.assertEqual('tse_retail', update_params[-1])
        connection.commit.assert_called_once_with()
        connection.rollback.assert_not_called()

    def test_siel_completion_is_allowed_below_100_percent(self):
        cursor = ScriptedCursor([
            {'fetchone': (0,)},
            {},
            {'fetchone': (42,)},
            {},
            {},
            {},
        ])
        connection = Mock()
        section = self._tse_section()
        section['section'] = 'siel_retail'

        result = self.service.save_check(
            cursor, connection, '2026-08-12', 1, 2,
            [section], 'tester',
        )

        self.assertIn('siel_retail', self.service.ALL_SECTIONS)
        self.assertTrue(result['success'])
        self.assertEqual('siel_retail', cursor.calls[1][1][-1])
        connection.commit.assert_called_once_with()
        connection.rollback.assert_not_called()

    @staticmethod
    def _seda_section():
        return {
            'section': 'seda_retail', 'status': 'OK',
            'details': [{
                'category': 'REF', 'retailer': 'Magalu',
                'expected_count': 300, 'actual_count': 294,
                'rate': 98, 'status': 'OK',
            }],
        }

    def test_seda_first_confirmation_is_persisted(self):
        cursor = ScriptedCursor([{}, {'fetchone': (43,)}])
        connection = Mock()

        result = self.service.save_check(
            cursor, connection, '2026-09-21', 1, 1,
            [self._seda_section()], 'tester',
        )

        self.assertTrue(result['success'])
        self.assertEqual(2, len(cursor.calls))
        self.assertIn('INSERT INTO test_monitoring_check_log', cursor.calls[1][0])
        self.assertEqual(('2026-09-21', 1, 'seda_retail', 300, 294, 98),
                         cursor.calls[1][1][:6])
        connection.commit.assert_called_once_with()
        connection.rollback.assert_not_called()

    def test_seda_completion_and_details_are_persisted_below_100_percent(self):
        cursor = ScriptedCursor([{'fetchone': (0,)}, {}, {'fetchone': (43,)}, {}])
        connection = Mock()

        result = self.service.save_check(
            cursor, connection, '2026-09-21', 1, 2,
            [self._seda_section()], 'tester',
        )

        self.assertTrue(result['success'])
        self.assertEqual(4, len(cursor.calls))
        self.assertIn('SET confirm_step = 2', cursor.calls[1][0])
        self.assertEqual((300, 294, 98), cursor.calls[1][1][:3])
        self.assertEqual(('2026-09-21', 1, 'seda_retail'), cursor.calls[1][1][-3:])
        self.assertIn('INSERT INTO test_monitoring_check_log_detail', cursor.calls[3][0])
        self.assertEqual((43, '2026-09-21', 1, 'seda_retail', 'REF', '', 'Magalu'),
                         cursor.calls[3][1][:7])
        connection.commit.assert_called_once_with()
        connection.rollback.assert_not_called()

    def test_seda_completion_still_blocks_unresolved_issues(self):
        cursor = ScriptedCursor([{'fetchone': (1,)}])
        connection = Mock()

        result = self.service.save_check(
            cursor, connection, '2026-09-21', 1, 2,
            [self._seda_section()], 'tester',
        )

        self.assertFalse(result['success'])
        self.assertIn('미해결 이슈 1건', result['error'])
        connection.rollback.assert_called_once_with()
        connection.commit.assert_not_called()

    def test_seda_saved_confirmation_steps_are_returned_for_inspection_date(self):
        for step in (1, 2):
            with self.subTest(step=step):
                cursor = ScriptedCursor([{'fetchall': [
                    (43, 'seda_retail', 300, 294, 98, 'OK', '', 'tester',
                     None, None, None, step),
                ]}])
                with patch.object(self.service, 'get_target_sections', return_value=1):
                    result = self.service.get_check_status(cursor, '2026-09-21', 1)
                self.assertEqual(step, result['sections']['seda_retail']['confirm_step'])
                self.assertEqual(('2026-09-21', 1), cursor.calls[0][1])

    def test_non_retail_section_still_requires_full_completion(self):
        cursor = ScriptedCursor([{'fetchone': (0,)}])
        connection = Mock()
        section = {
            'section': 'youtube',
            'status': 'WARNING',
            'details': [{
                'expected_count': 100,
                'actual_count': 99,
                'status': 'WARNING',
            }],
        }

        result = self.service.save_check(
            cursor, connection, '2026-08-12', 1, 2,
            [section], 'tester',
        )

        self.assertFalse(result['success'])
        self.assertIn('99%', result['error'])
        self.assertEqual(1, len(cursor.calls))
        connection.rollback.assert_called_once_with()
        connection.commit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
