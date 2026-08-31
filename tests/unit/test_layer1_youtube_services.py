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
            'apps.common.inspection_dates': module_stub(
                'apps.common.inspection_dates',
                resolve_youtube_monitoring_date=lambda inspection: {
                    'inspection_date': str(inspection),
                    'source_date': '2026-07-28',
                    'offset_days': -1,
                    'country': 'SEA',
                    'source_key': 'sea_youtube',
                },
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
                'distinct_keywords': 24,
            },
        }

    def _stats(self, today_rows):
        self.today_target = None
        self.schedule_target = None

        def get_today(_cursor, target):
            self.today_target = target
            return today_rows

        def get_schedule(_schedule_type, target, _now):
            self.schedule_target = target
            return {
                'us_start_hour': 4,
                'kst_start': {
                    'full_display': '2026-07-28 17:00',
                    'is_dst': True,
                },
                'kst_end': {'full_display': '2026-07-28 21:00'},
                'is_pending': False,
                'is_collecting': False,
                'collection_done': True,
            }

        self.repo_stub.get_youtube_today = get_today
        self.service.get_schedule_kst_info = get_schedule
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
        self.assertEqual('2026-07-28', self.today_target)
        self.assertEqual(date(2026, 7, 28), self.schedule_target)
        self.assertEqual('2026-07-29', check['inspection_date'])
        self.assertEqual('2026-07-28', check['source_date'])
        self.assertEqual(-1, check['offset_days'])
        self.assertEqual('sea_youtube', check['source_key'])
        self.assertEqual('2026-07-28 04:00', check['us_time'])
        category = check['categories'][0]
        self.assertEqual(240, category['log_count'])
        self.assertEqual(240, category['attempted_count'])
        self.assertEqual(841, category['video_count'])
        self.assertEqual(40938, category['comment_count'])
        self.assertEqual(10, category['country_count'])
        self.assertEqual(10, category['completed_country_count'])
        self.assertEqual(10, category['expected_country_count'])
        self.assertEqual(24, category['distinct_keyword_count'])

    def test_failed_country_does_not_count_attempted_jobs_as_completed(self):
        check = self._stats([
            ('HHP', 240, 216, 700, 30000, 10, 9),
        ])

        category = check['categories'][0]
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

    def test_raw_data_uses_the_same_d_minus_one_source_date(self):
        requested = {}

        class ConnectionContext:
            def __enter__(self):
                return object(), object()

            def __exit__(self, *_args):
                return False

        def get_logs(_cursor, source_date, category):
            requested['source_date'] = source_date
            requested['category'] = category
            return ['id'], [(7,)], 1

        old_connection = self.service.dx_connection
        self.service.dx_connection = lambda: ConnectionContext()
        self.repo_stub.get_youtube_logs = get_logs
        try:
            result = self.service.get_youtube_raw_data(
                'HHP', 'logs', date(2026, 7, 29)
            )
        finally:
            self.service.dx_connection = old_connection

        self.assertEqual('2026-07-28', requested['source_date'])
        self.assertEqual('HHP', requested['category'])
        self.assertEqual('2026-07-29', result['inspection_date'])
        self.assertEqual('2026-07-28', result['source_date'])
        self.assertEqual(-1, result['offset_days'])
        self.assertEqual([(7,)], result['data'])


if __name__ == '__main__':
    unittest.main()
