import unittest
from contextlib import contextmanager
from datetime import date

from tests.unit.support import ScriptedCursor, load_module, module_stub, package_stub


class Layer4RedirectStatusTests(unittest.TestCase):
    def test_null_metrics_exclude_redirect_but_return_email_count(self):
        cursor = ScriptedCursor([
            {'fetchone': (248, 0, 0, 0)},
            {'fetchone': (2,)},
        ])

        @contextmanager
        def connection():
            yield object(), cursor

        condition = "NOT (account_name = 'Amazon' AND redirect IS TRUE)"
        stubs = {
            'apps': package_stub('apps'),
            'apps.common': package_stub('apps.common'),
            'apps.common.db': module_stub(
                'apps.common.db',
                dx_connection=connection,
                dx_table=lambda table: table,
            ),
            'apps.common.retail_columns': module_stub(
                'apps.common.retail_columns',
                load_retail_columns=lambda: {'tv': {'Amazon': ['item']}},
            ),
            'apps.common.retail_validation': module_stub(
                'apps.common.retail_validation',
                get_tv_validation_condition=lambda alias=None: condition,
            ),
            'config': package_stub('config'),
            'config.config': module_stub(
                'config.config', EMAIL_CONFIG={},
            ),
        }
        service = load_module(
            'apps/dx/dx_layer4/collection_status/services.py',
            'layer4_redirect_status_under_test',
            stubs,
        )

        result = service.get_collection_status(date(2026, 7, 30), 'tv')

        amazon = result['retailers'][0]
        self.assertEqual(248, amazon['total_count'])
        self.assertEqual(2, amazon['redirect_true_count'])
        self.assertEqual(248, amazon['columns'][0]['total_count'])
        self.assertIn(condition, cursor.calls[0][0])
        self.assertIn('redirect IS TRUE', cursor.calls[1][0])
        self.assertNotIn(condition, cursor.calls[1][0])


if __name__ == '__main__':
    unittest.main()
