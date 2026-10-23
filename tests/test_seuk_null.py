"""SEUK NULL integration with mocked source cursors; never contacts a DB."""
import sys
import unittest
from contextlib import ExitStack
from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests import test_collection_statistics_backend  # isolated Django settings
from tests.unit.support import ScriptedCursor
from apps.common import seuk_retail as policy, null_review_evidence as evidence
from apps.common.source_dates import source_date_sql
from apps.dx.dx_layer2 import seuk_null_validation as seuk
from apps.dx.dx_layer2.common import context
from apps.dx.dx_layer2.null_validation import services as nulls, review_history
from apps.dx.dx_layer2.data_edit import services as edits
from apps.dx.dx_layer2.dashboard.services import supports_null_auto_detail


DAY = policy.FIRST_SOURCE_DATE
SOURCE = policy.SEUK_SOURCE_CONFIG['seuk_tv']


def record(**changes):
    row = dict.fromkeys(SOURCE['columns'], 'value')
    row.update(id=42, account_name='Currys', country='SEUK', item='001',
               retailer_sku_name='Product A', batch_id='current',
               crawl_datetime=f'{DAY}T23:59:59-04:00', screen_size=None,
               count_of_reviews='0', count_of_star_ratings='0', star_rating='0')
    row.update(changes)
    return row


class SeukNullTests(unittest.TestCase):
    def test_required_fields_match_seib_and_zero_is_not_null(self):
        for key in policy.SEUK_SOURCE_CONFIG:
            fields = policy.get_seuk_null_columns(key, ' currys ')
            self.assertEqual(11, len(fields))
            self.assertNotIn('loading_type', fields)
            self.assertNotIn('ref_refrigerator_type', fields)
            self.assertFalse(set(fields) & {'original_sku_price','savings','main_rank','bsr_rank'})
        for value in (0,'0','0.0','NULL',False): self.assertFalse(seuk.missing(value))
        for value in (None,'',' ','\t\n'): self.assertTrue(seuk.missing(value))
        with self.assertRaises(ValueError): policy.get_seuk_null_columns('seuk_tv','other')

    def test_latest_batch_and_original_day_scope_are_used_for_read_and_write(self):
        cursor = Mock()
        cursor.description = [(column,) for column in SOURCE['columns']]
        cursor.fetchall.return_value = [record()]
        rows, mapping = seuk.latest_rows(cursor, DAY, SOURCE, 'Currys')
        self.assertEqual([42], [r['id'] for r in rows])
        self.assertEqual(str(DAY), mapping['source_date'])
        sql, params = cursor.execute.call_args.args
        self.assertIn(source_date_sql('anchor.crawl_datetime'),sql)
        self.assertIn('anchor.id DESC',sql)
        self.assertIn('source.batch_id IS NOT DISTINCT FROM latest.batch_id',sql)
        self.assertNotIn('AT TIME ZONE',sql)
        self.assertEqual([str(DAY),str(DAY),'currys','currys'],params)
        cursor.fetchone.return_value = (None,'Currys','001','current')
        self.assertEqual((None,'Currys','001'),seuk.select_record(cursor,DAY,'seuk_tv',42,'screen_size'))
        self.assertIn('FOR UPDATE OF source',cursor.execute.call_args.args[0])
        for field in ('loading_type','screen_size;DELETE','main_rank'):
            with self.assertRaises(ValueError): seuk.select_record(cursor,DAY,'seuk_tv',42,field)

    def test_counts_distinguish_raw_pending_and_reviewed_cells(self):
        mapping = seuk._mapping(DAY,SOURCE)
        rows = [record(sku=' ',original_sku_price=None,savings=None)]
        with patch.object(seuk,'latest_rows',return_value=(rows,mapping)), \
             patch.object(seuk,'_load_normal_reviews',return_value={'42_screen_size':{'memo':'checked'}}), \
             patch.object(evidence,'load_evidence',return_value=[]):
            result={'tables':[]}
            self.assertEqual(1,seuk.append_null_stats(Mock(),DAY,result,category='seuk_tv_retail'))
        table=result['tables'][0]
        self.assertEqual(2,table['raw_null_count'])
        self.assertEqual(1,table['manual_reviewed_count'])
        fields=table['retailers'][0]['fields_detail']
        self.assertEqual(1,fields['sku'])
        self.assertEqual(0,fields['screen_size'])
        self.assertEqual(0,fields['star_rating'])

    def test_detail_history_preserves_null_items_and_has_start_date(self):
        target=[record(),record(id=43,item=None)]
        history=[record(id=1,screen_size='55',crawl_datetime=str(DAY)+'T00:01:00+09:00'),target[0]]
        with patch.object(seuk,'latest_rows',return_value=(target,seuk._mapping(DAY,SOURCE))), \
             patch.object(seuk,'_load_normal_reviews',return_value={}), \
             patch.object(evidence,'load_evidence',return_value=[]), \
             patch.object(seuk,'_history_rows',return_value=history):
            result=seuk.null_detail(Mock(),DAY,'seuk_tv_retail','Currys','screen_size',days=3)
        self.assertEqual([1,42,43],[r['id'] for r in result['results']])
        self.assertNotIn('screen_size',result['results'][0]['null_fields'])
        self.assertIn('screen_size',result['results'][1]['null_fields'])
        self.assertEqual(str(DAY),result['active_from'])
        cursor=Mock()
        cursor.description=[]
        cursor.fetchall.return_value=[]
        seuk._history_rows(cursor,SOURCE,'Currys',date(2026,10,1),DAY,['001'])
        self.assertEqual(str(DAY),cursor.execute.call_args.args[1][0])

    def test_edit_uses_current_batch_and_records_audit(self):
        for field in ('screen_size','final_sku_price','original_sku_price','savings'):
            cursor=ScriptedCursor([{'fetchone':(None,'Currys','001','current')},{'rowcount':1},{'rowcount':1}])
            result=edits.update_cell_value(cursor,Mock(),SOURCE['table_name'],42,field,'55',str(DAY),'null','tester','')
            self.assertTrue(result['success'],result)
            self.assertIn('FOR UPDATE OF source',cursor.calls[0][0])
            self.assertEqual(str(DAY),cursor.calls[0][1][0])
            self.assertIn('monitoring_corrections',cursor.calls[-1][0])
        cursor=ScriptedCursor([{'fetchone':None}])
        self.assertEqual(404,edits.update_cell_value(cursor,Mock(),SOURCE['table_name'],42,'sku','X',str(DAY),'null','tester','')['status'])
        cursor=ScriptedCursor([{'fetchone':('001','Currys','001','current')},{'fetchone':(99,)}])
        result=edits.update_cell_value(cursor,Mock(),SOURCE['table_name'],42,'item','duplicate',str(DAY),'null','tester','')
        self.assertEqual(409,result['status'])
        self.assertFalse(any(sql.lstrip().startswith('UPDATE ') for sql,_ in cursor.calls))

    def test_other_validations_and_unrequired_columns_stay_disabled(self):
        for kind,field in (('format','sku'),('duplicate','sku'),('cross_field','sku'),('other','sku'),('null','loading_type')):
            cursor=ScriptedCursor([])
            result=edits.update_cell_value(cursor,Mock(),SOURCE['table_name'],42,field,'X',str(DAY),kind,'tester','')
            self.assertEqual(403,result['status'])
            result=nulls.save_null_review(cursor,Mock(),SOURCE['table_name'],42,field,'normal','','reason',str(DAY),kind,'tester')
            self.assertEqual(400,result['status_code'])
            self.assertEqual([],cursor.calls)

    def test_normal_review_captures_country_product_and_raw_date(self):
        source=policy.SEUK_SOURCE_CONFIG['seuk_ldy_dryer']
        cursor=ScriptedCursor([
            {'fetchone':(None,'Currys','001')},
            {'fetchone':(42,'001','Product A',None,'Currys')},
            {'fetchone':None},{'fetchone':(51,)},{'fetchone':(101,)},
        ])
        conn=Mock()
        with patch.object(evidence,'_korean_time',return_value=datetime(2026,10,23,16,tzinfo=evidence.KOREA)):
            result=nulls.save_null_review(cursor,conn,source['table_name'],42,'capacity','normal','',
                '해당값 정상 확인',str(DAY),'null','tester')
        self.assertTrue(result['success'],result)
        self.assertIn(source_date_sql('crawl_datetime'),cursor.calls[1][0])
        saved=dict(zip(evidence._EVIDENCE_COLUMNS[1:],cursor.calls[4][1]))
        self.assertEqual(('SEUK','LDY_DRYER','Currys'),(saved['country'],saved['product_line'],saved['retailer']))
        conn.commit.assert_called_once()
        cursor=ScriptedCursor([{'fetchone':('value','Currys','001')}])
        result=nulls.save_null_review(cursor,Mock(),SOURCE['table_name'],42,'sku','normal','','reason',str(DAY),'null','tester')
        self.assertEqual(409,result['status_code'])

    def test_dryer_auto_review_context_and_history_registration(self):
        with patch.object(evidence,'load_evidence',return_value=[]) as load:
            seuk.review_state(Mock(),DAY,[record(capacity=None)],['capacity'],{},
                table_name='dx_seuk.dx_seuk_ldy_dryer_retail_com',country='SEUK',
                product_line='seuk_ldy_dryer',retailer='Currys',is_null=lambda value,field:seuk.missing(value))
        self.assertEqual('LDY_DRYER',load.call_args.kwargs['product_line'])
        source=review_history._sources()['dx_seuk.dx_seuk_ldy_dryer_retail_com']
        self.assertEqual('LDY_DRYER',source['product_line'])
        self.assertEqual('seuk_ldy_dryer_retail',source['history_category'])
        self.assertTrue(supports_null_auto_detail('null','seuk_ldy_dryer_retail',DAY))
        self.assertFalse(supports_null_auto_detail('format','seuk_ldy_dryer_retail',DAY))

    def test_dashboard_routes_to_seuk_once_and_sidebar_only_enables_null(self):
        config={s['section_code']:{'display_name':s['display_name'],'checks':{}} for s in policy.SEUK_SOURCE_CONFIG.values()}
        with ExitStack() as stack:
            stack.enter_context(patch.object(nulls,'load_null_check_config',return_value=config))
            stack.enter_context(patch.object(nulls,'get_all_categories',return_value=list(config)))
            groups=context.build_sidebar_groups('null_validation','SEUK REF')
            self.assertTrue(any(i['name']=='SEUK Retail' and i['active'] for i in groups[0]['items']))
            self.assertFalse(any(i['name']=='SEUK Retail' for g in groups[1:] for i in g.get('items',[])))
            menus=context.get_sidebar_items()
            self.assertEqual(4,len(menus['null']))
            self.assertEqual([],menus['format'])
            self.assertEqual([],menus['anomaly'])
            stack.enter_context(patch.object(seuk,'latest_rows',return_value=([record()],seuk._mapping(DAY,SOURCE))))
            stack.enter_context(patch.object(seuk,'_load_normal_reviews',return_value={}))
            stack.enter_context(patch.object(evidence,'load_evidence',return_value=[]))
            result,count=nulls.get_null_stats(Mock(),DAY,category='seuk_tv_retail',include_youtube=False)
            self.assertEqual(1,count)
            self.assertEqual(['seuk_tv_retail'],[t['table'] for t in result['tables']])

    def test_null_registration_sql_parses(self):
        from pglast import parse_sql,parse_plpgsql
        sql=(Path(__file__).resolve().parents[1]/'sql/setup_seuk_null.sql').read_text(encoding='utf-8')
        self.assertTrue(parse_sql(sql))
        self.assertTrue(parse_plpgsql(sql))
        self.assertNotIn('UPDATE dx_seuk.',sql)
        self.assertNotIn('DELETE FROM',sql)


if __name__=='__main__': unittest.main()
