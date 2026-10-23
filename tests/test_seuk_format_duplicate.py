"""SEUK format/duplicate integration; mocked source DB only."""
import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests import test_collection_statistics_backend  # isolated Django settings
from tests.unit.support import ScriptedCursor
from apps.common import seuk_retail as policy
from apps.dx.dx_layer2 import seuk_format_validation as fmt, seuk_duplicate_validation as dup
from apps.dx.dx_layer2 import seuk_null_validation as nulls, retail_duplicate_edit as duplicate_edit
from apps.dx.dx_layer2.format_validation import services as formats, review_service as reviews
from apps.dx.dx_layer2.anomaly_validation import services as anomalies
from apps.dx.dx_layer2.data_edit import services as edits

DAY = policy.FIRST_SOURCE_DATE
EXCLUDED = {'item','product_url','crawl_datetime','calendar_week','main_rank','bsr_rank','screen_size'}


def record(**changes):
    row = dict(id=42, country='SEUK', account_name='Currys', item='123', sku='MODEL',
               batch_id='latest', crawl_datetime=f'{DAY}T23:59:59-04:00',
               final_sku_price='£1399.00', original_sku_price='£1799.99', savings='£400.99',
               count_of_reviews='1', count_of_star_ratings='1', star_rating='4.8',
               ref_capacity='605L', ref_refrigerator_type='French Door',
               capacity='9kg', loading_type='Front loading')
    row.update(changes)
    return row


class SeukFormatDuplicateTests(unittest.TestCase):
    def test_exact_column_scope_and_exclusions(self):
        for product, count in [('tv',8),('ref',10),('ldy',10),('ldy_dryer',10)]:
            key = 'seuk_' + product
            self.assertEqual(count, len(fmt.get_format_columns(key)))
            self.assertFalse(EXCLUDED.intersection(fmt.get_format_columns(key)))
            self.assertFalse(EXCLUDED.intersection(fmt.get_format_editable_columns(key)))
            self.assertEqual([], fmt.evaluate_format(record(**dict.fromkeys(EXCLUDED,'INVALID')), key))
            self.assertEqual([], fmt.evaluate_format(dict.fromkeys(fmt.get_format_columns(key), ' '), key))

    def test_uk_money_counts_ratings_and_capacities(self):
        for value in ('£0.00','£1399.00','£1,399.00','£400.99'):
            self.assertEqual([],fmt.evaluate_format({'final_sku_price':value},'seuk_tv'))
        for value in ('1399.00','£1.399,00','£1,39.00','£-1.00','20%','£1.000','£NaN'):
            self.assertEqual(['savings'],fmt.evaluate_format({'savings':value},'seuk_tv'))
        for field,value in [('count_of_reviews','-1'),('count_of_star_ratings','1.5'),('star_rating','5.1')]:
            self.assertEqual([field],fmt.evaluate_format({field:value},'seuk_tv'))
        self.assertEqual([],fmt.evaluate_format({'star_rating':'5','count_of_reviews':'0'},'seuk_tv'))
        self.assertEqual([],fmt.evaluate_format({'capacity':'10kg, 6kg'},'seuk_ldy'))
        self.assertEqual(['capacity'],fmt.evaluate_format({'capacity':'10kg, 6kg'},'seuk_ldy_dryer'))
        self.assertEqual(['loading_type'],fmt.evaluate_format({'loading_type':'arbitrary'},'seuk_ldy'))

    def test_detail_counts_history_and_original_date(self):
        source=policy.SEUK_SOURCE_CONFIG['seuk_tv']
        rows=[record(savings='20%'),record(id=43,item=None,savings='30%')]
        mapping=nulls._mapping(DAY,source)
        past=record(id=1,savings='£1.00',crawl_datetime='2026-10-22T23:59:59-04:00')
        with patch.object(nulls,'latest_rows',return_value=(rows,mapping)), \
             patch.object(fmt,'_normal_reviews',return_value={}), \
             patch.object(nulls,'_history_rows',return_value=[past,rows[0]]):
            result=formats._get_format_detail_raw(Mock(),DAY,'seuk_tv_retail','Currys',3)
            self.assertEqual({'savings':2},result['field_counts'])
            self.assertEqual([1,42,43],[r['id'] for r in result['results']])
            self.assertEqual(str(DAY),result['results'][1]['_source_date'])
            self.assertEqual(str(DAY),result['active_from'])
            self.assertIn('savings',result['results'][1]['error_details'])
            stats={'tables':[]}
            self.assertEqual(2,fmt.append_format_stats(Mock(),DAY,stats,'seuk_tv_retail'))
        with patch.object(nulls,'latest_rows',return_value=(rows,mapping)), \
             patch.object(fmt,'_normal_reviews',return_value={'42_savings':{'memo':'checked'}}):
            result=fmt.format_detail(Mock(),DAY,'seuk_tv_retail')
            self.assertEqual([43],result['target_ids'])
            self.assertEqual(1,result['total_format_count'])

    def test_duplicates_group_by_item_only_and_empty_day_is_pending(self):
        source=policy.SEUK_SOURCE_CONFIG['seuk_tv']
        mapping=nulls._mapping(DAY,source)
        rows=[record(main_rank=1,bsr_rank=1),record(id=43),record(id=44,item='other'),record(id=45,item='')]
        with patch.object(dup,'latest_rows',return_value=(rows,mapping)):
            result=anomalies._get_anomaly_detail(Mock(),DAY,'seuk_tv_retail','Currys',1,1,50)
            self.assertEqual(1,result['results']['total_groups'])
            self.assertEqual(2,result['results']['duplicates'][0]['dup_count'])
            self.assertFalse(result['allow_cleanup'])
            self.assertEqual(['sku'],result['editable_cols'])
        with patch.object(dup,'latest_rows',return_value=([],mapping)):
            stats={'tables':[]}
            self.assertEqual(0,dup.append_duplicate_stats(Mock(),DAY,stats,'seuk_tv_retail'))
            self.assertEqual('PENDING',stats['tables'][0]['status'])

    def test_source_scope_is_latest_original_day_and_start_date_is_unchanged(self):
        self.assertEqual(date(2026,10,23),DAY)
        source=policy.SEUK_SOURCE_CONFIG['seuk_tv']
        cursor=Mock(description=[('id',)])
        cursor.fetchall.return_value=[]
        duplicate_edit.scoped_rows(cursor,DAY,'SEUK',source,'Currys')
        sql,params=cursor.execute.call_args.args
        self.assertIn('anchor.id DESC',sql)
        self.assertIn('source.batch_id IS NOT DISTINCT FROM latest.batch_id',sql)
        self.assertNotIn('AT TIME ZONE',sql)
        self.assertEqual([str(DAY),str(DAY),'currys','currys'],params)

    def test_format_edits_are_scoped_audited_and_exclusions_rejected(self):
        source=policy.SEUK_SOURCE_CONFIG['seuk_ref']
        for field in ('savings','ref_refrigerator_type'):
            cursor=ScriptedCursor([{'fetchone':('old','Currys','123','latest')},{},{}])
            result=edits.update_cell_value(cursor,Mock(),source['table_name'],42,field,'new',str(DAY),'format','tester','checked')
            self.assertTrue(result['success'],result)
            self.assertIn('FOR UPDATE OF source',cursor.calls[0][0])
            self.assertIn('format_check',cursor.calls[-1][1])
        for field in EXCLUDED:
            cursor=ScriptedCursor([])
            result=edits.update_cell_value(cursor,Mock(),source['table_name'],42,field,'new',str(DAY),'format','tester','')
            self.assertEqual(403,result['status'])
            self.assertEqual([],cursor.calls)
        cursor=ScriptedCursor([{'fetchone':None}])
        result=edits.update_cell_value(cursor,Mock(),source['table_name'],42,'savings','£1.00',str(DAY),'format','tester','')
        self.assertEqual(404,result['status'])

    def test_duplicate_sku_edit_checks_current_scope_and_audits(self):
        source=policy.SEUK_SOURCE_CONFIG['seuk_ldy_dryer']
        for rows,expected in [([{'id':42}],True),([],False)]:
            cursor=ScriptedCursor([{'fetchone':('old','Currys','123')},{},{}])
            with patch.object(duplicate_edit,'scoped_rows',return_value=rows):
                result=edits.update_cell_value(cursor,Mock(),source['table_name'],42,'sku','new',str(DAY),'duplicate','tester','checked')
            if expected:
                self.assertTrue(result['success'])
                self.assertIn('duplicate_check',cursor.calls[-1][1])
            else:
                self.assertEqual(404,result['status'])
                self.assertEqual(1,len(cursor.calls))

    def test_normal_approval_is_shared_exactly_and_revocation_applies(self):
        def data(product):
            return dict(table='seuk_'+product+'_retail',retailer=' Currys ',actual_table='dx_seuk.dx_seuk_'+product+'_retail_com',
                        date=str(DAY),validation_fields=['savings'],target_ids=[42],normal_reviews={},
                        results=[dict(record(savings='20%'),error_fields=['savings'])])
        origin=reviews.context_for(data('tv'))
        key=reviews.group_key('savings','20%')
        approval=dict(action='normal',date=str(DAY),event_id=1,is_del=False,shared_normal=True)
        scope=SimpleNamespace(context=origin,policies={key:approval},revision=1)
        scopes={reviews.digest(origin):scope}
        for product in ('tv','ref','ldy','ldy_dryer'):
            table=data(product)
            self.assertTrue(reviews.supported(table['table']))
            self.assertEqual(0,reviews.apply_detail(table,scopes)['total_format_count'])
        other=data('ref');other['results'][0]['savings']='20% '
        self.assertEqual(1,reviews.apply_detail(other,scopes)['total_format_count'])
        isolated=data('ref');isolated['retailer']='Other'
        self.assertEqual(1,reviews.apply_detail(isolated,scopes)['total_format_count'])
        scope.context={**origin,'environment':'different'}
        self.assertEqual(1,reviews.apply_detail(data('ref'),scopes)['total_format_count'])
        scope.context=origin
        approval['is_del']=True
        self.assertEqual(1,reviews.apply_detail(data('ref'),scopes)['total_format_count'])
        approval.update(action='error',is_del=False,record_ids=[42],reason='confirmed')
        self.assertEqual({},reviews.effective_policies(reviews.context_for(data('ref')),scopes,str(DAY)))

    def test_api_allowlists_and_rule_examples(self):
        for key,source in policy.SEUK_SOURCE_CONFIG.items():
            self.assertIn(source['section_code'],formats.VALID_TABLES_FORMAT)
            self.assertIn(key,formats.VALID_TABLES_RULES)
            self.assertIn(source['section_code'],anomalies.VALID_TABLES_ANOMALY)
            rules=formats.get_format_rules(Mock(),key,'Currys')['rules']
            self.assertEqual(set(fmt.get_format_columns(key)),{r['field'] for r in rules})
            for rule in rules:
                self.assertTrue(rule['examples'],rule)
                for value in rule['examples']:
                    self.assertEqual([],fmt.evaluate_format({rule['field']:value},key))

    def test_dashboard_scoped_stats_dispatch_once(self):
        source=policy.SEUK_SOURCE_CONFIG['seuk_tv']
        mapping=nulls._mapping(DAY,source)
        with patch.object(nulls,'latest_rows',return_value=([record(savings='20%')],mapping)), \
             patch.object(fmt,'_normal_reviews',return_value={}), \
             patch.object(reviews,'load_scopes',return_value={}):
            result,count=formats.get_format_stats(Mock(),DAY,category=source['section_code'])
            self.assertEqual(1,count)
            self.assertEqual([source['section_code']],[r['table'] for r in result['tables']])
        with patch.object(dup,'latest_rows',return_value=([record(),record(id=43)],mapping)):
            result,count=anomalies.get_anomaly_stats(Mock(),DAY,category=source['section_code'])
            self.assertEqual(1,count)
            self.assertEqual([source['section_code']],[r['table'] for r in result['tables']])


if __name__ == '__main__':
    unittest.main()
