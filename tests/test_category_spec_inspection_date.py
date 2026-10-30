"""The category summary, detail and sidebar use the same SEA source day."""
import sys
from datetime import date
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.test_collection_statistics_backend import settings
from apps.dx.dx_layer3.category_spec import services
from apps.dx.dx_layer3.category_spec.dates import rule_date_mapping, rule_source_date
from apps.dx.dx_layer3.dashboard import services as dashboard


class CategoryDateTests(TestCase):
    def test_month_year_and_leap_boundaries_and_other_sources(self):
        for selected, source in [('2026-10-30','2026-10-29'),('2026-11-01','2026-10-31'),
                                 ('2027-01-01','2026-12-31'),('2024-03-01','2024-02-29')]:
            self.assertEqual(source, str(rule_source_date(selected,'tv_retail_com')))
            self.assertEqual(selected, str(rule_source_date(selected,'openai_forecast_results')))
        self.assertEqual(-1,rule_date_mapping(date(2026,10,30),'tv_retail_com')['offset_days'])

    def test_summary_detail_dashboard_query_identical_source_day(self):
        rule=dict(rule_id=9,section_code='tv_retail',section_name='TV',detail_code='price',
                  table_name='tv_retail_com',date_column='crawl_datetime::timestamp',
                  field1='final_sku_price',product_line='tv',query='SELECT id FROM {table} WHERE DATE({date_col}) = %s')
        day=date(2026,10,30)
        for caller in ('summary','detail','dashboard'):
            cursor=Mock();cursor.fetchone.return_value=(952,);cursor.fetchall.return_value=[];cursor.description=[('id',)]
            if caller=='summary':
                services.get_rules_summary(cursor,day,'tv_retail',[rule])
            elif caller=='detail':
                services.get_rule_detail(cursor,day,9,'tv',[rule])
            else:
                conn=Mock();conn.cursor.return_value=cursor
                with patch.object(dashboard,'load_category_rules',return_value=[rule]),patch.object(dashboard,'get_dx_connection',return_value=conn):
                    dashboard.validate_all_category_specs(day)
            self.assertTrue(cursor.execute.called)
            for call in cursor.execute.call_args_list:
                self.assertEqual((date(2026,10,29),),call.args[1])
                self.assertNotIn('EXTRACT(HOUR',call.args[0])


if __name__=='__main__':
    main()
