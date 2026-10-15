"""Collection dates must survive display conversion and calendar boundaries."""
import unittest
from datetime import date, datetime
from unittest.mock import Mock

from apps.common import costco_layer2, sea_layer2
from apps.common.sea_dates import appliance_source_date_sql, appliance_source_date_value
from apps.common.source_dates import source_date_sql, source_date_value
from apps.dx.dx_layer1.retail import costco


class SourceDateTests(unittest.TestCase):
    def test_original_day_across_offsets_and_year_boundary(self):
        cases = (
            ('2026-10-14T21:37:34-04:00', '2026-10-14'),
            ('2026-09-18T01:59:39+00:00', '2026-09-18'),
            ('2026-01-01T00:01:00+14:00', '2026-01-01'),
            ('2026-12-31T23:59:59-12:00', '2026-12-31'),
            (' 2026-10-14 21:37:34 ', '2026-10-14'),
            (datetime.fromisoformat('2026-10-14T21:37:34-04:00'), '2026-10-14'),
            (None, ''), ('', ''),
        )
        for stamp, expected in cases:
            with self.subTest(stamp=stamp):
                self.assertEqual(expected, source_date_value(stamp))
                self.assertEqual(expected, appliance_source_date_value(
                    {'account_name': 'HomeDepot', 'crawl_strdatetime': stamp}))
                for retailer in ('Costco', 'HomeDepot'):
                    row = {'account_name': retailer, 'crawl_strdatetime': stamp}
                    costco_layer2.annotate_source_date(row)
                    self.assertEqual(stamp, row['crawl_strdatetime'])
                    if stamp:
                        self.assertEqual(expected, row['_source_date'])

    def test_reported_costco_batch_keeps_october_14_when_displayed_in_kst(self):
        for column in ('crawl_datetime', 'crawl_strdatetime'):
            row = {'account_name': 'Costco', 'batch_id': 'c20261014_213734',
                   column: '2026-10-14T21:37:34-04:00'}
            costco_layer2.annotate_source_date(row, display_kst=True)
            self.assertEqual('2026-10-14', row['_source_date'])
            self.assertEqual('2026-10-15 10:37:34', row[column])
            self.assertEqual('c20261014_213734', row['batch_id'])

    def test_monitoring_sql_preserves_original_date_and_lookup_exceptions(self):
        for column in ('source.crawl_datetime', 'source.crawl_strdatetime'):
            raw = source_date_sql(column)
            self.assertIn(column, raw)
            self.assertNotIn('AT TIME ZONE', raw)
            self.assertNotIn('timestamptz', raw)
            self.assertEqual(raw, costco.source_date_sql(column))
            self.assertEqual(raw, appliance_source_date_sql(column))
            self.assertIn(raw, costco_layer2.source_date_sql(column, retailer='Costco'))
            self.assertIn(raw, sea_layer2.source_date_sql(column, retailer='HomeDepot'))
            self.assertIn('Asia/Seoul', costco.query_date_sql(column))
            self.assertIn('Asia/Seoul', costco_layer2.source_date_sql(
                column, retailer='Costco', query_scope=True))

    def test_dday_filters_original_date_but_formats_last_collection_in_kst(self):
        from tests.unit.support import load_module, module_stub
        repository = load_module(
            'apps/dx/dx_layer1/dashboard/collection_repositories.py',
            'source_date_repository_under_test',
            {'apps.common.db': module_stub('apps.common.db', dx_table=lambda name: name)},
        )
        for source in repository.SOURCES:
            if source[0] not in ('Costco', 'HomeDepot'):
                continue
            cursor = Mock()
            cursor.fetchone.return_value = (78, '2026-10-15 10:37:34', 'c20261014_213734', 78, 53)
            repository.fetch_collection(cursor, source, date(2026, 10, 14))
            sql, params = cursor.execute.call_args.args
            for where in sql.split('WHERE ')[1:]:
                condition = where.split('AND LOWER')[0]
                self.assertIn(source_date_sql('source.' + source[3]), condition)
                self.assertNotIn('AT TIME ZONE', condition)
            self.assertEqual(('2026-10-14', source[0]) * 2, params)
            self.assertIn("AT TIME ZONE 'Asia/Seoul'", sql)


if __name__ == '__main__':
    unittest.main()
