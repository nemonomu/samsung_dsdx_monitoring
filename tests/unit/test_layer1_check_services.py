import unittest
from unittest.mock import Mock

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
