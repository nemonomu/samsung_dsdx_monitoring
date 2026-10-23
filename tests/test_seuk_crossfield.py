"""SEUK GBP cross-field rules, original-date scope, review and UI fixtures."""
import json
import sys
import unittest
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests import test_collection_statistics_backend  # isolated settings
from tests.unit.support import ScriptedCursor
from django.template import Engine, Context
from django.test import RequestFactory, override_settings
from apps.common.seuk_retail import SEUK_SOURCE_CONFIG, FIRST_SOURCE_DATE
from apps.common.source_dates import source_date_sql
from apps.dx.dx_layer3.cross_field import seuk_services as svc, api
from apps.dx.dx_layer3.common import context
from apps.dx.dx_layer3.dashboard import api as dashboard_api
from apps.dx.dx_layer3.data_edit import services as edits


DAY=date(2026,10,26)


def row(**changes):
    result=dict(id=2,item='A',sku='SKU',retailer_sku_name='Product A',account_name='Currys',
        crawl_datetime='2026-10-26T23:59:59-04:00',batch_id='current',
        final_sku_price='£1399.00',original_sku_price='£1799.99',savings='£400.99',
        star_rating='4.5',count_of_reviews='8',count_of_star_ratings='8',product_url='https://example.test/a')
    result.update(changes)
    return result


class Cursor:
    def __init__(self,product='seuk_tv',confirmed=False):
        self.product=product
        self.confirmed=confirmed
        self.calls=[]

    def execute(self,query,params=None):
        self.query=query
        self.calls.append((query,params))

    def fetchall(self):
        if 'monitoring_validation_rules' in self.query:
            return [(i,self.product+'_'+key,key,'Currys') for i,key in enumerate(svc.RULES,1)]
        if 'SELECT source.*' in self.query:
            return [row(id=1,crawl_datetime='2026-10-25T23:59:59-04:00'),row(savings='£400.00')]
        if 'monitoring_corrections' in self.query and self.confirmed:
            return [(2,7,'savings','checked','normal','tester','2026-10-26')]
        return []


def fixture(product='seuk_tv'):
    with patch.object(svc,'exclude_page_absent_records',side_effect=lambda _,__,rows,**kwargs:(rows,[])):
        return dict(summary=svc.get_seuk_cross_field_summary(Cursor(product),DAY,product),
                    detail=svc.get_seuk_cross_field_rule_detail(Cursor(product),DAY,product,7,3))


class SeukCrossfieldTests(unittest.TestCase):
    def test_gbp_amounts_and_exact_pennies(self):
        self.assertEqual(set(),svc.evaluate_seuk_row(row()))
        self.assertEqual(Decimal('1799.99'),svc._money('£1,799.99'))
        self.assertEqual(set(),svc.evaluate_seuk_row(row(final_sku_price='£0.10',original_sku_price='£0.30',savings='£0.20')))
        self.assertEqual({'savings_amount_match'},svc.evaluate_seuk_row(row(savings='£400.98')))
        self.assertEqual({'savings_missing'},svc.evaluate_seuk_row(row(final_sku_price='£999.99',original_sku_price='£1000.00',savings=None)))
        for value in ('23%','1.799,99 €','£1,79.99','n/a','£NaN'):
            self.assertIsNone(svc._money(value))
        self.assertNotIn('savings_amount_match',svc.evaluate_seuk_row(row(savings='23%')))

    def test_seven_rules_and_no_dependent_price_cascade(self):
        cases={
            'review_count_match':dict(count_of_reviews='7'),
            'rating_count_presence':dict(star_rating='0'),
            'final_original_price':dict(final_sku_price='£1799.99'),
            'savings_missing':dict(savings=' '),
            'original_missing':dict(original_sku_price=None),
            'final_missing':dict(final_sku_price=None),
            'savings_amount_match':dict(savings='£10.00'),
        }
        self.assertEqual(set(cases),set(svc.RULES))
        for key,changes in cases.items():
            self.assertEqual({key},svc.evaluate_seuk_row(row(**changes)),key)
        self.assertEqual(set(),svc.evaluate_seuk_row(row(star_rating='0',count_of_reviews='0',count_of_star_ratings='0')))
        self.assertEqual(set(),svc.evaluate_seuk_row(row(final_sku_price='£10.00',original_sku_price=None,savings=None)))
        self.assertEqual(set(),svc.evaluate_seuk_row(row(count_of_reviews='1,234',count_of_star_ratings='1234')))

    def test_all_products_summary_history_and_exact_date_sql(self):
        for product,source in SEUK_SOURCE_CONFIG.items():
            result=fixture(product)
            summary,detail=result['summary'],result['detail']
            self.assertEqual(7,len(summary['rule_summary']))
            self.assertEqual((1,1,1),(summary['total_checked'],summary['failed_records'],summary['total_anomalies']))
            self.assertEqual(['comparison_history','target'],[r['row_role'] for r in detail['anomalies']])
            self.assertEqual('2026-10-26',detail['source_date'])
            self.assertEqual(product.upper(),detail['product_line'])
            query=svc.display_query(source,DAY,30,["A'B"])
            self.assertIn(str(FIRST_SOURCE_DATE),query)
            self.assertIn(source_date_sql('anchor.crawl_datetime'),query)
            self.assertIn('source.batch_id IS NOT DISTINCT FROM latest.batch_id',query)
            self.assertIn("'A''B'",query)
            self.assertNotIn('AT TIME ZONE',query)

    def test_normal_confirmation_removes_only_matching_current_finding(self):
        with patch.object(svc,'exclude_page_absent_records',side_effect=lambda _,__,rows,**kwargs:(rows,[])):
            result=svc.get_seuk_cross_field_summary(Cursor(confirmed=True),DAY,'seuk_tv')
        self.assertEqual(0,result['total_anomalies'])
        self.assertEqual(1,result['total_checked'])

    def test_prelaunch_never_reads_source_and_rules_are_test_isolated(self):
        cursor=Mock()
        self.assertEqual([],svc._load_rows(cursor,SEUK_SOURCE_CONFIG['seuk_tv'],'2026-10-01','2026-10-24'))
        cursor.execute.assert_not_called()
        cursor.fetchall.return_value=[]
        with override_settings(DEBUG=True): svc.load_active_rules(cursor,SEUK_SOURCE_CONFIG['seuk_tv'])
        self.assertIn('public.test_monitoring_validation_rules',cursor.execute.call_args.args[0])

    def test_detail_api_routes_all_four_products(self):
        @contextmanager
        def connection(): yield Mock(),Mock()
        for product in SEUK_SOURCE_CONFIG:
            request=RequestFactory().get('/',dict(date=str(DAY),type=product,rule_id=7,days=3))
            with patch.object(api,'dx_connection',connection),patch.object(svc,'get_seuk_cross_field_rule_detail',return_value={'found':True,'source_date':str(DAY)}) as handler:
                response=api.cross_field_detail(request)
            self.assertEqual(str(DAY),json.loads(response.content)['source_date'])
            self.assertEqual((DAY,product,'7',3),handler.call_args.args[1:])

    def test_dashboard_counts_each_product_once(self):
        @contextmanager
        def connection(): yield Mock(),Mock()
        for product in SEUK_SOURCE_CONFIG:
            request=RequestFactory().get('/',dict(date=str(DAY),type=product,section='cross_field'))
            summary=fixture(product)['summary']
            with patch.object(dashboard_api,'dx_connection',connection),patch.object(svc,'get_seuk_cross_field_summary',return_value=summary) as handler:
                result=json.loads(dashboard_api.layer_stats(request).content)
            self.assertNotIn('error',result)
            self.assertEqual([product],[check['detail_code'] for check in result['checks']])
            self.assertEqual(1,result['summary']['total_checked'])
            self.assertEqual(1,result['summary']['failed'])
            handler.assert_called_once()

    def test_edits_and_reviews_lock_the_latest_original_day(self):
        table=SEUK_SOURCE_CONFIG['seuk_tv']['table_name']
        cursor=ScriptedCursor([{'fetchone':('£400.00','current','Currys','A')},{'rowcount':1},{'rowcount':1}])
        result=edits.update_cell_value(cursor,Mock(),table,2,'savings','£400.99',str(DAY),'cross_field','tester','',7)
        self.assertTrue(result['success'])
        self.assertIn('FOR UPDATE OF source',cursor.calls[0][0])
        self.assertIn('source.batch_id',cursor.calls[0][0])
        self.assertEqual(['2026-10-26','2026-10-26','currys','currys',2],cursor.calls[0][1])
        cursor=ScriptedCursor([{'fetchone':('£400.00','Currys','A')},{'fetchone':None},{'rowcount':1}])
        with patch.object(svc,'load_active_rules',return_value=[{'rule_id':7}]):
            result=edits.save_review(cursor,Mock(),table,2,'savings','normal','','checked',str(DAY),'cross_field','tester',7)
        self.assertTrue(result['success'])
        self.assertIn('source.id = %s FOR UPDATE OF source',cursor.calls[0][0])
        self.assertEqual(7,cursor.calls[-1][1][-1])
        cursor=ScriptedCursor([{'fetchone':None}])
        result=edits.update_cell_value(cursor,Mock(),table,1,'savings','£1.00',str(DAY),'cross_field','tester','',7)
        self.assertEqual(404,result['status'])
        self.assertEqual(1,len(cursor.calls))
        for column,kind in [('sku','cross_field'),('savings','field_missing')]:
            cursor=ScriptedCursor([])
            self.assertEqual(403,edits.update_cell_value(cursor,Mock(),table,2,column,'x',str(DAY),kind,'tester','')['status'])
        with patch.object(svc,'load_active_rules',return_value=[{'rule_id':7}]):
            cursor=ScriptedCursor([])
            self.assertEqual(400,edits.save_review(cursor,Mock(),table,2,'savings','normal','','checked',str(DAY),'cross_field','tester',99)['status'])
            self.assertEqual([],cursor.calls)

    def test_sidebar_flag_and_active_crossfield_children(self):
        rules=[dict(section_code=s['section_code'],section_name=s['display_name']) for s in SEUK_SOURCE_CONFIG.values()]
        with patch.object(context,'load_crossfield_rules',return_value=rules),patch.object(context,'load_timeseries_rules',return_value=[]),patch.object(context,'load_category_rules',return_value=[]):
            items=context._get_sidebar_items()['cross_field']
        group=next(i for i in items if isinstance(i,dict) and i['name']=='SEUK Retail')
        self.assertEqual(list(SEUK_SOURCE_CONFIG),[i['detail_code'] for i in group['children']])
        template=Engine().from_string(Path('templates/includes/_sidebar.html').read_text(encoding='utf-8'))
        for item in (group,{'name':'SEUK Retail'}):
            html=template.render(Context({'sidebar_groups':[{'key':'cross_field','items':[item]}]}))
            self.assertIn('/static/img/flags/gb.svg',html)

    def test_registration_sql_parses_and_matches_seven_rule_specs(self):
        from pglast import parse_sql,parse_plpgsql
        sql=Path('sql/setup_seuk_crossfield.sql').read_text(encoding='utf-8')
        self.assertTrue(parse_sql(sql))
        self.assertTrue(parse_plpgsql(sql))
        for key,spec in svc.RULES.items():
            self.assertIn("'"+key+"'",sql)
            self.assertIn(spec[3],sql)
        self.assertNotIn('UPDATE dx_seuk.',sql)
        self.assertNotIn('DELETE FROM',sql)


if __name__=='__main__': unittest.main()
