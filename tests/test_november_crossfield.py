"""November cross-field rules, retailer isolation and original-day histories."""
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests import test_seuk_crossfield  # isolated Django settings
from tests.unit.support import ScriptedCursor
from apps.dx.dx_layer3.cross_field import seuk_services as uk, seib_services as ib
from apps.dx.dx_layer3.cross_field import seg_services as seg, sem_services as sem
from apps.dx.dx_layer3.data_edit import services as edits
from apps.common.source_dates import source_date_sql

DAY = date(2026, 10, 30)


def row(retailer='AO', **changes):
    values = dict(id=2, account_name=retailer, item='shared-item', sku='SKU',
                  retailer_sku_name='Product', batch_id='new', country='SEUK',
                  crawl_datetime='2026-10-30T23:59:59-04:00',
                  count_of_reviews='10',count_of_star_ratings='10',star_rating='4.5',
                  final_sku_price='£80',original_sku_price='£100',savings='£20')
    values.update(changes)
    return values


class RetailerCursor:
    def __init__(self, module, key, records):
        self.module, self.key, self.records = module, key, records
        self.calls = []

    def execute(self, query, params=None):
        self.query, self.params = query, params
        self.calls.append((query, params))

    def fetchall(self):
        if 'monitoring_validation_rules' in self.query:
            source = getattr(self.module, 'SEUK_SOURCE_CONFIG', getattr(self.module, 'SEIB_SOURCE_CONFIG', {}))[self.key]
            result = []
            for number, retailer in enumerate(source['retailers'], 1):
                prefix = self.key + ('_' if retailer == self.module.RETAILER else '_' + retailer.lower() + '_')
                result.extend((number * 100 + i, prefix + key, key, retailer)
                              for i, key in enumerate(self.module.rule_definitions(retailer), 1))
            return result
        if 'SELECT source.*' in self.query:
            return [dict(r) for r in self.records if r['account_name'].lower() == self.params[-1]]
        return []


class NovemberCrossfieldTests(unittest.TestCase):
    def test_otto_dryer_registration_preserves_existing_rule_ids_and_approvals(self):
        cursor = Mock()
        cursor.fetchall.return_value = [
            {'rule_id': 900, 'validation_type': 'review_count_match',
             'retailer': 'OTTO', 'sort_order': 10},
            {'rule_id': 100, 'validation_type': 'review_count_match',
             'retailer': 'ALL', 'sort_order': 100},
        ]
        rules = seg.load_active_seg_rules(cursor, 'seg_ldy_dryer')
        by_id = {rule['rule_id']: rule for rule in rules}
        self.assertEqual({100, 900}, set(by_id))
        self.assertEqual([100], by_id[100]['_source_rule_ids'])
        self.assertTrue(seg._rule_applies_to_retailer(by_id[100], 'Mediamarkt'))
        self.assertFalse(seg._rule_applies_to_retailer(by_id[100], 'OTTO'))
        self.assertTrue(seg._rule_applies_to_retailer(by_id[900], 'OTTO'))
        self.assertFalse(seg._rule_applies_to_retailer(by_id[900], 'Mediamarkt'))

    def test_otto_reuses_six_existing_rules_without_rate_match(self):
        base = row('OTTO', country='SEG', final_sku_price='80,00 €', original_sku_price='100,00 €', savings='20%')
        self.assertEqual(set(), seg.evaluate_seg_row(base, 'seg_ldy_dryer'))
        cases = {
            'review_count_match': {'count_of_reviews':'11'},
            'rating_count_presence': {'star_rating':'0'},
            'final_original_price': {'final_sku_price':'100,00 €'},
            'savings_missing': {'savings':None},
            'original_missing': {'original_sku_price':None},
            'final_missing': {'final_sku_price':None},
        }
        for expected, changes in cases.items():
            self.assertEqual({expected}, seg.evaluate_seg_row({**base, **changes}, 'seg_ldy_dryer'))
        self.assertEqual(set(), seg.evaluate_seg_row({**base, 'savings':'99%'}, 'seg_ldy_dryer'))
        self.assertIn('OTTO',seg.get_seg_source('seg_ldy_dryer')['retailers'])

    def test_liverpool_reuses_four_existing_rules_and_ignores_savings(self):
        base = row('Liverpool', country='SEM', final_sku_price='$80.00', original_sku_price='$100.00', savings=None)
        cases = {'review_rating_count': {'count_of_reviews':'11'},
                 'rating_count_consistency': {'star_rating':'0'},
                 'final_original_price': {'final_sku_price':'$100.00'},
                 'original_price_zero': {'original_sku_price':'$0.00'}}
        self.assertEqual([],sem._failed_rules(base,'Liverpool','sem_ldy_dryer'))
        for expected, changes in cases.items():
            self.assertEqual([expected],sem._failed_rules({**base,**changes},'Liverpool','sem_ldy_dryer'))
        self.assertIn('Liverpool',sem.active_sem_retailers('sem_ldy_dryer',DAY))
        self.assertNotIn('Liverpool',sem.active_sem_retailers('sem_ldy_dryer',date(2026,10,29)))

    def test_eci_has_four_rules_and_savings_cannot_affect_any_result(self):
        self.assertEqual({'review_count_match','rating_count_presence','final_original_price','final_missing'},set(ib.rule_definitions('ECI')))
        base = row('ECI', country='SEIB', final_sku_price='80,00 €', original_sku_price='100,00 €')
        for savings in (None,'20%','90%','invalid'):
            self.assertEqual(set(),ib.evaluate_eci_row({**base,'savings':savings}))
            self.assertEqual(set(),ib.evaluate_eci_row({**base,'original_sku_price':None,'savings':savings}))
            self.assertEqual(set(),ib.evaluate_eci_row({**base,'original_sku_price':None,'final_sku_price':None,'savings':savings}))
            self.assertEqual({'final_missing'},ib.evaluate_eci_row({**base,'final_sku_price':None,'savings':savings}))
        for definition in ib.rule_definitions('ECI').values():
            self.assertNotIn('savings',' '.join(str(v) for v in definition))
        self.assertNotIn('savings',ib.editable_columns('ECI'))
        self.assertIn('savings',ib.editable_columns('MediaMarkt'))
        # Existing MediaMarkt discount checking remains enabled.
        self.assertIn('savings_missing',ib.evaluate_seib_row({**base,'savings':None}))

    def test_ao_seven_rules_and_exact_currency_values(self):
        self.assertEqual(7,len(uk.rule_definitions('AO')))
        for product in ('ref','ldy','ldy_dryer'):
            self.assertEqual(set(),uk.evaluate_seuk_row(row()))
            self.assertEqual({'savings_amount_match'},uk.evaluate_seuk_row(row(savings='£19.99')))
            query=uk.display_query(uk.get_seuk_source('seuk_'+product),DAY,3,retailer='AO')
            self.assertIn("= 'ao'",query)
            self.assertNotIn("'currys'",query)
            self.assertIn("'2026-10-30'",query)
            self.assertNotIn('AT TIME ZONE',query)

    def test_summary_and_history_never_mix_retailers_with_the_same_item(self):
        for module,key,old,new in ((uk,'seuk_ref','Currys','AO'),(ib,'seib_ldy_dryer','MediaMarkt','ECI')):
            records=[row(old,id=1),row(new,id=2,star_rating='0'),
                     row(old,id=3,crawl_datetime='2026-10-29T23:59:59-04:00'),
                     row(new,id=4,crawl_datetime='2026-10-29T23:59:59-04:00')]
            if module is ib:
                for record in records:
                    record.update(final_sku_price='80,00 €',original_sku_price='100,00 €',savings='20%')
            summary_fn = getattr(module,'get_'+key[:4]+'_cross_field_summary')
            detail_fn = getattr(module,'get_'+key[:4]+'_cross_field_rule_detail')
            with patch.object(module,'exclude_page_absent_records',side_effect=lambda c,d,r,**kw:(r,[])):
                summary=summary_fn(RetailerCursor(module,key,records),DAY,key)
                detail=detail_fn(RetailerCursor(module,key,records),DAY,key,202,3)
            self.assertEqual(2,summary['total_checked'])
            self.assertEqual(1,summary['failed_records'])
            self.assertEqual({old,new},{r['retailer'] for r in summary['retailers']})
            self.assertTrue(all(r['account_name']==new for r in detail['anomalies']))
            self.assertEqual({new},set(detail['queries']))
            self.assertEqual(1,detail['total_anomalies'])
            if new=='ECI':
                self.assertNotIn('savings',detail['select_fields'])
                self.assertNotIn('savings',detail['retailer_columns']['ECI'])

    def test_retailer_rules_are_allowlisted_and_review_cannot_cross_accounts(self):
        source=uk.get_seuk_source('seuk_ref')
        cursor=Mock()
        cursor.fetchall.return_value=[(1,'seuk_ref_ao_savings_amount_match','savings_amount_match','AO'),
                                     (2,'seuk_ref_ao_savings_amount_match','savings_amount_match','Currys'),
                                     (3,'seuk_ref_other_savings_amount_match','savings_amount_match','other')]
        self.assertEqual([1],[r['rule_id'] for r in uk.load_active_rules(cursor,source)])
        cursor=ScriptedCursor([{'fetchone':('£20','AO','shared-item')}])
        with patch.object(uk,'load_active_rules',return_value=[{'rule_id':7,'retailers':['Currys']}]):
            result=edits.save_review(cursor,Mock(),source['table_name'],2,'savings','normal','','checked',str(DAY),'cross_field','tester',7)
        self.assertEqual(400,result['status'])
        self.assertTrue(all('INSERT' not in sql for sql,_ in cursor.calls))
        self.assertIn('latest.retailer_key',cursor.calls[0][0])
        self.assertIn(source_date_sql('source.crawl_datetime'),cursor.calls[0][0])

    def test_new_null_scope_does_not_enable_format_checks(self):
        from apps.dx.dx_layer2 import seuk_format_validation, seib_format_validation
        self.assertEqual([],seuk_format_validation.get_format_rule_details('seuk_ref','AO'))
        self.assertEqual([],seib_format_validation.get_format_rule_details('seib_ldy_dryer','ECI'))


if __name__=='__main__':
    unittest.main()
