import unittest

from tests.unit.support import ScriptedCursor, load_module


class SeaLayer1RepositoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = load_module(
            'apps/dx/dx_layer1/retail/retail_repositories.py',
            'tests._sea_layer1_repositories_under_test',
        )

    def test_all_tv_paths_use_exact_crawl_datetime_half_open_range(self):
        count_cursor = ScriptedCursor([{'fetchall': []}])
        self.repo.query_retail_counts(
            count_cursor,
            'public.tv_retail_com',
            'crawl_datetime::timestamp',
            'promotion_position',
            '2026-08-19 00:00:00',
            '2026-08-20 00:00:00',
        )

        retailer_cursor = ScriptedCursor([{'fetchone': (1, 2, 3, 4)}])
        self.repo.query_retail_counts_by_retailer(
            retailer_cursor,
            'public.tv_retail_com',
            'crawl_datetime::timestamp',
            'promotion_position',
            '2026-08-19 00:00:00',
            '2026-08-20 00:00:00',
            'Amazon',
        )

        detail_cursor = ScriptedCursor([{'fetchall': []}])
        self.repo.get_tv_retail_detail_list(detail_cursor, '2026-08-19')

        null_cursor = ScriptedCursor([{'fetchone': (1,)}])
        self.repo.get_retail_summary_null_counts(
            null_cursor,
            'public.tv_retail_com',
            'crawl_datetime::timestamp',
            ['item'],
            '2026-08-19 00:00:00',
            '2026-08-20 00:00:00',
            'Amazon',
            False,
        )

        raw_cursor = ScriptedCursor([{'fetchall': []}])
        self.repo.get_retailer_raw_data_list(
            raw_cursor,
            'public.tv_retail_com',
            ['id'],
            'Amazon',
            'crawl_datetime',
            '2026-08-19 00:00:00',
            '2026-08-20 00:00:00',
        )

        calls = [
            count_cursor.calls[0], retailer_cursor.calls[0],
            detail_cursor.calls[0], null_cursor.calls[0],
            raw_cursor.calls[0],
        ]
        for sql, _params in calls:
            self.assertIn('crawl_datetime::timestamp', sql)
            self.assertIn('>=', sql)
            self.assertIn('<', sql)
            self.assertNotIn('batch_id', sql)

        self.assertEqual(
            ('2026-08-19 00:00:00', '2026-08-20 00:00:00'),
            count_cursor.calls[0][1],
        )
        self.assertEqual(
            (
                '2026-08-19 00:00:00',
                '2026-08-20 00:00:00',
                'Amazon',
            ),
            retailer_cursor.calls[0][1],
        )

    def test_tv_collection_is_inclusive_but_null_scope_excludes_redirect(self):
        count_cursor = ScriptedCursor([{'fetchone': (1, 2, 3, 250)}])
        self.repo.query_retail_counts_by_retailer(
            count_cursor,
            'public.tv_retail_com',
            'crawl_datetime::timestamp',
            'promotion_position',
            '2026-08-19 00:00:00',
            '2026-08-20 00:00:00',
            'Amazon',
        )
        null_cursor = ScriptedCursor([{'fetchone': (248,)}])
        self.repo.get_retail_summary_null_counts(
            null_cursor,
            'public.tv_retail_com',
            'crawl_datetime::timestamp',
            ['item'],
            '2026-08-19 00:00:00',
            '2026-08-20 00:00:00',
            'Amazon',
            False,
        )

        self.assertNotIn('redirect IS TRUE', count_cursor.calls[0][0])
        self.assertIn('redirect IS TRUE', null_cursor.calls[0][0])

    def test_appliance_uses_latest_exact_date_main_anchor_and_same_batch(self):
        cursor = ScriptedCursor([
            {'fetchone': ('b_20260819_180008',)},
            {'fetchone': (300, 2, 0, 302)},
        ])

        result = self.repo.query_appliance_counts_by_retailer(
            cursor,
            'public.ref_retail_com',
            'crawl_strdatetime',
            '2026-08-19',
            'Bestbuy',
        )

        self.assertEqual((300, 2, 0, 302, 'b_20260819_180008'), result)
        anchor_sql, anchor_params = cursor.calls[0]
        self.assertIn(
            'LEFT(BTRIM(CAST(crawl_strdatetime AS TEXT)), 10) = %s',
            anchor_sql,
        )
        self.assertIn("page_type AS TEXT))) = 'main'", anchor_sql)
        self.assertIn('ORDER BY id DESC LIMIT 1', anchor_sql)
        self.assertEqual(('2026-08-19', 'Bestbuy'), anchor_params)

        count_sql, count_params = cursor.calls[1]
        self.assertIn('batch_id IS NOT DISTINCT FROM %s', count_sql)
        self.assertIn("IN ('main', 'bsr')", count_sql)
        self.assertIn(
            'LEFT(BTRIM(CAST(crawl_strdatetime AS TEXT)), 10) = %s',
            count_sql,
        )
        self.assertEqual(
            ('2026-08-19', 'Bestbuy', 'b_20260819_180008'),
            count_params,
        )

    def test_appliance_without_exact_date_main_anchor_is_zero_no_fallback(self):
        cursor = ScriptedCursor([{'fetchone': None}])

        result = self.repo.query_appliance_counts_by_retailer(
            cursor,
            'public.ldy_retail_com',
            'crawl_strdatetime',
            '2026-08-19',
            'Lowes',
        )

        self.assertEqual((0, 0, 0, 0, None), result)
        self.assertEqual(1, len(cursor.calls))
        sql, params = cursor.calls[0]
        self.assertEqual(('2026-08-19', 'Lowes'), params)
        self.assertNotIn('MAX(', sql.upper())
        self.assertNotIn('CURRENT_DATE', sql.upper())

    def test_appliance_detail_and_raw_stay_in_anchor_main_bsr_scope(self):
        detail_cursor = ScriptedCursor([
            {'fetchone': ('l_260819_190923',)},
            {'fetchone': (190, 182, 8, 180)},
        ])
        detail = self.repo.get_appliance_retail_detail_list(
            detail_cursor,
            'public.ldy_retail_com',
            'crawl_strdatetime',
            '2026-08-19',
            ('Lowes',),
        )
        self.assertEqual(
            [('Lowes', 190, 182, 8, 180, 'l_260819_190923')],
            detail,
        )
        self.assertIn(
            "IN ('main', 'bsr')", detail_cursor.calls[1][0]
        )

        raw_cursor = ScriptedCursor([
            {'fetchone': ('l_260819_190923',)},
            {'fetchall': [(1, 'Lowes')]},
        ])
        rows = self.repo.get_appliance_raw_data_list(
            raw_cursor,
            'public.ldy_retail_com',
            ['id', 'account_name'],
            'Lowes',
            'crawl_strdatetime',
            '2026-08-19',
        )
        self.assertEqual([(1, 'Lowes')], rows)
        self.assertIn('batch_id IS NOT DISTINCT FROM %s', raw_cursor.calls[1][0])
        self.assertIn("IN ('main', 'bsr')", raw_cursor.calls[1][0])


if __name__ == '__main__':
    unittest.main()
