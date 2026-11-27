import json
import unittest
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import Mock, patch

from django.test import RequestFactory

from apps.dx.dx_dashboard import views
from apps.dx.dx_layer1.sem_retail import sem_retail_services as sem


class DxHomeSemTvTests(unittest.TestCase):
    def test_receipts_use_one_same_day_query_at_launch_and_show_missing_only_after_window(self):
        factory = RequestFactory()
        cursor = Mock()

        @contextmanager
        def connection():
            yield Mock(), cursor

        target_time = datetime.fromisoformat('2026-11-27T14:00:00+09:00')
        with patch.object(views, 'dx_connection', side_effect=connection) as connect, \
                patch.object(sem.repo, 'get_tv_observation_counts', return_value={
                    'walmart': {'batch_id': 'W-1', 'raw_count': 300, 'main_count': 60, 'bsr_count': 80}
                }) as read, \
                patch.object(views, 'get_new_tv_receipts', side_effect=lambda cursor, day:
                             sem.get_new_tv_receipts(cursor, day, target_time)):
            before = views.sem_tv_status(factory.get('/dx/api/sem-tv-status/', {'date': '2026-11-26'}))
            self.assertEqual({'countries': []}, json.loads(before.content))
            connect.assert_not_called()
            read.assert_not_called()

            response = views.sem_tv_status(factory.get('/dx/api/sem-tv-status/', {'date': '2026-11-27'}))
            country, = json.loads(response.content)['countries']
            self.assertEqual(('SEM', '2026-11-27'), (country['country'], country['source_date']))
            walmart, sams = country['retailers']
            self.assertEqual(('Walmart', 'rank_mismatch'), (walmart['retailer'], walmart['status']))
            self.assertEqual(("Sam's Club", 'uncollected'), (sams['retailer'], sams['status']))
            read.assert_called_once_with(cursor, '2026-11-27')

            target_time = datetime.fromisoformat('2026-11-27T08:00:00+09:00')
            response = views.sem_tv_status(factory.get('/dx/api/sem-tv-status/', {'date': '2026-11-27'}))
            country, = json.loads(response.content)['countries']
            self.assertEqual(['scheduled', 'scheduled'], [row['status'] for row in country['retailers']])
            read.assert_called_once()

            target_time = datetime.fromisoformat('2026-11-27T12:00:00+09:00')
            reader = views.sem_tv_status(factory.get('/dx/api/sem-tv-status/', {'date': '2026-11-27'}))
            country, = json.loads(reader.content)['countries']
            self.assertEqual('collecting', country['retailers'][1]['status'])

            bad = views.sem_tv_status(factory.get('/dx/api/sem-tv-status/', {'date': 'bad'}))
            self.assertEqual(400, bad.status_code)
