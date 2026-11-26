"""D-DAY verifies and caches collection counts without touching quality data."""
from contextlib import contextmanager
from datetime import date, datetime
from unittest import TestCase
from unittest.mock import Mock, patch

from django.test import RequestFactory
from django.core.cache import cache

from apps.common.sea_collection import KST
from apps.dx.dx_layer1.dashboard import collection_revisions as revisions, collection_services as sea
from apps.dx.dx_layer1.dashboard import dashboard_api, seda_collection as seda


DAY = date(2026, 11, 24)
NOW = datetime(2026, 11, 25, 18, tzinfo=KST)
SEA = ('SEA', 'TV', 'Walmart')
SEDA = ('SEDA', 'TV', 'Casas Bahia')
NORMAL = (280, '2026-11-24 20:00:00', 'first-batch', 250, 30)
MISSING = (0, None, None, 0, 0)
MISMATCH = (120, '2026-11-24 20:00:00', 'second-batch', 40, 80)


@contextmanager
def connection(**kwargs):
    yield None, None


class DdayRefreshTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_confirmed_normal_reuses_counts_and_only_changed_scope_reruns(self):
        current = {SEA: 'sea-1', SEDA: 'seda-1'}
        with patch.object(revisions, 'completed_revisions', side_effect=lambda _: current.copy()), \
                patch.object(revisions, 'dx_connection', connection), \
                patch.object(sea, 'SOURCES', (sea.SOURCES[0],)), \
                patch.object(seda, 'SEDA_SOURCE_CONFIG', {'tv': {'category': 'TV'}}), \
                patch.object(sea, 'fetch_collection', return_value=NORMAL) as sea_query, \
                patch.object(seda, 'fetch_collection', return_value=NORMAL) as seda_query:
            first = sea.get_dday_collection_status(DAY, NOW, reuse_normal=True)
            self.assertEqual(first, sea.get_dday_collection_status(DAY, NOW, reuse_normal=True))
            self.assertEqual((sea_query.call_count, seda_query.call_count), (1, 1))
            current[SEA] = 'sea-2'
            sea_query.return_value = MISMATCH
            changed = sea.get_dday_collection_status(DAY, NOW, reuse_normal=True)
            self.assertEqual(changed['retailers'][0]['status'], 'rank_mismatch')
            self.assertEqual((sea_query.call_count, seda_query.call_count), (2, 1))
            sea.get_dday_collection_status(DAY, NOW, reuse_normal=True)
            self.assertEqual((sea_query.call_count, seda_query.call_count), (3, 1))
            current.pop(SEDA)
            seda_query.return_value = MISSING
            result = sea.get_dday_collection_status(DAY, NOW, reuse_normal=True)
            self.assertEqual(result['countries'][1]['retailers'][0]['status'], 'uncollected')
            self.assertEqual(seda_query.call_count, 2)

    def test_revision_change_during_read_does_not_register_cached_counts(self):
        with patch.object(revisions, 'completed_revisions',
                          side_effect=[{SEA:'first'}, {SEA:'second'}, {SEA:'second'}]), \
                patch.object(revisions, 'dx_connection', connection):
            query = Mock(return_value=NORMAL)
            read = revisions.CollectionReads(DAY)
            read.read(query, 'walmart', SEA)
            read.store([{'country':'SEA', 'retailers':[
                {'product':'TV','retailer':'Walmart','status':'received','count':280,'batch_id':'first-batch'}
            ]}])
            revisions.CollectionReads(DAY).read(query, 'walmart', SEA)
            self.assertEqual(query.call_count, 2)

    def test_manual_request_bypasses_normal_reuse(self):
        req = RequestFactory().get('/dx/layer1/api/collection-status/',
                                   {'date':str(DAY), 'refresh':'1', 'reuse_normal':'1'})
        with patch.object(dashboard_api, 'get_dday_collection_status', return_value={}) as reader:
            self.assertEqual(dashboard_api.collection_status(req).status_code, 200)
            reader.assert_called_once_with(DAY)
