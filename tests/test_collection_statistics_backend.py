"""Run directly: python tests/test_collection_statistics_backend.py

Uses an isolated in-memory database and explicit test settings, never production configuration.
"""
import json
import sys
from contextlib import contextmanager
from datetime import date, timedelta, timezone as tz
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from django.conf import settings
if not settings.configured:
    settings.configure(
        INSTALLED_APPS=['apps.dx.dx_layer1'],
        DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}},
        USE_TZ=True, TIME_ZONE='Asia/Seoul', DEBUG=False, DEFAULT_CHARSET='utf-8',
        SECRET_KEY='isolated-test-only',
    )
import django
django.setup()
from django.core.management import call_command
from django.test import TestCase, SimpleTestCase, RequestFactory
from django.test.runner import DiscoverRunner
from django.utils import timezone
from apps.dx.dx_layer1.collection_statistics import calculations as calc, collector, api
from apps.dx.dx_layer1.collection_statistics import automatic
from apps.dx.dx_layer1.models import CollectionDailySnapshot as Daily, CollectionWeeklySnapshot as Weekly


def sample(total=300, *, retailer='Lowes', product='REF', **extra):
    return {'product': product, 'retailer': retailer, 'slot': 'daily',
            'main': total, 'bsr': 100, 'total': total, 'batch_id': 'b1',
            'complete': True, 'base_status': 'OK', 'baseline_eligible': True, **extra}


def check_for(total=300, **extra):
    return {'phase': 'complete', 'categories': [{'name': 'REF', 'retailers': [
        {'retailer': 'Lowes', 'main_count': total, 'bsr_count': 100,
         'count': total, 'batch_id': 'b1', 'status': 'OK', **extra}]}]}


class CalculationTests(SimpleTestCase):
    def test_main_review_and_abnormal_boundaries_all_countries(self):
        history = [sample(total=3000, main=2000)] * 7
        for country in calc.COUNTRIES:
            for current, expected in [(1901, None), (1900, 'VOLUME_REVIEW'),
                                      (1800, 'VOLUME_REVIEW'), (1700, 'VOLUME_REVIEW'),
                                      (1699, 'VOLUME_LOW'), (0, 'VOLUME_LOW'),
                                      (2599, None), (2600, 'VOLUME_HIGH')]:
                with self.subTest(country=country, current=current):
                    result = calc.compare_rows([sample(total=3000, main=current)], history, country=country)[0]
                    alerts = [a for a in result['alerts'] if a['metric'] == 'main']
                    self.assertEqual([expected] if expected else [], [a['status'] for a in alerts])
                    projected = calc.current_volume_decision(result, country)
                    self.assertEqual(result['alerts'], projected['alerts'])
        for extra in ({'complete': False}, {'base_status': 'ERROR'}, {'refresh_error': True}):
            row = calc.compare_rows([sample(main=1800, **extra)], history, country='SEA')[0]
            self.assertFalse(any(a['metric'] == 'main' for a in row['alerts']))

    def test_tiered_bsr_scope_and_exact_unrounded_boundaries(self):
        targets = [('SEA', 'Lowes', 'REF'), ('SEA', 'Lowes', 'LDY'),
                   ('SEA', 'Amazon', 'TV'), ('SIEL', 'Amazon', 'TV'),
                   ('SIEL', 'Amazon', 'REF'), ('SIEL', 'Amazon', 'LDY'),
                   ('SEG', 'Amazon', 'TV'), ('SEG', 'Amazon', 'REF')]
        for country, retailer, product in targets:
            history = [sample(retailer=retailer, product=product, bsr=2000)] * 7
            for current, expected in [(1701, None), (1700, 'VOLUME_REVIEW'),
                                      (1601, 'VOLUME_REVIEW'), (1600, 'VOLUME_LOW'),
                                      (0, 'VOLUME_LOW'), (2200, None)]:
                with self.subTest(country=country, product=product, retailer=retailer, current=current):
                    row = calc.compare_rows([sample(retailer=retailer, product=product, bsr=current)],
                                            history, country=country)[0]
                    alerts = [a for a in row['alerts'] if a['metric'] == 'bsr']
                    self.assertEqual([expected] if expected else [], [a['status'] for a in alerts])
                    self.assertEqual('median_28d', row['bsr_rule'])
            current = sample(retailer=retailer, product=product, bsr=79)
            history = [sample(retailer=retailer, product=product, bsr=80)] * 7
            self.assertEqual([], calc.compare_rows([current], history, country=country)[0]['alerts'])
            self.assertEqual('insufficient', calc.compare_rows([current], history[:6], country=country)[0]['bsr_comparison_state'])

    def test_tiered_projection_removes_fixed_alert_and_rechecks_saved_median(self):
        old = sample(bsr=80, alerts=[{'metric': 'bsr', 'status': 'VOLUME_LOW', 'rule': 'fixed_100'}],
                     baselines={'bsr': {'value': 100, 'days': 0, 'rule': 'fixed_100'}})
        result = calc.current_bsr_decision(old, 'SEA')
        self.assertEqual([], result['alerts'])
        self.assertEqual('insufficient', result['bsr_comparison_state'])
        for current, expected in [(99, None), (85, 'VOLUME_REVIEW'), (80, 'VOLUME_LOW')]:
            row = {**old, 'bsr': current, 'baselines': {'bsr': {'value': 100, 'days': 7, 'rule': 'median_28d'}}}
            projected = calc.current_bsr_decision(row, 'SEA')
            self.assertEqual([expected] if expected else [], [a['status'] for a in projected['alerts']])

    def test_collector_passes_legacy_naive_kst_clock_only_to_sea(self):
        seen = []
        cursor = SimpleNamespace(execute=lambda statement: None)

        @contextmanager
        def fake_connection():
            yield None, cursor

        db_stub = ModuleType('apps.common.db')
        db_stub.dx_connection = fake_connection

        def fake_stats(_cursor, _day, now):
            seen.append(now)
            return {'check': {'categories': [{'name': 'REF'}]}}

        service = SimpleNamespace(get_layer1_stats=fake_stats)
        with patch.dict(sys.modules, {'apps.common.db': db_stub}), patch.object(
                collector.importlib, 'import_module', return_value=service):
            collector.load_check('SEA', date(2026, 9, 22))
            collector.load_check('SEG', date(2026, 9, 22))

        self.assertIsNone(seen[0].tzinfo)
        self.assertIsNotNone(seen[1].tzinfo)
        self.assertEqual(timedelta(hours=9), seen[1].utcoffset())

    def test_exact_threshold_both_directions_and_rounding(self):
        history = [sample(2000)] * 7
        for current, expected in [(1400, 'VOLUME_LOW'), (2600, 'VOLUME_HIGH'), (1401, None), (2599, None)]:
            row = calc.compare_rows([sample(current)], history)[0]
            states = {alert['status'] for alert in row['alerts'] if alert['metric'] == 'total'}
            self.assertEqual({expected} if expected else set(), states)

    def test_median_ignores_one_extreme_day_without_excluding_current_findings(self):
        history = [sample(300)] * 6 + [sample(100000)]
        row = calc.compare_rows([sample(210)], history)[0]
        self.assertEqual(300, row['baselines']['main']['value'])
        self.assertEqual('VOLUME_LOW', row['alerts'][0]['status'])

    def test_history_minimum_zero_baseline_and_collecting(self):
        self.assertEqual('insufficient', calc.compare_rows([sample(100)], [sample()] * 6)[0]['comparison_state'])
        self.assertEqual([], calc.compare_rows([sample(100)], [sample(0)] * 7)[0]['alerts'])
        self.assertEqual([], calc.compare_rows([sample(100, complete=False)], [sample()] * 7)[0]['alerts'])

    def test_other_products_retailers_slots_and_failed_history_are_not_mixed(self):
        history = [sample(), sample(retailer='Amazon'), sample(product='TV'), sample(slot='AM'), sample(baseline_eligible=False)] * 6
        self.assertEqual([], calc.compare_rows([sample(100)], history)[0]['alerts'])

    def test_main_drop_not_hidden_by_total_increase(self):
        row = calc.compare_rows([sample(400, main=200)], [sample()] * 7)[0]
        self.assertEqual({'VOLUME_LOW', 'VOLUME_HIGH'}, {a['status'] for a in row['alerts']})

    def test_week_zeros_are_included_unknowns_are_not_zero_and_future_not_due(self):
        monday = date(2026, 9, 14)
        week = calc.build_week({monday: [sample(300)], monday + timedelta(days=1): [sample(0)]}, monday, monday + timedelta(days=2))[0]
        self.assertEqual({'sum': 300, 'average': 150}, week['metrics']['total'])
        self.assertEqual((2, 3, 1, 1), (week['completed_days'], week['expected_days'], week['missing_days'], week['unknown_days']))
        self.assertEqual('future', week['daily'][3]['state'])

    def test_all_bsr_counts_retained_and_raw_total_not_main_plus_bsr(self):
        rows = calc.normalize_check(check_for(300, raw_count=320), 'SEG', date(2026, 9, 21))
        self.assertEqual((300, 100, 320), (rows[0]['main'], rows[0]['bsr'], rows[0]['total']))
        rows = calc.normalize_check(check_for(300, bsr_applicable=False, actual=300, raw_count=315), 'TSE', date(2026, 9, 21))
        self.assertEqual(100, rows[0]['bsr'])
        self.assertEqual(300, rows[0]['total'])
        rows = calc.normalize_check(check_for(300, actual=300, raw_count=315), 'SEM', date(2026, 9, 21))
        self.assertEqual(300, rows[0]['total'])

    def test_fixed_bsr_99_is_low_without_history_100_is_normal(self):
        for current in (0, 99, 100, 101):
            row = calc.compare_rows([sample(bsr=current)], [], country='SEG')[0]
            bsr = [a for a in row['alerts'] if a['metric'] == 'bsr']
            self.assertEqual(current < 100, bool(bsr))
            self.assertEqual('ready', row['bsr_comparison_state'])
            if bsr:
                self.assertEqual(('VOLUME_LOW', 100, current),
                                 (bsr[0]['status'], bsr[0]['baseline'], bsr[0]['actual']))

    def test_variable_bsr_exact_30_percent_drop_and_seven_days(self):
        for country, retailer, product in [('SEM', 'HomeDepot', 'TV'),
                                           ('SEM', 'HomeDepot', 'REF'),
                                           ('SEM', 'HomeDepot', 'LDY')]:
            history = [sample(retailer=retailer, product=product, bsr=80)] * 7
            for count, low in ((56, True), (57, False), (79, False), (120, False), (0, True)):
                row = calc.compare_rows([sample(retailer=retailer, product=product, bsr=count)],
                                        history, country=country)[0]
                self.assertEqual(low, any(a['metric'] == 'bsr' for a in row['alerts']))
                self.assertEqual(80, row['baselines']['bsr']['value'])
            row = calc.compare_rows([sample(retailer=retailer, product=product, bsr=40)],
                                    history[:6], country=country)[0]
            self.assertEqual('insufficient', row['bsr_comparison_state'])
            self.assertFalse(any(a['metric'] == 'bsr' for a in row['alerts']))

    def test_exception_scope_and_pending_or_failed_do_not_make_bsr_alerts(self):
        for country, retailer, product in [('SEG', 'OTTO', 'TV'), ('SEA', 'Amazon', 'REF'),
                                           ('SEA', 'HomeDepot', 'REF'), ('SEM', 'Liverpool', 'TV')]:
            row = calc.compare_rows([sample(retailer=retailer, product=product, bsr=99)], [], country=country)[0]
            self.assertEqual('fixed_100', row['bsr_rule'])
            self.assertEqual(1, len(row['alerts']))
        for extra in ({'complete': False}, {'base_status': 'ERROR'}, {'refresh_error': True}):
            row = calc.compare_rows([sample(bsr=0, **extra)], [], country='SEG')[0]
            self.assertEqual([], row['alerts'])
            self.assertEqual('pending', row['bsr_comparison_state'])

    def test_variable_history_counts_distinct_normal_days(self):
        history = [sample(retailer='Amazon', product='TV', bsr=80, source_date=f'2026-09-{n:02}')
                   for n in range(1, 8)]
        current = sample(retailer='Amazon', product='TV', bsr=55)
        for index in range(7):
            history[index]['source_date'] = '2026-09-01'
        self.assertEqual('insufficient', calc.compare_rows([current], history, country='SEA')[0]['bsr_comparison_state'])
        for index in range(7):
            history[index]['source_date'] = f'2026-09-{index+1:02}'
        history[-1]['alerts'] = [{'metric': 'bsr', 'status': 'VOLUME_LOW'}]
        self.assertEqual('insufficient', calc.compare_rows([current], history, country='SEA')[0]['bsr_comparison_state'])
        history[-1]['alerts'] = [{'metric': 'bsr', 'status': 'VOLUME_REVIEW'}]
        self.assertEqual('insufficient', calc.compare_rows([current], history, country='SEA')[0]['bsr_comparison_state'])

    def test_fixed_projection_replaces_stale_bsr_only_and_preserves_exceptions(self):
        main_alert = {'metric': 'main', 'status': 'VOLUME_HIGH'}
        old_bsr = {'metric': 'bsr', 'status': 'VOLUME_LOW', 'baseline': 50}
        for country in calc.COUNTRIES:
            for product in ('TV', 'REF', 'LDY'):
                for retailer in ('Walmart', 'Amazon', 'HomeDepot'):
                    source = sample(retailer=retailer, product=product, bsr=99,
                                    alerts=[main_alert], bsr_comparison_state='insufficient')
                    result = calc.current_bsr_decision(source, country)
                    exception = calc.variable_bsr(source, country)
                    self.assertEqual(not exception, any(a['metric'] == 'bsr' for a in result['alerts']))
                    self.assertIn(main_alert, result['alerts'])
                    self.assertEqual([main_alert], source['alerts'])
        for count in (100, 101):
            result = calc.current_bsr_decision(sample(bsr=count, alerts=[main_alert, old_bsr]), 'SEA')
            self.assertEqual([main_alert], result['alerts'])
        for extra in ({'complete': False}, {'state': 'future'}, {'state': 'error'},
                      {'state': 'unknown'}, {'refresh_error': True}, {'base_status': 'ERROR'},
                      {'main': 0, 'total': 0, 'bsr': 0}):
            result = calc.current_bsr_decision({**sample(bsr=99, alerts=[old_bsr]), **extra}, 'SEA')
            self.assertEqual([], result['alerts'])
        for country, retailer in [('SEA', 'Amazon'), ('SEM', 'HomeDepot')]:
            result = calc.compare_rows([sample(0, main=0, bsr=0, product='TV', retailer=retailer)],
                                      [], country=country)[0]
            self.assertEqual('missing', result['bsr_comparison_state'])
            self.assertEqual([], result['alerts'])

    def test_sea_d1_slot_counts_and_launch(self):
        check = {'categories': [{'name': 'REF', 'time_slots': [{'name': 'daily', 'retailers': [
            {'retailer': 'HomeDepot', 'count': 320, 'status': 'UNASSESSED',
             'items': [{'name': 'Main Rank', 'count': 300}, {'name': 'BSR Rank', 'count': 100}]}]}]}]}
        self.assertEqual([], calc.normalize_check(check, 'SEA', date(2026, 9, 20)))
        row = calc.normalize_check(check, 'SEA', date(2026, 9, 21))[0]
        self.assertEqual((300, 100, 320), (row['main'], row['bsr'], row['total']))
        week = calc.build_week({date(2026, 9, 20): [row]}, date(2026, 9, 14), date(2026, 9, 20))[0]
        self.assertEqual(1, week['expected_days'])
        self.assertEqual(0, week['unknown_days'])


class StoreTests(TestCase):
    def test_saved_main_baseline_uses_new_thresholds_in_both_apis_without_writes(self):
        for current, expected in [(1900, 'VOLUME_REVIEW'), (1700, 'VOLUME_REVIEW'), (1699, 'VOLUME_LOW')]:
            source = sample(retailer='Walmart', product='TV', main=current, total=3000,
                            alerts=[], baselines={'main': {'value': 2000, 'days': 7}},
                            comparison_state='ready')
            Daily.objects.update_or_create(country='SEA', source_date=self.end,
                inspection_date=self.end + timedelta(days=1), defaults={
                    'rows': [source], 'digest': 'legacy', 'updated_at': timezone.now()})
            Weekly.objects.update_or_create(country='SEA', week_start=calc.week_start(self.end), defaults={
                'rows': calc.build_week({self.end: [source]}, calc.week_start(self.end), self.end),
                'updated_at': timezone.now()})
            with self.assertNumQueries(1):
                dashboard = json.loads(api.alerts(self.factory.get('/', {'date': str(self.end + timedelta(days=1))})).content)
            with self.assertNumQueries(1):
                weekly = json.loads(api.weekly(self.factory.get('/', {'date': str(self.end), 'country': 'SEA', 'weeks': '1'})).content)
            alerts = dashboard['snapshots'][0]['rows'][0]['alerts']
            self.assertEqual(expected, alerts[0]['status'])
            self.assertEqual(alerts, weekly['weeks'][0]['rows'][0]['daily'][6]['alerts'])
            self.assertEqual([], Daily.objects.get().rows[0]['alerts'])

    def test_existing_fixed_policy_upgrades_target_history_without_source_reread(self):
        old = date(2026, 8, 1)
        for offset in range(8):
            day = old + timedelta(days=offset)
            row = sample(bsr=68 if offset == 7 else 80, bsr_rule='fixed_100',
                         alerts=[{'metric': 'bsr', 'status': 'VOLUME_LOW', 'rule': 'fixed_100'}])
            Daily.objects.create(country='SEA', source_date=day, inspection_date=day + timedelta(days=1),
                                 rows=[row], digest='old', updated_at=timezone.now())
        self.refresh()
        upgraded = Daily.objects.get(country='SEA', source_date=old + timedelta(days=7)).rows[0]
        self.assertEqual(80, upgraded['baselines']['bsr']['value'])
        self.assertEqual('VOLUME_REVIEW', upgraded['alerts'][0]['status'])
        dashboard = json.loads(api.alerts(self.factory.get('/', {'date': str(old + timedelta(days=8))})).content)
        weekly = json.loads(api.weekly(self.factory.get('/', {'country': 'SEA', 'date': str(old + timedelta(days=7))})).content)
        day = next(day for week in weekly['weeks'] for row in week['rows'] for day in row['daily']
                   if day['date'] == str(old + timedelta(days=7)))
        self.assertEqual(upgraded['alerts'], dashboard['snapshots'][0]['rows'][0]['alerts'])
        self.assertEqual(upgraded['alerts'], day['alerts'])

    def setUp(self):
        self.factory = RequestFactory()
        self.end = date(2026, 9, 20)

    def refresh(self, start=None, end=None, country='SEA', loader=None):
        return collector.refresh_country(country, start or self.end, end or self.end,
            loader=loader or (lambda *_: check_for()), today=date(2026, 9, 22))

    def test_initial_backfill_uses_d1_and_idempotent_updates(self):
        observed = []
        def load(country, day):
            observed.append((country, day))
            return check_for()
        first = self.refresh(self.end - timedelta(days=7), loader=load)
        self.assertEqual(8, first['updated'])
        self.assertEqual(('SEA', date(2026, 9, 21)), observed[-1])
        self.assertEqual(0, self.refresh()['updated'])
        self.assertEqual('ready', Daily.objects.get(country='SEA', source_date=self.end).rows[0]['comparison_state'])

    def test_recollection_replaces_not_adds_and_changes_alert(self):
        self.refresh(self.end - timedelta(days=7))
        result = self.refresh(loader=lambda *_: check_for(210, batch_id='retry'))
        self.assertEqual(1, result['updated'])
        target = Daily.objects.get(source_date=self.end)
        self.assertEqual(210, target.rows[0]['total'])
        self.assertEqual('VOLUME_LOW', target.rows[0]['alerts'][0]['status'])
        self.assertEqual(2010, Weekly.objects.get(week_start=date(2026, 9, 14)).rows[0]['metrics']['total']['sum'])

    def test_old_saved_bsr_decisions_upgrade_on_normal_refresh_without_source_reread(self):
        old = self.end - timedelta(days=40)
        Daily.objects.create(country='SEG', source_date=old, inspection_date=old,
                             rows=[sample(bsr=99)], digest='old-policy', updated_at=timezone.now())
        from unittest.mock import Mock
        load = Mock(return_value=check_for())
        self.refresh(country='SEG', loader=load)
        self.assertEqual(1, load.call_count)
        upgraded = Daily.objects.get(country='SEG', source_date=old).rows[0]
        self.assertEqual('fixed_100', upgraded['bsr_rule'])
        self.assertEqual(99, upgraded['alerts'][0]['actual'])
        weekly = Weekly.objects.get(country='SEG', week_start=calc.week_start(old))
        matching = [day for row in weekly.rows for day in row['daily'] if day['date'] == str(old)]
        self.assertEqual(upgraded['alerts'], matching[0]['alerts'])

    def test_exception_bsr_decision_shared_by_stats_and_dashboard(self):
        def loader(country, inspection):
            count = 56 if inspection == self.end else 80
            return {'phase': 'complete', 'categories': [{'name': 'REF', 'retailers': [
                {'retailer': 'HomeDepot', 'main_count': 300, 'bsr_count': count,
                 'count': 300, 'batch_id': 'b1', 'status': 'OK'}]}]}
        self.refresh(self.end - timedelta(days=7), country='SEM', loader=loader)
        saved = Daily.objects.get(country='SEM', source_date=self.end).rows[0]
        self.assertEqual('median_28d', saved['bsr_rule'])
        self.assertEqual(('bsr', 'VOLUME_LOW', -30.0),
                         tuple(saved['alerts'][0][key] for key in ('metric', 'status', 'percent')))
        alerts = json.loads(api.alerts(self.factory.get('/', {'date': str(self.end)})).content)
        weekly = json.loads(api.weekly(self.factory.get('/', {'date': str(self.end), 'country': 'SEM'})).content)
        self.assertEqual(saved['alerts'], alerts['snapshots'][0]['rows'][0]['alerts'])
        day = next(day for week in weekly['weeks'] for row in week['rows'] for day in row['daily']
                   if day['date'] == str(self.end))
        self.assertEqual(saved['alerts'], day['alerts'])

    def test_legacy_walmart_99_is_red_in_both_apis_without_refresh_or_writes(self):
        # Reproduce the screenshot: saved counts exist but old alerts are empty.
        source = sample(retailer='Walmart', product='TV', main=299, total=321, bsr=99,
                        alerts=[], comparison_state='insufficient')
        Daily.objects.create(country='SEA', source_date=self.end, inspection_date=self.end + timedelta(days=1),
                             rows=[source], digest='legacy', updated_at=timezone.now())
        rows = calc.build_week({self.end: [source]}, calc.week_start(self.end), self.end)
        Weekly.objects.create(country='SEA', week_start=calc.week_start(self.end), rows=rows,
                              updated_at=timezone.now())
        with patch.object(collector, 'load_check', side_effect=AssertionError('no source read')):
            with self.assertNumQueries(1):
                weekly = json.loads(api.weekly(self.factory.get('/', {
                    'date': str(self.end), 'country': 'SEA', 'weeks': '1'})).content)
            with self.assertNumQueries(1):
                dashboard = json.loads(api.alerts(self.factory.get('/', {
                    'date': str(self.end + timedelta(days=1))})).content)
        day = weekly['weeks'][0]['rows'][0]['daily'][6]
        self.assertEqual('ready', day['bsr_comparison_state'])
        self.assertEqual(('bsr', 'VOLUME_LOW', 100, 99),
                         tuple(day['alerts'][0][key] for key in ('metric', 'status', 'baseline', 'actual')))
        self.assertEqual(day['alerts'], dashboard['snapshots'][0]['rows'][0]['alerts'])
        self.assertEqual([], Daily.objects.get().rows[0]['alerts'])
        self.assertEqual([], Weekly.objects.get().rows[0]['daily'][6]['alerts'])
        self.assertTrue(all(not d['alerts'] for d in weekly['weeks'][0]['rows'][0]['daily'][:6]))

    def test_failed_refresh_preserves_previous_good_snapshot_and_never_creates_zero(self):
        self.refresh()
        def fail(*_):
            raise RuntimeError('fixture failure')
        self.assertEqual(1, self.refresh(loader=fail)['errors'])
        saved = Daily.objects.get(source_date=self.end)
        self.assertEqual(300, saved.rows[0]['total'])
        self.assertTrue(saved.refresh_error)
        week = Weekly.objects.get(week_start=date(2026, 9, 14)).rows[0]
        self.assertEqual(0, week['missing_days'])
        self.assertEqual('error', week['daily'][6]['state'])
        self.assertEqual(1, self.refresh(loader=lambda *_: check_for())['updated'])

    def test_lease_prevents_overlapping_source_queries(self):
        collector.acquire_lease('SEA')
        with patch.object(collector, 'load_check') as load:
            result = self.refresh(loader=load)
        self.assertTrue(result['busy'])
        load.assert_not_called()

    def test_weekly_api_one_bounded_query_no_collector_call(self):
        self.refresh(self.end - timedelta(days=7))
        with patch.object(collector, 'load_check', side_effect=AssertionError('web must not read source')):
            with self.assertNumQueries(1):
                response = api.weekly(self.factory.get('/', {'date': '2026-09-20', 'country': 'SEA', 'weeks': 12}))
        self.assertEqual(200, response.status_code)
        payload = json.loads(response.content)
        self.assertEqual(12, len(payload['weeks']))
        self.assertEqual(['Lowes'], payload['retailers'])

    def test_weekly_api_all_countries_uses_one_saved_snapshot_query(self):
        self.refresh(country='SEA')
        self.refresh(country='SEG')
        with self.assertNumQueries(1):
            response = api.weekly(self.factory.get('/', {
                'date': '2026-09-20', 'country': 'ALL', 'product': 'REF', 'weeks': '1',
            }))
        self.assertEqual(200, response.status_code)
        payload = json.loads(response.content)
        self.assertEqual({'SEA', 'SEG'}, {row['country'] for row in payload['weeks'][0]['rows']})
        self.assertEqual(['Lowes'], payload['retailers'])

    def test_alert_api_one_query_saved_decision_only(self):
        self.refresh(self.end - timedelta(days=7))
        self.refresh(loader=lambda *_: check_for(400))
        with self.assertNumQueries(1):
            response = api.alerts(self.factory.get('/', {'date': '2026-09-21'}))
        payload = json.loads(response.content)
        self.assertEqual('2026-09-20', payload['snapshots'][0]['source_date'])
        self.assertEqual('VOLUME_HIGH', payload['snapshots'][0]['rows'][0]['alerts'][0]['status'])

    def test_stale_same_day_and_failed_snapshots_are_unavailable(self):
        now = timezone.now()
        day = timezone.localdate(timezone=tz(timedelta(hours=9)))
        Daily.objects.create(country='SIEL', inspection_date=day, source_date=day,
            rows=[sample()], digest='a', updated_at=now - timedelta(hours=2))
        payload = json.loads(api.alerts(self.factory.get('/', {'date': str(day)})).content)
        self.assertFalse(payload['snapshots'][0]['available'])

    def test_filters_and_invalid_input(self):
        self.refresh()
        for params in [{'country': 'INVALID'}, {'weeks': 13}, {'weeks': 0}, {'date': 'bad'}, {'product': 'DROP'}]:
            with self.subTest(params=params), self.assertNumQueries(0):
                self.assertEqual(400, api.weekly(self.factory.get('/', params)).status_code)
        response = api.weekly(self.factory.get('/', {'country': 'SEA', 'product': 'TV', 'date': '2026-09-20'}))
        self.assertTrue(all(not week['rows'] for week in json.loads(response.content)['weeks']))

    def test_unknown_snapshot_is_not_returned_as_normal(self):
        with self.assertNumQueries(1):
            payload = json.loads(api.alerts(self.factory.get('/', {'date': '2026-09-21'})).content)
        self.assertEqual([], payload['snapshots'])

    def test_model_and_migration_agree(self):
        call_command('makemigrations', 'dx_layer1', check=True, dry_run=True, verbosity=0)

    def test_automatic_refresh_current_countries_first_then_bounded_history(self):
        calls = []
        def refresh(country, start, end, **kwargs):
            calls.append((country, start, end))
            return {'updated': 0, 'errors': 0, 'busy': False}
        errors = automatic.refresh_automatic(date(2026, 9, 22), countries=['SEA', 'SEG'], refresh=refresh)
        self.assertEqual(0, errors)
        self.assertEqual(['SEA', 'SEG', 'SEA', 'SEG'], [c[0] for c in calls])
        self.assertEqual(date(2026, 9, 21), calls[0][2])
        self.assertEqual(date(2026, 9, 22), calls[1][2])
        self.assertEqual(13, (calls[2][2] - calls[2][1]).days)
        self.assertEqual(date(2026, 9, 18), calls[2][2])

    def test_automatic_skips_history_after_source_failure_or_busy_lease(self):
        for result in [{'updated': 0, 'errors': 1, 'busy': False}, {'updated': 0, 'errors': 0, 'busy': True}]:
            with patch.object(automatic, 'refresh_country', return_value=result) as refresh:
                automatic.refresh_automatic(date(2026, 9, 22), countries=['SEA'])
                self.assertEqual(1, refresh.call_count)

    def test_automatic_does_not_repeat_completed_history(self):
        last_due = date(2026, 9, 21)
        Daily.objects.bulk_create([Daily(country='SEA', source_date=last_due - timedelta(days=i),
            inspection_date=last_due - timedelta(days=i - 1), rows=[], digest='fixture', updated_at=timezone.now())
            for i in range(3, 112)])
        self.assertIsNone(automatic.history_range('SEA', last_due))
        Daily.objects.filter(source_date=date(2026, 9, 10)).update(refresh_error=True)
        self.assertEqual((date(2026, 9, 10), date(2026, 9, 10)), automatic.history_range('SEA', last_due))


if __name__ == '__main__':
    raise SystemExit(bool(DiscoverRunner(verbosity=1).run_tests(['__main__'])))
