import unittest
from datetime import date, datetime

from tests.unit.support import load_module, module_stub, package_stub


class YouTubeServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_stub = module_stub('layer1_testpkg.youtube_repositories')
        schedule_info = {
            'us_start_hour': 4,
            'kst_start': {'full_display': '2026-07-29 17:00', 'is_dst': True},
            'kst_end': {'full_display': '2026-07-29 21:00'},
            'is_pending': False,
            'is_collecting': False,
            'collection_done': True,
        }
        stubs = {
            'layer1_testpkg': package_stub('layer1_testpkg'),
            'layer1_testpkg.youtube_repositories': cls.repo_stub,
            'apps': package_stub('apps'),
            'apps.common': package_stub('apps.common'),
            'apps.common.db': module_stub(
                'apps.common.db', dx_connection=lambda: None
            ),
            'apps.common.response': module_stub(
                'apps.common.response', log_error=lambda error: str(error)
            ),
            'apps.common.dx_schedules': module_stub(
                'apps.common.dx_schedules',
                get_schedule_kst_info=lambda *_: schedule_info,
                get_kst_time_info=lambda *_: schedule_info['kst_start'],
            ),
            'apps.dx': package_stub('apps.dx'),
            'apps.dx.dx_layer1': package_stub('apps.dx.dx_layer1'),
            'apps.dx.dx_layer1.common': package_stub('apps.dx.dx_layer1.common'),
            'apps.dx.dx_layer1.common.context': module_stub(
                'apps.dx.dx_layer1.common.context',
                SECTION_TITLES={'youtube': 'Consumer (YouTube)'},
            ),
        }
        cls.service = load_module(
            'apps/dx/dx_layer1/youtube/youtube_services.py',
            'layer1_testpkg.youtube_services',
            stubs,
        )

    def setUp(self):
        self.repo_stub.get_youtube_expected = lambda _cursor: {
            'HHP': {
                'expected_jobs': 240,
                'expected_countries': 10,
                'keywords_per_country_min': 24,
                'keywords_per_country_max': 24,
            }
        }
        self.repo_stub.get_youtube_avg = lambda _cursor, _target: {
            'HHP': {'avg_video': 240, 'avg_comment': 40000}
        }

    def _stats(self, today_rows):
        self.repo_stub.get_youtube_today = lambda _cursor, _target: today_rows
        return self.service.get_layer1_stats(
            object(), date(2026, 7, 29), datetime(2026, 7, 30, 9, 0)
        )['check']

    def test_completed_keyword_count_drives_rate_and_expected_values(self):
        check = self._stats([
            ('HHP', 240, 240, 841, 40938, 10, 10),
        ])

        self.assertEqual(240, check['actual'])
        self.assertEqual(240, check['expected'])
        self.assertEqual(100.0, check['rate'])
        self.assertEqual('OK', check['status'])
        category = check['categories'][0]
        self.assertEqual(240, category['attempted_count'])
        self.assertEqual(240, category['log_count'])
        self.assertEqual(10, category['completed_country_count'])
        self.assertEqual(10, category['expected_country_count'])
        self.assertEqual(24, category['keywords_per_country_min'])
        self.assertEqual(841, category['video_count'])
        self.assertEqual(40938, category['comment_count'])

    def test_failed_country_does_not_count_attempted_jobs_as_completed(self):
        check = self._stats([
            ('HHP', 240, 216, 700, 30000, 10, 9),
        ])

        category = check['categories'][0]
        self.assertEqual(240, category['attempted_count'])
        self.assertEqual(216, category['log_count'])
        self.assertEqual(90.0, category['rate'])
        self.assertEqual('WARNING', category['status'])

    def test_expected_category_is_visible_even_when_no_run_exists(self):
        check = self._stats([])

        self.assertEqual(0, check['actual'])
        self.assertEqual(240, check['expected'])
        self.assertEqual('CRITICAL', check['status'])
        self.assertEqual('HHP', check['categories'][0]['name'])
        self.assertEqual(0, check['categories'][0]['log_count'])


if __name__ == '__main__':
    unittest.main()
