import json
import unittest
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from django.core.cache import cache
from django.test import RequestFactory, override_settings
from psycopg2 import OperationalError
from apps.dx.dx_layer1.common import retail_batches
from apps.dx.dx_layer1.dashboard import country_revisions, dashboard_api
from apps.dx.dx_layer1.event_master import services as event_master_services

from tests.unit.support import load_module, module_stub, package_stub


class RecordingCursor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((' '.join(sql.split()), params))

    def fetchone(self):
        return None


class StatsService:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def get_layer1_stats(self, *_args, **_kwargs):
        self.calls.append((_args, _kwargs))
        if self.error:
            raise self.error
        return self.result


class Layer1DashboardIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        empty_service = module_stub('empty_layer1_service')
        stubs = {
            'apps.dx.dx_layer1.event_master': package_stub('apps.dx.dx_layer1.event_master'),
            'apps.dx.dx_layer1.event_master.services': event_master_services,
            'apps.dx.dx_layer1.common.retail_batches': retail_batches,
            'apps.dx.dx_layer1.dashboard.country_revisions': country_revisions,
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
                load_collection_schedules=lambda: [],
                is_target_date=lambda *_: False,
            ),
            'apps.common.monitoring_exclusions': module_stub(
                'apps.common.monitoring_exclusions',
                DISABLED_CHECK_TYPES=frozenset({
                    'market_trend',
                    'market_demand',
                    'market_promotion',
                    'market_competitor',
                    'market_competitor_event',
                }),
            ),
            'apps.dx': package_stub('apps.dx'),
            'apps.dx.dx_layer1': package_stub('apps.dx.dx_layer1'),
        }

        service_modules = {
            'retail': 'retail_services',
            'sentiment': 'sentiment_services',
            'youtube': 'youtube_services',
            'siel_retail': 'siel_retail_services',
            'sem_retail': 'sem_retail_services',
            'seg_retail': 'seg_retail_services',
            'seuk_retail': 'seuk_retail_services',
            'seib_retail': 'seib_retail_services',
            'seda_retail': 'seda_retail_services',
            'tse_retail': 'tse_retail_services',
            'market_trend': 'market_trend_services',
            'market_demand': 'market_demand_services',
            'market_competitor': 'market_competitor_services',
            'market_competitor_event': 'market_competitor_event_services',
            'market_promotion': 'market_promotion_services',
        }
        for package_name, module_name in service_modules.items():
            package_path = f'apps.dx.dx_layer1.{package_name}'
            module_path = f'{package_path}.{module_name}'
            stubs[package_path] = package_stub(package_path)
            stubs[module_path] = empty_service

        macro_module = module_stub('apps.dx.dx_layer1.macro.macro_services')
        for name in (
            'macro_capital_stock_svc', 'macro_net_interest_svc',
            'macro_potential_gdp_svc', 'macro_gdp_ppp_nominal_svc',
            'macro_gdp_ppp_real_svc', 'macro_disposable_income_real_svc',
            'macro_cpi_svc', 'macro_disposable_income_nominal_svc',
            'macro_household_debt_svc', 'macro_rpi_svc',
        ):
            setattr(macro_module, name, empty_service)
        stubs['apps.dx.dx_layer1.macro'] = package_stub(
            'apps.dx.dx_layer1.macro'
        )
        stubs['apps.dx.dx_layer1.macro.macro_services'] = macro_module

        cls.service = load_module(
            'apps/dx/dx_layer1/dashboard/services.py',
            'layer1_dashboard_service_under_test',
            stubs,
        )

    def test_parallel_dashboard_matches_serial_and_keeps_competitor_batch(self):
        @contextmanager
        def connection():
            yield object(), RecordingCursor()

        class FreshService(StatsService):
            def get_layer1_stats(self, *args, **kwargs):
                return deepcopy(super().get_layer1_stats(*args, **kwargs))

        order = ['youtube', 'seg_retail', 'market_competitor', 'retail', 'market_competitor_event']
        services = {check: FreshService({
            'check': {'check_type': check, 'status': 'REVIEW' if check == 'seg_retail' else 'OK'},
            'comp_batch_id': 'batch-7' if check == 'market_competitor' else None,
            'failed_items': [],
        }) for check in order}
        with patch.object(self.service, 'dx_connection', connection), \
                patch.object(self.service, '_get_active_services', return_value=(
                    list(services.items()), {'retail', 'seg_retail', 'youtube'}, set(order),
                )), patch.object(self.service, 'add_batch_counts'):
            day = date(2026, 11, 26)
            serial = self.service.get_dashboard_stats(day)
            grouped = self.service.get_dashboard_stats(day, parallel=True)
        serial.pop('timestamp')
        grouped.pop('timestamp')
        self.assertEqual(serial, grouped)
        self.assertEqual([call[1]['comp_batch_id'] for call in
                          services['market_competitor_event'].calls], ['batch-7', 'batch-7'])

    @override_settings(MONITORING_CACHE_ENABLED=False)
    def test_dashboard_scopes_read_only_their_schedule_group(self):
        @contextmanager
        def connection():
            yield object(), RecordingCursor()

        def check(check_type):
            return StatsService({'check': {'check_type': check_type, 'status': 'OK'}})

        event, youtube, seg = map(check, ('event_master', 'youtube', 'seg_retail'))
        order = [('event_master', event), ('youtube', youtube), ('seg_retail', seg)]
        daily = {'youtube', 'seg_retail'}
        target = {'event_master', 'youtube'}
        factory = RequestFactory()

        def request(scope, **options):
            return dashboard_api.layer_stats(factory.get('/layer1/api/stats/', {
                'dashboard': '1', 'dashboard_scope': scope, 'date': '2026-11-26', **options,
            }))

        with patch.object(self.service, 'dx_connection', connection), \
                patch.object(self.service, '_get_active_services', return_value=(order, daily, target)), \
                patch.object(dashboard_api, 'get_dashboard_stats', self.service.get_dashboard_stats):
            self.assertEqual(400, request('unsupported').status_code)
            normal = json.loads(request('daily').content)
            self.assertEqual(['seg_retail', 'youtube'], [row['check_type'] for row in normal['checks']])
            self.assertEqual([False, True], [row['is_target_date'] for row in normal['checks']])
            self.assertEqual((1, 1), (normal['summary']['total_checked'], normal['summary']['passed']))
            self.assertFalse(event.calls)
            self.assertEqual((1, 1), (len(youtube.calls), len(seg.calls)))
            delayed = json.loads(request('periodic', refresh='1').content)
            self.assertEqual(['event_master'], [row['check_type'] for row in delayed['checks']])
            self.assertEqual((1, 1), (delayed['summary']['total_checked'], delayed['summary']['passed']))
            self.assertEqual((1, 1, 1), (len(event.calls), len(youtube.calls), len(seg.calls)))
            out_of_scope = json.loads(request('daily', check_type='event_master').content)
            self.assertEqual([], out_of_scope['checks'])
            self.assertEqual(0, out_of_scope['summary']['total_checked'])
            self.assertEqual(1, len(event.calls))

    def test_daily_api_reuses_only_unchanged_normal_and_manual_rereads_every_country(self):
        def result(check_type, status, count):
            return {'check': {'check_type': check_type, 'status': status, 'phase': 'complete',
                              'categories': [{'retailers': [{'status': status, 'count': count}]}]}}

        cursors = []

        @contextmanager
        def connection():
            cursor = RecordingCursor()
            cursors.append(cursor)
            yield object(), cursor

        seg = StatsService(result('seg_retail', 'OK', 300))
        seda = StatsService(result('seda_retail', 'CRITICAL', 0))
        periodic = StatsService(result('event_master', 'OK', 10))
        states = {'seg_retail': ('first',)}
        services = [('seg_retail', seg), ('seda_retail', seda), ('event_master', periodic)]
        daily = {'seg_retail', 'seda_retail'}
        target = {*daily, 'event_master'}
        cache.clear()
        self.addCleanup(cache.clear)
        factory = RequestFactory()

        def request(**query):
            return dashboard_api.layer_stats(factory.get('/layer1/api/stats/', {
                'dashboard': '1', 'date': '2026-11-26', **query,
            }))

        with TemporaryDirectory() as cache_dir, override_settings(MONITORING_CACHE_DIR=cache_dir), \
                patch.object(self.service, 'dx_connection', connection), \
                patch.object(self.service, '_get_active_services', return_value=(services, daily, target)), \
                patch.object(self.service, 'add_batch_counts'), \
                patch.object(dashboard_api, 'get_dashboard_stats', self.service.get_dashboard_stats), \
                patch.object(country_revisions, '_root'), \
                patch.object(country_revisions, '_backend', return_value=cache), \
                patch.object(country_revisions, 'source_revision',
                             side_effect=lambda _, check, day: states[check['check_type']]) as revision:
            request()
            request()
            self.assertEqual((len(seg.calls), len(seda.calls), len(periodic.calls)), (1, 2, 1))
            states['seg_retail'] = ('recollected',)
            request()
            self.assertEqual((len(seg.calls), len(seda.calls)), (2, 3))
            self.assertEqual(revision.call_count, 3)
            seg.error = OperationalError('manual refresh failed')
            self.assertIn(b'"status": "ERROR"', request(refresh='1').content)
            request()
            self.assertEqual((len(seg.calls), len(seda.calls), len(periodic.calls)), (4, 5, 2))
            request(check_type='seg_retail')
            self.assertEqual((len(seg.calls), len(seda.calls), len(periodic.calls)), (5, 5, 2))
        transactions = [cursor.calls[0][0] for cursor in cursors if cursor.calls]
        self.assertEqual(transactions.count('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'), 5)

    def test_duplicate_batches_and_preview_query_errors_prevent_reuse(self):
        row = {'status': 'OK', 'count': 300, 'verification_state': 'ready', 'batch_count': 1}
        preview = {'status': 'OK', 'exclude_from_total': True}
        check = {'status': 'OK', 'categories': [{'retailers': [row, preview]}]}
        self.assertTrue(country_revisions.reusable(check, []))
        row['batch_count'] = 2
        self.assertFalse(country_revisions.reusable(check, []))
        row['batch_count'] = 1
        preview['status'] = 'ERROR'
        self.assertFalse(country_revisions.reusable(check, []))
        preview['status'] = 'OK'
        row.update(main_count=50, bsr_count=100)
        self.assertFalse(country_revisions.reusable(check, []))

    def test_seuk_raw_receipt_never_hides_known_fixed_bsr_or_zero_main_issue(self):
        row = {'retailer': 'Currys', 'status': 'OK', 'count': 300,
               'main_count': 300, 'bsr_count': 99, 'verification_state': 'ready'}
        check = {'check_type': 'seuk_retail', 'status': 'OK', 'categories': [{'retailers': [row]}]}
        self.assertFalse(country_revisions.reusable(check, []))
        row['bsr_count'] = 100
        self.assertTrue(country_revisions.reusable(check, []))
        row.update(retailer='Amazon', main_count=0, bsr_count=0)
        self.assertFalse(country_revisions.reusable(check, []))
        row['missing_by_raw_count'] = True
        self.assertTrue(country_revisions.reusable(check, []))

    def test_sea_unassessed_only_reuses_completed_non_anomalous_receipt(self):
        row = {'retailer': 'HomeDepot', 'status': 'UNASSESSED', 'count': 300,
               'verification_state': 'ready', 'batch_count': 1, 'batch_id': 'hd',
               'collection_phase': 'complete',
               'items': [{'name': 'Main Rank', 'count': 300}, {'name': 'BSR Rank', 'count': 100}]}
        check = {'check_type': 'retail', 'status': 'OK', 'categories': [{'retailers': [row]}]}
        self.assertFalse(country_revisions.reusable(check, []))
        self.assertTrue(country_revisions.reusable(check, [], sea_source_complete=True))
        self.assertEqual('UNASSESSED', row['status'])
        for changes in ({
            'collection_phase': 'collecting',
        }, {'batch_count': 2}, {'count': 0}, {
            'items': [{'name': 'Main Rank', 'count': 50}, {'name': 'BSR Rank', 'count': 100}],
        }):
            check['categories'][0]['retailers'] = [{**row, **changes}]
            self.assertFalse(country_revisions.reusable(check, [], sea_source_complete=True))

    def test_tse_revision_falls_back_to_the_selected_day_only(self):
        cursor = Mock()
        cursor.fetchone.return_value = ('tse',)
        check = {'check_type': 'tse_retail', 'categories': [{'product_line': 'tse_tv'}]}
        self.assertEqual(('tse',), country_revisions.source_revision(cursor, check, date(2026, 11, 26)))
        sql, params = cursor.execute.call_args_list[1].args
        self.assertIn('FROM dx_tse.dx_tse_tv_retail_com source', sql)
        self.assertEqual(['2026-11-26'], params)
        self.assertNotIn('source_date', check['categories'][0])

    def test_same_database_snapshot_bypasses_source_scans_and_changes_are_rechecked(self):
        day = date(2026, 11, 26)
        now = datetime(2026, 11, 27)
        row = {'status': 'OK', 'count': 300, 'verification_state': 'ready', 'batch_count': 1}
        check = {'check_type': 'seg_retail', 'status': 'OK',
                 'categories': [{'product_line': 'seg_tv', 'source_date': str(day), 'retailers': [row]}]}
        backing = {}
        backend = Mock()
        backend.get.side_effect = backing.get
        backend.set.side_effect = lambda key, entry, timeout: backing.update({key: entry})
        states = [('db', 'startup', '1:1:'), ('db', 'startup', '1:1:'), ('db', 'startup', '2:2:'),
                  ('db', 'startup', '2:2:'), ('db', 'startup', '3:3:')]
        with patch.object(country_revisions, '_root'), \
                patch.object(country_revisions, '_backend', return_value=backend), \
                patch.object(country_revisions, 'database_snapshot', side_effect=states), \
                patch.object(country_revisions, 'source_revision',
                             side_effect=[('first',), ('first',), ('recollected',)]) as revision:
            prime, unchanged, unrelated, unchanged_again, recollected = [
                country_revisions.CountryRevisions(Mock(), day, now, False) for _ in states
            ]
            prime.store(check, [])
            self.assertEqual(1, revision.call_count)
            self.assertEqual(check, unchanged.get('seg_retail'))
            self.assertEqual(1, revision.call_count)
            self.assertEqual(check, unrelated.get('seg_retail'))
            self.assertEqual(2, revision.call_count)
            self.assertEqual(check, unchanged_again.get('seg_retail'))
            self.assertEqual(2, revision.call_count)
            self.assertIsNone(recollected.get('seg_retail'))
            self.assertEqual(3, revision.call_count)

    def test_country_revision_uses_recorded_day_and_ignores_unrelated_fields(self):
        cursor = Mock()
        cursor.fetchone.return_value = ('segment', 'dryer')
        check = {'check_type': 'seg_retail', 'categories': [
            {'product_line': 'seg_tv', 'source_date': '2026-11-25'},
            {'product_line': 'seg_ldy_dryer', 'source_date': '2026-11-25'},
        ]}
        self.assertEqual(country_revisions.source_revision(cursor, check), ('segment', 'dryer'))
        sql, params = cursor.execute.call_args_list[1].args
        self.assertIn('source.batch_id', sql)
        self.assertIn('source.account_name', sql)
        self.assertIn('source.main_rank IS NOT NULL', sql)
        self.assertNotIn('xmin', sql)
        self.assertNotIn('final_sku_price', sql)
        self.assertEqual(params, ['2026-11-25', '2026-11-25'])

    def test_country_revision_query_failure_releases_savepoint_for_fresh_read(self):
        cursor = Mock()
        cursor.execute.side_effect = [None, OperationalError('marker failed'), None, None]
        check = {'check_type': 'siel_retail', 'categories': [
            {'product_line': 'siel_tv', 'source_date': '2026-11-25'},
        ]}
        with self.assertLogs(country_revisions.logger, 'WARNING'):
            self.assertIsNone(country_revisions.source_revision(cursor, check))
        sql, params = cursor.execute.call_args_list[1].args
        self.assertIn('AT TIME ZONE', sql)
        self.assertEqual(params, ['2026-11-25', 'Asia/Seoul', '2026-11-25', 'Asia/Seoul'])
        self.assertEqual([call.args[0] for call in cursor.execute.call_args_list[2:]], [
            'ROLLBACK TO SAVEPOINT layer1_country_revision', 'RELEASE SAVEPOINT layer1_country_revision',
        ])

    def test_seg_query_failure_is_rolled_back_locally(self):
        cursor = RecordingCursor()
        result = self.service._get_retail_stats_isolated(
            cursor, StatsService(error=RuntimeError('SEG failed')),
            date(2026, 9, 9), datetime(2026, 9, 9, 12), 'SEG',
        )
        self.assertIsNone(result)
        self.assertEqual([
            'SAVEPOINT layer1_seg_retail_monitoring',
            'ROLLBACK TO SAVEPOINT layer1_seg_retail_monitoring',
            'RELEASE SAVEPOINT layer1_seg_retail_monitoring',
        ], [sql for sql, _params in cursor.calls])
        self.assertIn('seg_retail', self.service._SERVICE_MAP)

    def test_seda_query_failure_is_rolled_back_locally(self):
        cursor = RecordingCursor()
        result = self.service._get_seda_retail_stats_isolated(
            cursor, StatsService(error=RuntimeError('SEDA failed')),
            date(2026, 9, 9), datetime(2026, 9, 9, 12),
        )
        self.assertIsNone(result)
        self.assertEqual([
            'SAVEPOINT layer1_seda_retail_monitoring',
            'ROLLBACK TO SAVEPOINT layer1_seda_retail_monitoring',
            'RELEASE SAVEPOINT layer1_seda_retail_monitoring',
        ], [sql for sql, _params in cursor.calls])
        self.assertIn('seda_retail', self.service._SERVICE_MAP)

    def _run_dashboard(self, youtube_service):
        cursor = RecordingCursor()
        retail_service = StatsService({
            'check': {
                'name': 'TV Retail',
                'check_type': 'retail',
                'status': 'OK',
            },
            'failed_items': [],
        })

        @contextmanager
        def connection():
            yield object(), cursor

        self.service.dx_connection = connection
        self.service._get_active_services = lambda _target: (
            [('youtube', youtube_service), ('retail', retail_service)],
            {'youtube', 'retail'},
            {'youtube', 'retail'},
        )
        result = self.service.get_dashboard_stats(date(2026, 7, 29))
        return result, cursor

    def test_youtube_empty_check_rolls_back_and_preserves_tv(self):
        result, cursor = self._run_dashboard(StatsService({
            'check': None,
            'failed_items': [],
        }))

        self.assertNotIn('error', result)
        self.assertEqual(['retail', 'youtube'], [c['check_type'] for c in result['checks']])
        self.assertEqual('ERROR', result['checks'][1]['status'])
        self.assertEqual(('ERROR', 1), (result['summary']['status'], result['summary']['failed']))
        self.assertEqual('Consumer (YouTube)', result['failed_items'][0]['source'])
        self.assertEqual([
            'SAVEPOINT layer1_youtube_monitoring',
            'ROLLBACK TO SAVEPOINT layer1_youtube_monitoring',
            'RELEASE SAVEPOINT layer1_youtube_monitoring',
            'SAVEPOINT layer1_sea_retail_monitoring',
            'RELEASE SAVEPOINT layer1_sea_retail_monitoring',
        ], [sql for sql, _params in cursor.calls])

    def test_collected_sem_review_is_not_a_collection_failure(self):
        @contextmanager
        def connection():
            yield object(), RecordingCursor()

        for retail_status, summary_status, failed in (
            ('OK', 'REVIEW', 0), ('CRITICAL', 'CRITICAL', 1),
        ):
            with self.subTest(retail_status=retail_status):
                active = [
                    (check_type, StatsService({
                        'check': {'check_type': check_type, 'status': status},
                        'failed_items': [],
                    }))
                    for check_type, status in (
                        ('sem_retail', 'REVIEW'), ('retail', retail_status),
                    )
                ]
                with patch.object(self.service, 'dx_connection', connection), patch.object(
                    self.service, '_get_active_services',
                    return_value=(active, {'sem_retail', 'retail'}, {'sem_retail', 'retail'}),
                ):
                    result = self.service.get_dashboard_stats(date(2026, 9, 13))
                self.assertNotIn('error', result)
                self.assertEqual(summary_status, result['summary']['status'])
                self.assertEqual(failed, result['summary']['failed'])
                self.assertEqual(2, result['summary']['total_completed'])
                self.assertEqual(1 if retail_status == 'OK' else 0, result['summary']['passed'])
                self.assertEqual([], result['failed_items'])

    def test_automatic_normal_verdict_is_preserved_while_statistics_wait(self):
        @contextmanager
        def connection():
            yield object(), RecordingCursor()

        service = StatsService({'check': {
            'check_type': 'sem_retail', 'phase': 'collecting', 'status': 'OK',
            'categories': [{'name': 'REF', 'status': 'OK', 'retailers': [
                {'retailer': 'Coppel', 'status': 'OK', 'count': 250, 'batch_id': 'present'}]}],
        }, 'failed_items': []})
        with patch.object(self.service, 'dx_connection', connection), patch.object(
            self.service, '_get_active_services', return_value=(
                [('sem_retail', service)], {'sem_retail'}, {'sem_retail'}),
        ), patch.object(self.service, 'add_batch_counts'):
            result = self.service.get_dashboard_stats(date(2026, 9, 29))
        self.assertNotIn('error', result)
        check = result['checks'][0]
        self.assertEqual('OK', check['status'])
        row = check['categories'][0]['retailers'][0]
        self.assertEqual(('OK', 'waiting', 250),
                         (row['status'], row['verification_state'], row['count']))
        self.assertEqual(1, result['summary']['passed'])
        self.assertEqual(1, result['summary']['total_completed'])
        self.assertEqual(0, result['summary']['failed'])

    def test_youtube_exception_rolls_back_and_preserves_tv(self):
        result, cursor = self._run_dashboard(StatsService(
            error=RuntimeError('youtube query failed')
        ))

        self.assertNotIn('error', result)
        self.assertEqual(['retail', 'youtube'], [c['check_type'] for c in result['checks']])
        self.assertEqual('ERROR', result['checks'][1]['status'])
        self.assertEqual(('ERROR', 1), (result['summary']['status'], result['summary']['failed']))
        self.assertIn(
            'ROLLBACK TO SAVEPOINT layer1_youtube_monitoring',
            [sql for sql, _params in cursor.calls],
        )

    def test_tse_exception_rolls_back_and_preserves_tv(self):
        cursor = RecordingCursor()
        retail_service = StatsService({
            'check': {
                'name': 'TV Retail',
                'check_type': 'retail',
                'status': 'OK',
            },
            'failed_items': [],
        })

        @contextmanager
        def connection():
            yield object(), cursor

        self.service.dx_connection = connection
        self.service._get_active_services = lambda _target: (
            [
                ('tse_retail', StatsService(error=RuntimeError('tse query failed'))),
                ('retail', retail_service),
            ],
            {'tse_retail', 'retail'},
            {'tse_retail', 'retail'},
        )

        result = self.service.get_dashboard_stats(date(2026, 8, 10))

        self.assertNotIn('error', result)
        self.assertEqual(['retail', 'tse_retail'], [c['check_type'] for c in result['checks']])
        self.assertEqual('ERROR', result['checks'][1]['status'])
        self.assertEqual(('ERROR', 1), (result['summary']['status'], result['summary']['failed']))
        self.assertEqual('TSE Retail', result['failed_items'][0]['source'])
        self.assertEqual([
            'SAVEPOINT layer1_tse_retail_monitoring',
            'ROLLBACK TO SAVEPOINT layer1_tse_retail_monitoring',
            'RELEASE SAVEPOINT layer1_tse_retail_monitoring',
            'SAVEPOINT layer1_sea_retail_monitoring',
            'RELEASE SAVEPOINT layer1_sea_retail_monitoring',
        ], [sql for sql, _params in cursor.calls])

    def test_siel_exception_rolls_back_and_preserves_tv(self):
        cursor = RecordingCursor()
        retail_service = StatsService({
            'check': {
                'name': 'SEA Retail',
                'check_type': 'retail',
                'status': 'OK',
            },
            'failed_items': [],
        })

        @contextmanager
        def connection():
            yield object(), cursor

        self.service.dx_connection = connection
        original_services = self.service._get_active_services
        self.service._get_active_services = lambda _target: (
            [
                (
                    'siel_retail',
                    StatsService(error=RuntimeError('siel query failed')),
                ),
                ('retail', retail_service),
            ],
            {'siel_retail', 'retail'},
            {'siel_retail', 'retail'},
        )
        try:
            result = self.service.get_dashboard_stats(date(2026, 8, 11))
        finally:
            self.service._get_active_services = original_services

        self.assertNotIn('error', result)
        self.assertEqual(['retail', 'siel_retail'], [c['check_type'] for c in result['checks']])
        self.assertEqual('ERROR', result['checks'][1]['status'])
        self.assertEqual(('ERROR', 1), (result['summary']['status'], result['summary']['failed']))
        self.assertEqual('SIEL Retail', result['failed_items'][0]['source'])
        self.assertEqual([
            'SAVEPOINT layer1_siel_retail_monitoring',
            'ROLLBACK TO SAVEPOINT layer1_siel_retail_monitoring',
            'RELEASE SAVEPOINT layer1_siel_retail_monitoring',
            'SAVEPOINT layer1_sea_retail_monitoring',
            'RELEASE SAVEPOINT layer1_sea_retail_monitoring',
        ], [sql for sql, _params in cursor.calls])

    def test_siel_service_receives_explicit_kst_clock(self):
        cursor = RecordingCursor()
        siel_service = StatsService({
            'check': {
                'name': 'SIEL Retail',
                'check_type': 'siel_retail',
                'status': 'COLLECTING',
            },
            'failed_items': [],
        })
        expected_now = datetime(
            2026, 8, 11, 8, 59,
            tzinfo=timezone(timedelta(hours=9)),
        )

        @contextmanager
        def connection():
            yield object(), cursor

        self.service.dx_connection = connection
        original_services = self.service._get_active_services
        self.service._get_active_services = lambda _target: (
            [('siel_retail', siel_service)],
            {'siel_retail'},
            {'siel_retail'},
        )
        original_clock = self.service._get_siel_kst_now
        self.service._get_siel_kst_now = lambda: expected_now
        try:
            self.service.get_dashboard_stats(date(2026, 8, 11))
        finally:
            self.service._get_siel_kst_now = original_clock
            self.service._get_active_services = original_services

        self.assertIs(expected_now, siel_service.calls[0][0][2])
        self.assertEqual(timedelta(hours=9), expected_now.utcoffset())

    def test_tse_service_receives_explicit_kst_clock(self):
        cursor = RecordingCursor()
        tse_service = StatsService({
            'check': {
                'name': 'TSE Retail',
                'check_type': 'tse_retail',
                'status': 'COLLECTING',
            },
            'failed_items': [],
        })
        expected_now = datetime(
            2026, 8, 25, 10, 59,
            tzinfo=timezone(timedelta(hours=9)),
        )

        @contextmanager
        def connection():
            yield object(), cursor

        self.service.dx_connection = connection
        self.service._get_active_services = lambda _target: (
            [('tse_retail', tse_service)],
            {'tse_retail'},
            {'tse_retail'},
        )
        original_clock = self.service._get_tse_kst_now
        self.service._get_tse_kst_now = lambda: expected_now
        try:
            self.service.get_dashboard_stats(date(2026, 8, 25))
        finally:
            self.service._get_tse_kst_now = original_clock

        self.assertIs(expected_now, tse_service.calls[0][0][2])
        self.assertEqual(timedelta(hours=9), expected_now.utcoffset())

    def test_stopped_market_services_are_not_activated(self):
        self.service.load_collection_schedules = lambda: [
            {'check_type': 'retail', 'schedule_type': 'daily'},
            {'check_type': 'market_trend', 'schedule_type': 'daily'},
            {'check_type': 'market_demand', 'schedule_type': 'weekly'},
            {'check_type': 'market_promotion', 'schedule_type': 'weekly'},
            {'check_type': 'market_competitor', 'schedule_type': 'quarterly'},
            {'check_type': 'market_competitor_event', 'schedule_type': 'monthly'},
        ]
        self.service.check_target_date = lambda *_: True

        service_order, daily_types, target_types = self.service._get_active_services(
            date(2026, 8, 5)
        )

        self.assertEqual(
            ['retail', 'event_master'],
            [check_type for check_type, _service in service_order],
        )
        self.assertEqual({'retail'}, daily_types)
        self.assertEqual({'retail', 'event_master'}, target_types)

    def test_seda_daily_schedule_activates_layer1_service(self):
        self.service.load_collection_schedules = lambda: [
            {'check_type': 'seda_retail', 'schedule_type': 'daily'},
        ]
        self.service.check_target_date = lambda *_: True

        service_order, daily_types, target_types = self.service._get_active_services(
            date(2026, 8, 11)
        )

        self.assertEqual(
            ['seda_retail', 'event_master'],
            [check_type for check_type, _service in service_order],
        )
        self.assertEqual({'seda_retail'}, daily_types)
        self.assertEqual({'seda_retail', 'event_master'}, target_types)

    def test_primary_cards_are_sorted_without_reordering_other_checks(self):
        checks = [
            {'check_type': 'macro_cpi'},
            {'check_type': 'youtube'},
            {'check_type': 'sentiment'},
            {'check_type': 'retail'},
            {'check_type': 'seda_retail'},
            {'check_type': 'siel_retail'},
            {'check_type': 'sem_retail'},
            {'check_type': 'seg_retail'},
            {'check_type': 'tse_retail'},
            {'check_type': 'macro_rpi'},
        ]

        ordered = self.service._sort_checks_for_display(checks)

        self.assertEqual(
            [
                'retail', 'seda_retail', 'siel_retail', 'seg_retail', 'sem_retail',
                'tse_retail', 'youtube',
                'macro_cpi', 'sentiment', 'macro_rpi',
            ],
            [check['check_type'] for check in ordered],
        )
        self.assertEqual(
            ['macro_cpi', 'sentiment', 'macro_rpi'],
            [
                check['check_type']
                for check in ordered
                if check['check_type'] not in {
                    'retail', 'seda_retail', 'siel_retail', 'seg_retail', 'sem_retail',
                    'tse_retail', 'youtube'
                }
            ],
        )


if __name__ == '__main__':
    unittest.main()
