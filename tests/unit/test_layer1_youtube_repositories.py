import unittest

from tests.unit.support import ScriptedCursor, load_module


class YouTubeRepositoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = load_module(
            'apps/dx/dx_layer1/youtube/youtube_repositories.py',
            'youtube_repositories_under_test',
        )

    def test_today_uses_latest_country_runs_and_completed_keywords(self):
        expected_row = ('HHP', 240, 240, 841, 40938, 10, 10)
        cursor = ScriptedCursor([{'fetchall': [expected_row]}])

        rows = self.repo.get_youtube_today(cursor, '2026-07-29')

        self.assertEqual([expected_row], rows)
        sql, params = cursor.calls[0]
        self.assertIn('youtube_country_collection_runs', sql)
        self.assertIn('PARTITION BY r.collection_country', sql)
        self.assertIn('WHERE row_num = 1', sql)
        self.assertIn("status = 'completed'", sql)
        self.assertNotIn('youtube_collection_logs', sql)
        self.assertEqual(('2026-07-29',), params)

    def test_expected_excludes_legacy_group_and_reports_unique_keywords(self):
        cursor = ScriptedCursor([{'fetchall': [('HHP', 240, 10, 24, 24)]}])

        result = self.repo.get_youtube_expected(cursor)

        self.assertEqual(240, result['HHP']['expected_jobs'])
        self.assertEqual(10, result['HHP']['expected_countries'])
        self.assertEqual(24, result['HHP']['keywords_per_country_min'])
        self.assertEqual(24, result['HHP']['keywords_per_country_max'])
        sql, params = cursor.calls[0]
        self.assertIn("collection_group = 'hhp_10_country'", sql)
        self.assertIn("category = 'HHP'", sql)
        self.assertIn('SUM(distinct_keyword_count)', sql)
        self.assertNotIn('SUM(job_count)', sql)
        self.assertNotIn('legacy_us', sql)
        self.assertIsNone(params)

    def test_video_rows_are_scoped_by_country_batch_and_keep_real_total(self):
        sample_row = ('US', 'batch-1', 'video-1')
        cursor = ScriptedCursor([
            {'fetchall': [sample_row]},
            {'fetchone': (841,)},
        ])

        columns, rows, total = self.repo.get_youtube_videos(
            cursor, '2026-07-29', 'HHP'
        )

        self.assertEqual('collection_country', columns[0])
        self.assertEqual([sample_row], rows)
        self.assertEqual(841, total)
        self.assertEqual(2, len(cursor.calls))
        list_sql, list_params = cursor.calls[0]
        count_sql, count_params = cursor.calls[1]
        for sql in (list_sql, count_sql):
            self.assertIn('r.batch_id = v.collection_batch_id', sql)
            self.assertIn('r.collection_country = v.collection_country', sql)
            self.assertNotIn('youtube_collection_logs', sql)
        self.assertNotIn('DATE(v.created_at)', list_sql)
        self.assertEqual(('2026-07-29', 'HHP'), list_params)
        self.assertEqual(list_params, count_params)

    def test_comment_rows_do_not_join_on_video_id_alone(self):
        cursor = ScriptedCursor([
            {'fetchall': [('BR', 'batch-1', 'comment-1')]},
            {'fetchone': (40938,)},
        ])

        columns, rows, total = self.repo.get_youtube_comments(
            cursor, '2026-07-29', 'HHP'
        )

        self.assertEqual('collection_country', columns[0])
        self.assertEqual(40938, total)
        self.assertEqual(1, len(rows))
        sql, params = cursor.calls[0]
        self.assertIn('r.batch_id = c.collection_batch_id', sql)
        self.assertIn('r.collection_country = c.collection_country', sql)
        self.assertIn('v.collection_batch_id = c.collection_batch_id', sql)
        self.assertIn('v.collection_country = c.collection_country', sql)
        self.assertNotIn('DATE(c.created_at)', sql)
        self.assertEqual(('2026-07-29', 'HHP'), params)

    def test_logs_use_country_runs_only(self):
        cursor = ScriptedCursor([{'fetchall': []}])

        columns, rows, total = self.repo.get_youtube_logs(
            cursor, '2026-07-29', 'HHP'
        )

        self.assertIn('collection_country', columns)
        self.assertEqual([], rows)
        self.assertEqual(0, total)
        sql, _ = cursor.calls[0]
        self.assertIn('youtube_country_collection_runs', sql)
        self.assertNotIn('youtube_collection_logs', sql)


if __name__ == '__main__':
    unittest.main()
