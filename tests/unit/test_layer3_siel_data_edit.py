import unittest

from apps.common import (
    inspection_dates,
    retail_validation,
    sea_retail,
    seg_retail,
    siel_retail,
    tse_retail,
)
from tests.unit.support import (
    ScriptedCursor,
    load_module,
    module_stub,
    package_stub,
)


services = load_module(
    'apps/dx/dx_layer3/data_edit/services.py',
    'layer3_siel_data_edit_service_under_test',
    {
        'apps': package_stub('apps'),
        'apps.common': package_stub('apps.common'),
        'apps.common.monitoring_exclusions': module_stub(
            'apps.common.monitoring_exclusions',
            DISABLED_SOURCE_TABLES=frozenset(),
        ),
        'apps.common.retail_columns': module_stub(
            'apps.common.retail_columns',
            get_editable_columns=lambda *_: [],
        ),
        'apps.common.inspection_dates': inspection_dates,
        'apps.common.retail_validation': retail_validation,
        'apps.common.sea_retail': sea_retail,
        'apps.common.siel_retail': siel_retail,
        'apps.common.seg_retail': seg_retail,
        'apps.common.tse_retail': tse_retail,
    },
)


class FakeConnection:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class SielLayer3DataEditTests(unittest.TestCase):
    table_name = 'dx_siel.dx_siel_tv_retail_com'

    def test_siel_tables_are_exactly_allowlisted(self):
        self.assertIn(self.table_name, services.VALID_TABLES_UPDATE)
        self.assertIn(
            'dx_siel.dx_siel_ref_retail_com',
            services.VALID_TABLES_UPDATE,
        )
        self.assertIn(
            'dx_siel.dx_siel_ldy_retail_com',
            services.VALID_TABLES_UPDATE,
        )
        self.assertNotIn(
            'dx_siel.any_retail_com', services.VALID_TABLES_UPDATE
        )

    def test_update_uses_kst_same_day_latest_batch_and_redirect_scope(self):
        cursor = ScriptedCursor([
            {'fetchone': ('5.5', None, 'Amazon', 'A-1')},
            {},
            {},
        ])
        conn = FakeConnection()

        result = services.update_cell_value(
            cursor, conn, self.table_name, 20, 'star_rating', '4.5',
            '2026-09-03', 'cross_field', 'tester', '별점 수정', 71,
        )

        self.assertTrue(result['success'])
        source_sql, source_params = cursor.calls[0]
        self.assertIn('FROM dx_siel.dx_siel_tv_retail_com source', source_sql)
        self.assertIn("AT TIME ZONE 'Asia/Seoul'", source_sql)
        self.assertIn(
            'source.batch_id IS NOT DISTINCT FROM', source_sql
        )
        self.assertIn(
            "NOT (source.account_name = 'Amazon' AND source.redirect IS TRUE)",
            source_sql,
        )
        self.assertEqual(
            (20, '2026-09-03', '2026-09-03',
             '2026-09-03', '2026-09-03'),
            source_params,
        )
        history_params = cursor.calls[2][1]
        self.assertEqual(3, history_params[0])
        self.assertEqual('2026-09-03', history_params[7])
        self.assertEqual(71, history_params[-1])
        self.assertEqual(1, conn.commits)

    def test_siel_normal_review_allows_empty_memo(self):
        cursor = ScriptedCursor([
            {'fetchone': (None, 'Flipkart', 'F-1')},
            {'fetchone': None},
            {},
        ])
        conn = FakeConnection()

        result = services.save_review(
            cursor, conn, self.table_name, 20,
            'count_of_star_ratings', 'normal', '', '정상 데이터',
            '2026-09-03', 'cross_field', 'tester', 72,
        )

        self.assertTrue(result['success'])
        self.assertIsNone(cursor.calls[2][1][11])
        self.assertEqual('정상 데이터', cursor.calls[2][1][12])
        self.assertEqual(1, conn.commits)

    def test_siel_crossfield_confirmation_does_not_require_edit_config(self):
        cursor = ScriptedCursor([
            {'fetchone': (None, 'Flipkart', 'F-1')},
            {'fetchone': None},
            {},
        ])
        conn = FakeConnection()

        result = services.save_review(
            cursor, conn, self.table_name, 20,
            'count_of_star_ratings', 'normal', '수집원 확인 완료',
            '정상 데이터', '2026-09-03', 'cross_field', 'tester', 72,
        )

        self.assertTrue(result['success'])
        self.assertEqual(1, conn.commits)
        history_params = cursor.calls[2][1]
        self.assertEqual('수집원 확인 완료', history_params[11])
        self.assertEqual(72, history_params[-1])

    def test_siel_crossfield_confirmation_rejects_unrelated_column(self):
        cursor = ScriptedCursor([
            {'fetchone': ('A-1', 'Flipkart', 'F-1')},
        ])

        result = services.save_review(
            cursor, FakeConnection(), self.table_name, 20,
            'item', 'normal', '확인 완료', '정상 데이터',
            '2026-09-03', 'cross_field', 'tester', 72,
        )

        self.assertEqual(403, result['status'])
        self.assertIn('정상 확인할 수 없습니다', result['error'])

    def test_seg_price_cell_uses_latest_batch_and_redirect_scope(self):
        cursor = ScriptedCursor([
            {'fetchone': ('899,99€', 'a_20260909', 'Amazon', 'A-1')},
            {},
            {},
        ])
        conn = FakeConnection()
        table = 'dx_seg.dx_seg_tv_retail_com'

        result = services.update_cell_value(
            cursor, conn, table, 1, 'final_sku_price', '899,00€',
            '2026-09-09', 'cross_field', 'tester', '가격 수정', 101,
        )

        self.assertTrue(result['success'])
        source_sql, source_params = cursor.calls[0]
        self.assertIn(f'FROM {table} source', source_sql)
        self.assertIn('source.redirect IS NOT TRUE', source_sql)
        self.assertIn('source.batch_id IS NOT DISTINCT FROM', source_sql)
        self.assertEqual(
            (1, '2026-09-09', 'SEG', '2026-09-09'), source_params,
        )
        self.assertIn(
            f'UPDATE {table} SET final_sku_price = %s',
            cursor.calls[1][0],
        )
        self.assertEqual(1, conn.commits)


if __name__ == '__main__':
    unittest.main()
