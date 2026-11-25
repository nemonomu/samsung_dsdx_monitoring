from datetime import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.dx.dx_layer1.models import ColumnStatisticsNote


@override_settings(DEBUG=False)
class ColumnStatisticsNoteTests(TestCase):
    scope = {'country': 'SEA', 'product': 'TV', 'retailer': 'Amazon'}

    def setUp(self):
        self.url = reverse('dx_layer1:api_column_statistics_notes')
        self.user = get_user_model().objects.create_user(username='note-editor', is_staff=True)
        self.client.force_login(self.user)

    def save(self, client=None, **changes):
        data = {**self.scope, 'column': 'sku', 'text': '확인 메모', 'revision': 0, **changes}
        return (client or self.client).post(self.url, data, content_type='application/json')

    def test_note_persists_across_dates_and_tracks_both_timestamps(self):
        with patch('apps.common.monitoring_cache.invalidate_monitoring_cache') as invalidate:
            created = self.save(date='2026-11-24').json()['note']
            invalidate.assert_not_called()
        self.assertEqual('확인 메모', created['text'])
        self.assertEqual(1, created['revision'])

        next_day = self.client.get(self.url, {**self.scope, 'date': '2026-11-25'}).json()['notes']
        self.assertEqual(created, next_day['sku'])

        edited = self.save(retailer='AMAZON', text='수정한 메모', revision=1, date='2026-11-25').json()['note']
        self.assertEqual('수정한 메모', edited['text'])
        self.assertEqual(2, edited['revision'])
        self.assertEqual(created['created_at'], edited['created_at'])
        self.assertGreater(datetime.fromisoformat(edited['updated_at']), datetime.fromisoformat(created['updated_at']))
        self.assertEqual(1, ColumnStatisticsNote.objects.count())
        self.assertEqual({'sku': edited}, self.client.get(self.url, {**self.scope, 'date': '2026-11-24'}).json()['notes'])

    def test_conflicting_writes_preserve_the_latest_note_and_empty_text_can_clear(self):
        self.assertEqual(200, self.save().status_code)
        duplicate = self.save(text='오래된 신규 입력')
        self.assertEqual(409, duplicate.status_code)
        self.assertEqual('확인 메모', duplicate.json()['note']['text'])

        self.assertEqual(200, self.save(text='최신 메모', revision=1).status_code)
        stale = self.save(text='오래된 수정', revision=1)
        self.assertEqual(409, stale.status_code)
        self.assertEqual('최신 메모', stale.json()['note']['text'])
        cleared = self.save(text='  ', revision=2).json()['note']
        self.assertEqual('', cleared['text'])
        self.assertEqual(3, cleared['revision'])

    def test_notes_are_separated_by_scope_and_environment(self):
        self.assertEqual(200, self.save().status_code)
        self.assertEqual(200, self.save(column='item', text='다른 컬럼').status_code)
        self.assertEqual({'item', 'sku'}, set(self.client.get(self.url, self.scope).json()['notes']))
        for scope in ({**self.scope, 'retailer': 'Costco'}, {**self.scope, 'country': 'SIEL'}):
            self.assertEqual({}, self.client.get(self.url, scope).json()['notes'])
        self.assertEqual(200, self.save(country='SIEL').status_code)
        self.assertEqual({}, self.client.get(self.url, {**self.scope, 'country': 'SIEL', 'product': 'REF'}).json()['notes'])
        with override_settings(DEBUG=True):
            self.assertEqual({}, self.client.get(self.url, self.scope).json()['notes'])
            self.assertEqual(200, self.save(text='테스트 메모').status_code)
        self.assertEqual('확인 메모', self.client.get(self.url, self.scope).json()['notes']['sku']['text'])

    def test_authentication_csrf_and_input_validation(self):
        self.assertEqual(302, Client().get(self.url, self.scope).status_code)
        denied = Client()
        denied.force_login(get_user_model().objects.create_user(username='no-dx'))
        self.assertEqual(403, denied.get(self.url, self.scope).status_code)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.user)
        self.assertEqual(403, self.save(client=csrf).status_code)
        for changes in ({'retailer': 'all'}, {'column': ''}, {'column': 'main_rank'}, {'text': 'a' * 2001},
                        {'revision': True}, {'revision': -1}):
            self.assertEqual(400, self.save(**changes).status_code)
        self.assertFalse(ColumnStatisticsNote.objects.exists())
