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
            states = {alert['status'] for alert in row['alerts']}
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

    def test_unsupported_bsr_not_zero_and_raw_total_not_main_plus_bsr(self):
        rows = calc.normalize_check(check_for(300, raw_count=320), 'SEG', date(2026, 9, 21))
        self.assertEqual((300, 100, 320), (rows[0]['main'], rows[0]['bsr'], rows[0]['total']))
        rows = calc.normalize_check(check_for(300, bsr_applicable=False, actual=300, raw_count=315), 'TSE', date(2026, 9, 21))
        self.assertIsNone(rows[0]['bsr'])
        self.assertEqual(300, rows[0]['total'])
        rows = calc.normalize_check(check_for(300, actual=300, raw_count=315), 'SEM', date(2026, 9, 21))
        self.assertEqual(300, rows[0]['total'])

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
