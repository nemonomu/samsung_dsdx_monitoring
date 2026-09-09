import unittest

from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.seg_retail import SEG_SOURCE_CONFIG
from apps.dx.dx_layer1.seg_retail import seg_retail_repositories as repo
from tests.unit.support import ScriptedCursor


class SegLayer1RepositoryTests(unittest.TestCase):
    def test_history_uses_seven_positive_days_per_retailer_excluding_today(self):
        cursor = ScriptedCursor([{'fetchall': [('otto', '2026-09-08', 301)]}])
        result = repo.get_previous_main_counts(cursor, 'seg_ldy', '2026-09-09')
        sql, params = cursor.calls[0]
        self.assertEqual(['2026-09-09', 'mediamarkt', 'otto', 7], params)
        self.assertIn('LEFT(BTRIM(crawl_strdatetime), 10) < %s', sql)
        self.assertIn('HAVING COUNT(rows.main_rank) > 0', sql)
        self.assertIn('PARTITION BY retailer ORDER BY source_date DESC', sql)
        self.assertIn('WHERE day_rank <= %s', sql)
        self.assertIn('rows.source_date = latest.source_date', sql)
        self.assertIn("WHERE page_type = 'main'", sql)
        self.assertNotIn('INTERVAL', sql)
        self.assertEqual(301, result[0]['main_count'])

    def test_dated_latest_main_anchor_and_rank_coverage(self):
        sql, params = repo.latest_main_counts_query('seg_tv', '2026-08-11')
        self.assertEqual(['2026-08-11', 'mediamarkt', 'otto', 'amazon'], params)
        self.assertIn('LEFT(BTRIM(crawl_strdatetime), 10) = %s', sql)
        self.assertIn("WHERE LOWER(BTRIM(page_type)) = 'main'", sql)
        self.assertIn('ORDER BY LOWER(BTRIM(account_name)), id DESC', sql)
        self.assertIn('rows.batch_id IS NOT DISTINCT FROM latest.batch_id', sql)
        self.assertIn("WHERE LOWER(BTRIM(rows.page_type)) IN ('main', 'bsr')", sql)
        self.assertIn('COUNT(rows.main_rank)', sql)
        self.assertIn('COUNT(rows.bsr_rank)', sql)
        self.assertIn('COUNT(*) AS actual_count', sql)
        self.assertNotIn('::timestamp', sql)

    def test_ldy_has_no_amazon_or_redirect_column_reference(self):
        sql, params = repo.latest_main_counts_query('seg_ldy', '2026-08-11')
        self.assertEqual(['2026-08-11', 'mediamarkt', 'otto'], params)
        self.assertNotIn('rows.redirect', sql)
        self.assertNotIn(', redirect', sql)
        self.assertIn('0 AS redirect_count', sql)
        self.assertEqual(('Mediamarkt', 'OTTO'), SEG_SOURCE_CONFIG['seg_ldy']['retailers'])

    def test_overlap_counts_do_not_replace_physical_count(self):
        cursor = ScriptedCursor([{'fetchall': [
            ('Mediamarkt', 'batch-1', 301, 300, 100, 0),
            ('Amazon', 'batch-2', 334, 294, 100, 2),
        ]}])
        result = repo.get_latest_main_batch_counts(cursor, 'seg_tv', '2026-08-11')
        self.assertEqual(301, result[0]['actual_count'])
        self.assertEqual(300, result[0]['main_count'])
        self.assertEqual(100, result[0]['bsr_count'])
        self.assertEqual(2, result[1]['redirect_count'])
        self.assertEqual(334, result[1]['actual_count'])

    def test_empty_day_has_no_recent_date_fallback(self):
        cursor = ScriptedCursor([{'fetchall': []}])
        self.assertEqual([], repo.get_latest_main_batch_counts(
            cursor, 'seg_ref', '2026-08-12',
        ))
        self.assertEqual(1, len(cursor.calls))
        self.assertEqual('2026-08-12', cursor.calls[0][1][0])

    def test_allowlist_and_date_validation_before_query(self):
        for product, day in [('tv', '2026-08-11'), ('seg_tv', '2026-02-30')]:
            with self.subTest(product=product, day=day):
                with self.assertRaises(ValueError):
                    repo.latest_main_counts_query(product, day)
        for key in SEG_SOURCE_CONFIG:
            self.assertEqual('2026-08-11', resolve_monitoring_date(
                '2026-08-11', 'SEG', key,
            )['source_date'])


if __name__ == '__main__':
    unittest.main()
