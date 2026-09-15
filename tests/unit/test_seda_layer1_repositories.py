import unittest

from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.seda_retail import (
    SEDA_SOURCE_CONFIG,
    display_seda_retailer,
)
from apps.dx.dx_layer1.seda_retail import seda_retail_repositories as repo
from tests.unit.support import ScriptedCursor


class SedaLayer1RepositoryTests(unittest.TestCase):
    def test_exact_d_minus_one_source_query_uses_latest_main_batch(self):
        sql, params = repo.latest_main_counts_query('seda_tv', '2026-08-10')

        self.assertEqual(
            ['2026-08-10', 'magalu', 'casasbahia'], params
        )
        self.assertIn('FROM dx_seda.dx_seda_tv_retail_com', sql)
        self.assertIn('LEFT(BTRIM(crawl_strdatetime), 10) = %s', sql)
        self.assertIn("WHERE LOWER(BTRIM(page_type)) = 'main'", sql)
        self.assertIn("LOWER(REPLACE(BTRIM(account_name), ' ', ''))", sql)
        self.assertIn("')), id DESC", sql)
        self.assertIn('rows.batch_id IS NOT DISTINCT FROM latest.batch_id', sql)
        self.assertIn("WHERE LOWER(BTRIM(rows.page_type)) IN ('main', 'bsr')", sql)
        self.assertNotIn('::timestamp', sql)

    def test_history_uses_seven_positive_days_before_source_date(self):
        cursor = ScriptedCursor([{
            'fetchall': [('casasbahia', '2026-08-09', 300)],
        }])

        result = repo.get_previous_main_counts(
            cursor, 'seda_ref', '2026-08-10'
        )

        sql, params = cursor.calls[0]
        self.assertEqual(
            ['2026-08-10', 'magalu', 'casasbahia', 7],
            params,
        )
        self.assertIn('WHERE main_count > 0', sql)
        self.assertIn('WHERE day_rank <= %s', sql)
        self.assertEqual(300, result[0]['main_count'])

    def test_registry_and_retailer_aliases_match_reference_files(self):
        self.assertEqual('Casas Bahia', display_seda_retailer('CasasBahia'))
        self.assertEqual('Casas Bahia', display_seda_retailer('casas bahia'))
        for key in SEDA_SOURCE_CONFIG:
            mapping = resolve_monitoring_date('2026-08-11', 'SEDA', key)
            self.assertEqual('2026-08-10', mapping['source_date'])
            self.assertEqual(-1, mapping['offset_days'])

    def test_invalid_product_or_date_fails_before_query(self):
        for product, day in (
            ('tv', '2026-08-10'),
            ('seda_tv', '2026-02-30'),
        ):
            with self.subTest(product=product, day=day):
                with self.assertRaises(ValueError):
                    repo.latest_main_counts_query(product, day)


if __name__ == '__main__':
    unittest.main()
