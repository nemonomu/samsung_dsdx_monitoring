"""D-DAY verifies and caches collection counts without touching quality data."""
from datetime import date, datetime
from unittest import TestCase
from unittest.mock import Mock, patch

from django.test import RequestFactory, override_settings
from django.core.cache import cache
from psycopg2 import OperationalError

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


class DdayRefreshTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    @override_settings(DX_DDAY_COLLECTION_REVISIONS=True)
    def test_normal_reuses_counts_and_only_changed_scope_reruns(self):
        sea_result, seda_result = [NORMAL, 'sea-1'], [NORMAL, 'seda-1']

        def fetch(result, _, source, day, *, revision_only=False, with_revision=False):
            counts, digest = result
            return digest if revision_only else (*counts, digest) if with_revision else counts

        with patch.object(sea, 'dx_connection') as db, \
                patch.object(sea, 'SOURCES', (sea.SOURCES[0],)), \
                patch.object(seda, 'SEDA_SOURCE_CONFIG', {'tv': {'category': 'TV'}}), \
                patch.object(revisions, '_backend', return_value=cache), \
                patch.object(revisions, '_root'), \
                patch.object(sea, 'fetch_collection', side_effect=lambda *args, **kwargs: fetch(sea_result, *args, **kwargs)), \
                patch.object(seda, 'fetch_collection', side_effect=lambda *args, **kwargs: fetch(seda_result, *args, **kwargs)):
            db.return_value.__enter__.return_value = (Mock(), Mock())
            first = sea.get_dday_collection_status(DAY, NOW, reuse_normal=True)
            self.assertEqual(first['source_reads'], 2)
            again = sea.get_dday_collection_status(DAY, NOW, reuse_normal=True)
            self.assertEqual((again['revision_reused'], again['source_reads']), (2, 0))
            self.assertEqual(first['countries'], again['countries'])

            sea_result[:] = [MISMATCH, 'sea-2']
            changed = sea.get_dday_collection_status(DAY, NOW, reuse_normal=True)
            self.assertEqual(changed['retailers'][0]['status'], 'rank_mismatch')
            self.assertEqual((changed['revision_reused'], changed['source_reads']), (1, 1))
            again = sea.get_dday_collection_status(DAY, NOW, reuse_normal=True)
            self.assertEqual((again['revision_reused'], again['source_reads']), (1, 1))

            seda_result[:] = [MISSING, 'seda-2']
            removed = sea.get_dday_collection_status(DAY, NOW, reuse_normal=True)
            self.assertEqual(removed['countries'][1]['retailers'][0]['status'], 'uncollected')
            self.assertEqual((removed['revision_reused'], removed['source_reads']), (0, 2))

    def test_running_scope_reads_source_counts(self):
        reads = revisions.CollectionReads(DAY, Mock(), cache=cache)
        read_source = Mock(return_value=NORMAL)
        self.assertEqual(reads.read(read_source, 'walmart', SEA, False), NORMAL)
        self.assertEqual((reads.reused, reads.source_reads), (0, 1))
        read_source.assert_called_once_with(reads.cursor, 'walmart', DAY)

    def test_signature_failure_falls_back_to_source_counts(self):
        reads = revisions.CollectionReads(DAY, Mock(), cache=cache)
        query = Mock(side_effect=[OperationalError('signature timeout'), NORMAL])
        self.assertEqual(reads.read(query, 'walmart', SEA, True), NORMAL)
        self.assertEqual((reads.reused, reads.source_reads), (0, 1))
        self.assertFalse(reads.fresh)

    def test_manual_request_bypasses_normal_reuse(self):
        req = RequestFactory().get('/dx/layer1/api/collection-status/',
                                   {'date':str(DAY), 'refresh':'1', 'reuse_normal':'1'})
        with patch.object(dashboard_api, 'get_dday_collection_status', return_value={}) as reader:
            self.assertEqual(dashboard_api.collection_status(req).status_code, 200)
            reader.assert_called_once_with(DAY)
