import unittest

from apps.common.retail_validation import (
    apply_tv_validation_scope,
    get_tv_validation_condition,
)
from tests.unit.support import ScriptedCursor, load_module


class RedirectScopeTests(unittest.TestCase):
    def test_condition_excludes_only_amazon_true(self):
        condition = get_tv_validation_condition()

        self.assertEqual(
            "NOT (account_name = 'Amazon' AND redirect IS TRUE)",
            condition,
        )
        self.assertNotIn('redirect = FALSE', condition)
        self.assertEqual(
            "NOT (r.account_name = 'Amazon' AND r.redirect IS TRUE)",
            get_tv_validation_condition('r'),
        )

    def test_plain_select_is_scoped_with_cte(self):
        query = 'SELECT id FROM tv_retail_com WHERE DATE(crawl_datetime) = %s'

        scoped = apply_tv_validation_scope(query, 'tv_retail_com')

        self.assertTrue(scoped.startswith('WITH tv_retail_com AS'))
        self.assertIn('FROM public.tv_retail_com', scoped)
        self.assertIn('redirect IS TRUE', scoped)
        self.assertTrue(scoped.rstrip().endswith(query))

    def test_existing_with_query_scopes_all_table_reads(self):
        query = (
            'WITH today_prices AS (SELECT * FROM tv_retail_com), '
            'hist_prices AS (SELECT * FROM tv_retail_com) '
            'SELECT * FROM today_prices'
        )

        scoped = apply_tv_validation_scope(query, 'tv_retail_com')

        self.assertEqual(1, scoped.count('FROM public.tv_retail_com'))
        self.assertIn('), today_prices AS', scoped)
        self.assertEqual(2, scoped.count('FROM tv_retail_com'))

    def test_non_tv_query_is_unchanged(self):
        query = 'SELECT * FROM market_trend'
        self.assertEqual(query, apply_tv_validation_scope(query, 'market_trend'))


class Layer1RedirectScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = load_module(
            'apps/dx/dx_layer1/retail/retail_repositories.py',
            'layer1_retail_redirect_repo_under_test',
        )

    def test_collection_count_stays_inclusive_but_null_check_is_scoped(self):
        count_cursor = ScriptedCursor([{'fetchone': (1, 2, 3, 250)}])
        self.repo.query_retail_counts_by_retailer(
            count_cursor, 'tv_retail_com', 'crawl_datetime',
            'promotion_position', '2026-07-30 00:00:00',
            '2026-07-31 00:00:00', 'Amazon',
        )
        count_sql = count_cursor.calls[0][0]

        null_cursor = ScriptedCursor([{'fetchone': (248,)}])
        self.repo.get_retail_summary_null_counts(
            null_cursor, 'tv_retail_com', 'crawl_datetime', ['item'],
            '2026-07-30 00:00:00', '2026-07-31 00:00:00',
            'Amazon', True,
        )
        null_sql = null_cursor.calls[0][0]

        self.assertNotIn('redirect IS TRUE', count_sql)
        self.assertIn('redirect IS TRUE', null_sql)


if __name__ == '__main__':
    unittest.main()
