import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from tests.unit.support import ScriptedCursor, load_module, module_stub


def load_service(cursor, connection=None):
    @contextmanager
    def dx_connection():
        yield connection or object(), cursor

    return load_module(
        'apps/dx/dx_layer4/corrections/services.py',
        'layer4_tse_corrections_under_test',
        stubs={
            'apps.common.db': module_stub(
                'apps.common.db',
                dx_connection=dx_connection,
            ),
            'apps.common.retail_columns': module_stub(
                'apps.common.retail_columns',
                get_retailer_columns=lambda *args: [],
                load_retail_columns=lambda: {},
                get_tse_retailer_columns=lambda product_line: {
                    'Homepro': {
                        'retailer': 'homepro',
                        'required_columns': ['country', 'item', 'product_url'],
                        'editable_columns': ['final_sku_price'],
                    }
                },
            ),
        },
    )


class Layer4TseCorrectionTests(unittest.TestCase):
    def test_cancel_revokes_only_changed_records_before_commit(self):
        cursor = ScriptedCursor([{'fetchall': [(11,), (12,)], 'rowcount': 2}])
        events = []
        connection = Mock()
        connection.commit.side_effect = lambda: events.append('commit')
        revoke = Mock(side_effect=lambda *_args, **_kwargs: events.append('revoke'))
        service = load_service(cursor, connection)
        module_name = 'apps.common.null_review_evidence'

        with patch.dict('sys.modules', {
            module_name: module_stub(module_name, revoke_evidence=revoke),
        }):
            result = service.cancel_corrections([11, 12, 13], '재검수 필요', 'reviewer')

        self.assertEqual({'success': True, 'cancelled': 2}, result)
        revoke.assert_called_once_with(
            cursor, [11, 12], reviewer='reviewer', memo='재검수 필요',
        )
        self.assertEqual(['revoke', 'commit'], events)
        self.assertIn("AND status = 'normal' RETURNING id", cursor.calls[0][0])

    def test_cancel_does_not_commit_if_evidence_revoke_fails(self):
        cursor = ScriptedCursor([{'fetchall': [(11,)], 'rowcount': 1}])
        connection = Mock()
        service = load_service(cursor, connection)
        module_name = 'apps.common.null_review_evidence'
        revoke = Mock(side_effect=RuntimeError('revocation failed'))

        with patch.dict('sys.modules', {
            module_name: module_stub(module_name, revoke_evidence=revoke),
        }), self.assertRaisesRegex(RuntimeError, 'revocation failed'):
            service.cancel_corrections([11], '재검수', 'reviewer')

        connection.commit.assert_not_called()

    def test_cancel_with_no_changed_records_does_not_revoke_evidence(self):
        cursor = ScriptedCursor([{'fetchall': [], 'rowcount': 0}])
        connection = Mock()
        service = load_service(cursor, connection)
        module_name = 'apps.common.null_review_evidence'
        revoke = Mock()

        with patch.dict('sys.modules', {
            module_name: module_stub(module_name, revoke_evidence=revoke),
        }):
            result = service.cancel_corrections([11], '', 'reviewer')

        self.assertEqual(0, result['cancelled'])
        revoke.assert_not_called()
        connection.commit.assert_called_once_with()

    def test_cancel_empty_selection_does_not_open_a_connection(self):
        service = load_service(ScriptedCursor([]))
        with patch.object(service, 'dx_connection') as connection:
            result = service.cancel_corrections([], '', 'reviewer')
        self.assertEqual({'success': True, 'cancelled': 0}, result)
        connection.assert_not_called()

    def test_tse_tables_are_supported_for_crawl_time_and_history(self):
        cursor = ScriptedCursor([
            {
                'description': [
                    ('id',),
                    ('crawl_datetime',),
                    ('item',),
                    ('country',),
                    ('final_sku_price',),
                    ('product_url',),
                ],
                'fetchall': [
                    (1, '2026-08-10T09:58:03+09:00', 'A1', 'TSE', '฿9,990', 'https://example.invalid'),
                ],
            },
        ])
        service = load_service(cursor)
        table_name = 'dx_tse.dx_tse_tv_retail_com'

        result = service.get_history(
            table_name, 'Homepro', 'A1', 'final_sku_price', 3, 1
        )

        self.assertIn(table_name, service._CRAWL_TIME_COLUMN)
        self.assertIn(table_name, service._HISTORY_TABLES)
        self.assertEqual(result['rows'][0]['final_sku_price'], '฿9,990')
        sql, params = cursor.calls[0]
        self.assertIn('FROM dx_tse.dx_tse_tv_retail_com', sql)
        self.assertIn('LEFT(TRIM(crawl_datetime), 10) >= %s', sql)
        self.assertEqual(params[0:2], ('Homepro', 'A1'))

    def test_bulk_history_rejects_unknown_category(self):
        service = load_service(ScriptedCursor([]))
        with self.assertRaises(ValueError):
            service.get_bulk_history('2026-08-10', category='unknown')

    def test_bulk_history_preserves_existing_default_and_hhp_contracts(self):
        cursor = ScriptedCursor([{'fetchall': []}])
        service = load_service(cursor)

        default_result = service.get_bulk_history('2026-08-10')
        hhp_result = service.get_bulk_history('2026-08-10', category='hhp')

        self.assertEqual(default_result['rows'], [])
        self.assertEqual(hhp_result['rows'], [])
        self.assertIn('table_name IN (%s)', cursor.calls[0][0])
        self.assertIn('tv_retail_com', cursor.calls[0][1])


if __name__ == '__main__':
    unittest.main()
