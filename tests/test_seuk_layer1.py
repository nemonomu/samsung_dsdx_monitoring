"""UK Layer 1 onboarding; isolated SQLite and mock source cursors only."""
import json
import sys
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.test_collection_statistics_backend import sample, Daily, calc, collector, automatic
from django.test import TestCase
from django.test.runner import DiscoverRunner
from apps.common import seuk_retail as policy
from apps.common.inspection_dates import resolve_monitoring_date, SOURCE_DEFINITIONS
from apps.common.source_dates import source_date_value, source_date_sql
from apps.dx.dx_layer1.seuk_retail.seuk_retail_services import get_layer1_stats
from apps.dx.dx_layer1.collection_statistics import live
from apps.dx.dx_layer1.column_statistics import services as columns
from apps.dx.dx_layer1.column_statistics.comparison import collection_complete, compare_columns
from apps.dx.dx_layer1.collection_issues import services as issues, queries
from apps.dx.dx_layer1.common import retail_batches


class SeukLayer1Tests(TestCase):
    day = date(2026, 10, 25)

    def check(self, day=None, total=309, main=290, bsr=100, now=None):
        cursor = Mock()
        cursor.fetchone.return_value = (total, main, bsr, 'currys_batch')
        return get_layer1_stats(cursor, day or self.day,
            now or datetime(2026, 11, 1, 5, tzinfo=policy.KST))['check']

    def test_original_source_day_and_four_tables(self):
        self.assertFalse(any(country == 'SEUK' for _, country, _ in SOURCE_DEFINITIONS))
        for key, source in policy.SEUK_SOURCE_CONFIG.items():
            self.assertEqual('2026-10-25', resolve_monitoring_date(self.day, 'SEUK', key)['source_date'])
            cte, scope, params = policy.latest_scope(source, '2026-10-21', '2026-10-25')
            self.assertEqual(['2026-10-25', '2026-10-25', 'currys', 'currys'], params)
            self.assertIn('anchor.id DESC', cte)
            self.assertIn(source_date_sql('anchor.crawl_datetime'), cte)
            self.assertIn('latest.source_date', scope)
            self.assertNotIn('AT TIME ZONE', cte + scope)
            self.assertNotIn('page_type', cte + scope)
        self.assertEqual('2026-10-25', source_date_value('2026-10-25T23:59:59-04:00'))
        self.assertEqual('2026-10-24', source_date_value('2026-10-24T23:59:59+09:00'))

    def test_schedule_boundaries_and_start_date(self):
        self.assertEqual(date(2026,10,25), policy.FIRST_SOURCE_DATE)
        for hour, minute, phase in ((0,59,'pending'),(1,0,'collecting'),(3,59,'collecting'),(4,0,'complete')):
            now = datetime(2026,10,25,hour,minute,tzinfo=policy.KST)
            self.assertEqual(phase, policy.collection_phase(self.day, now))
            self.assertEqual(phase, policy.collection_phase(self.day, now.astimezone(timezone.utc)))
            self.assertEqual(phase == 'complete', collection_complete('SEUK','TV','Currys',self.day,now))
        cursor = Mock()
        before = get_layer1_stats(cursor, date(2026,10,24), datetime(2026,10,24,5,tzinfo=policy.KST))['check']
        cursor.execute.assert_not_called()
        self.assertEqual('PENDING', before['status'])
        self.assertEqual([], calc.normalize_check(before, 'SEUK', date(2026,10,24)))
        self.assertEqual({}, queries.raw_counts('SEUK','TV','Currys',date(2026,10,21),date(2026,10,24)))
        self.assertEqual((self.day, 'registered'), issues.coverage_start('SEUK','TV','Currys'))
        for day in (date(2026,10,23), date(2026,10,24)):
            cursor = Mock()
            result = get_layer1_stats(cursor, day, datetime(2026,10,26,5,tzinfo=policy.KST))
            cursor.execute.assert_not_called()
            self.assertEqual([], result['failed_items'])
            self.assertEqual('PENDING', result['check']['status'])
            self.assertEqual('2026-10-25', result['check']['active_from'])
            self.assertIn('2026-10-25 시작', result['check']['description'])

    def test_total_is_not_main_plus_bsr_and_missing_after_deadline(self):
        check = self.check()
        self.assertEqual(309 * 4, check['actual'])
        rows = calc.normalize_check(check,'SEUK',self.day)
        self.assertEqual(4,len(rows))
        self.assertTrue(all((r['main'],r['bsr'],r['total']) == (290,100,309) for r in rows))
        missing = self.check(total=0,main=0,bsr=0)
        self.assertEqual('CRITICAL',missing['status'])
        compared = calc.compare_rows(calc.normalize_check(missing,'SEUK',self.day),[],'SEUK')
        self.assertTrue(all(r['bsr_comparison_state'] == 'missing' for r in compared))

    def test_dashboard_excludes_prelaunch_from_inspection_targets(self):
        from apps.dx.dx_layer1.dashboard import services
        from apps.dx.dx_layer1.common.services import get_target_sections
        from apps.common import dx_schedules
        schedules=[dict(check_type='seuk_retail',schedule_type='daily')]
        with patch.object(dx_schedules,'load_collection_schedules',return_value=schedules):
            self.assertEqual(0, get_target_sections('2026-10-24'))
            self.assertEqual(1, get_target_sections('2026-10-25'))
        with patch.object(services,'load_collection_schedules',return_value=schedules):
            before=services._get_active_services(date(2026,10,24))
            after=services._get_active_services(self.day)
        self.assertIn('seuk_retail',dict(before[0]))
        self.assertNotIn('seuk_retail',before[2])
        self.assertIn('seuk_retail',after[2])

    def test_fixed_100_for_all_products_before_and_after_observation(self):
        for product in ('TV', 'REF', 'LDY', 'LDY_DRYER'):
            row = sample(retailer='Currys', product=product, main=300, bsr=100)
            history = [dict(row, source_date=str(self.day+timedelta(days=i))) for i in range(5)]
            for old in ([], history):
                for count in (0, 99, 100, 101):
                    current = calc.compare_rows([dict(row, bsr=count)], old, 'SEUK')[0]
                    self.assertEqual('ready', current['bsr_comparison_state'])
                    self.assertEqual('fixed_100', current['bsr_rule'])
                    self.assertEqual(count != 100, any(a['metric']=='bsr' for a in current['alerts']))
                    self.assertTrue(calc.comparison_rules(current, 'SEUK')['bsr']['exact'])
            dropped = calc.compare_rows([dict(row, main=200)], history, 'SEUK')[0]
            self.assertEqual(['main'], [a['metric'] for a in dropped['alerts']])
            stale = dict(dropped, bsr_comparison_state='policy_pending', bsr_rule='undecided')
            self.assertEqual('ready', calc.current_volume_decision(stale, 'SEUK')['bsr_comparison_state'])

    def test_column_counts_include_types_and_use_latest_original_day(self):
        self.assertEqual(4,len([s for s in columns.catalog() if s['country']=='SEUK']))
        for key, config in policy.SEUK_SOURCE_CONFIG.items():
            source = columns.select_source('SEUK',config['category'],'Currys')
            fields = columns.ordered_columns(config['columns'])
            self.assertEqual(11 if key=='seuk_tv' else 12,len(fields))
            sql, params = columns.query_spec(source,source['retailers'][0],fields,date(2026,10,1),self.day)
            self.assertEqual(['currys','2026-10-25','2026-10-25','currys'],params)
            self.assertIn('latest.chosen_batch',sql)
            self.assertIn(source_date_sql('source.crawl_datetime'),sql)
            self.assertNotIn('AT TIME ZONE',sql)
            if key in ('seuk_ldy','seuk_ldy_dryer'):
                self.assertIn('loading_type',fields)
                self.assertIn('capacity',fields)
            if key=='seuk_ref': self.assertIn('ref_refrigerator_type',fields)
        cursor=Mock()
        fields=columns.ordered_columns(policy.SEUK_SOURCE_CONFIG['seuk_tv']['columns'])
        cursor.fetchall.return_value=[('2026-10-25',300,*([300]*len(fields)))]
        @contextmanager
        def connection(): yield None,cursor
        with patch.object(columns,'dx_connection',connection):
            result=columns.daily_counts('SEUK','TV','Currys',self.day,5)
        self.assertEqual([0,0,0,0,300],[day['total'] for day in result['daily']])
        self.assertEqual('2026-10-25',result['active_from'])
        completed={day['date']:day['date']>='2026-10-25' for day in result['daily']}
        self.assertTrue(all(r['status']=='not_scheduled' for r in compare_columns(result,date(2026,10,24),completed)))

    def test_batch_detail_sql_uses_exact_date(self):
        cursor=Mock()
        cursor.fetchall.return_value=[('old','t1','t1',200,80,False,210),('new','t2','t2',290,100,True,309)]
        cursor.mogrify.return_value=b'SELECT *;'
        result=retail_batches.fetch_batch_details(cursor,'seuk_retail','seuk_ldy','2026-10-25','Currys')
        self.assertEqual([False,True],[r['applied'] for r in result['batches']])
        self.assertIn(source_date_sql('crawl_datetime'),cursor.execute.call_args.args[0])
        self.assertIn(source_date_sql('crawl_datetime')+' = %s',cursor.mogrify.call_args.args[0])

    def test_collector_live_and_backlog_never_use_trial_days(self):
        loader=Mock(side_effect=lambda country,day:self.check(day))
        before=collector.refresh_country('SEUK',date(2026,10,18),date(2026,10,24),loader=loader,today=date(2026,10,24))
        self.assertEqual(0,before['updated'])
        loader.assert_not_called()
        self.assertIsNone(automatic.history_range('SEUK',date(2026,10,24)))
        trial=[sample(retailer='Currys',product='TV',observation_state='ready',observation_days=5)]
        for trial_day in (date(2026,10,23), date(2026,10,24)):
            Daily.objects.create(country='SEUK',inspection_date=trial_day,source_date=trial_day,rows=trial,digest='trial',updated_at=datetime.now(timezone.utc))
        result=collector.refresh_country('SEUK',date(2026,10,21),date(2026,10,25),loader=loader,today=self.day)
        self.assertEqual(0,result['errors'])
        self.assertEqual([self.day],[c.args[1] for c in loader.call_args_list])
        with patch.object(live,'load_current_check',return_value=self.check()):
            snapshot=live.current_snapshot('SEUK',self.day)
        self.assertTrue(all(r['observation_prior_days']==0 for r in snapshot['rows']))
        self.assertTrue(all(set(r['rules']) == {'bsr'} and r['rules']['bsr']['exact'] for r in snapshot['rows']))

    def test_registration_sql_parses_and_does_not_write_source_data(self):
        try:
            from pglast import parse_sql, parse_plpgsql
        except ImportError:
            self.skipTest('Optional PostgreSQL syntax parser pglast is not installed')
        sql=(Path(__file__).resolve().parents[1]/'sql/setup_seuk_layer1.sql').read_text(encoding='utf-8')
        self.assertTrue(parse_sql(sql))
        self.assertTrue(parse_plpgsql(sql))
        self.assertNotIn('UPDATE dx_seuk.',sql)
        self.assertNotIn('DELETE FROM',sql)
        self.assertNotIn('monitoring_null_column',sql)
        self.assertEqual(79,sum(len(c['columns']) for c in policy.SEUK_SOURCE_CONFIG.values()))
        update_sql=(Path(__file__).resolve().parents[1]/'sql/set_seuk_start_20261025.sql').read_text(encoding='utf-8')
        self.assertTrue(parse_sql(update_sql))
        self.assertTrue(parse_plpgsql(update_sql))
        self.assertNotIn('UPDATE dx_seuk.',update_sql)
        self.assertNotIn('DELETE FROM',update_sql)


if __name__=='__main__':
    sys.exit(bool(DiscoverRunner(verbosity=1).run_tests([__name__])))
