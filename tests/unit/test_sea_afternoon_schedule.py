"""Bestbuy/Lowes KST windows; source dates and D-1 inspection stay separate."""
import unittest
from contextlib import contextmanager
from datetime import date, datetime, timezone
from unittest.mock import Mock, patch

from apps.common.sea_collection import KST, afternoon_collection_phase
from apps.common.source_dates import source_date_sql, source_date_value
from apps.dx.dx_layer1.dashboard import collection_services as dday, collection_repositories as repo
from apps.dx.dx_layer1.retail import retail_services as retail, bestbuy_dryer, lowes_dryer
from apps.dx.dx_layer1.column_statistics.comparison import collection_complete

DAY = date(2026, 10, 26)
PAIRS = {('Bestbuy', p) for p in ('TV', 'REF', 'LDY', 'LDY_DRYER')} | {
    ('Lowes', p) for p in ('REF', 'LDY', 'LDY_DRYER')}


@contextmanager
def connection():
    yield None, Mock()


class SeaAfternoonScheduleTests(unittest.TestCase):
    def test_kst_boundaries_and_no_dst_shift(self):
        for day in (DAY, date(2026, 11, 2)):
            for hour, minute, phase in ((12, 59, 'pending'), (13, 0, 'collecting'),
                                        (17, 59, 'collecting'), (18, 0, 'complete')):
                now = datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=minute, tzinfo=KST)
                for retailer, product in PAIRS:
                    with self.subTest(day=day, retailer=retailer, product=product, phase=phase):
                        self.assertEqual(phase, afternoon_collection_phase(day, retailer, now))
                        self.assertEqual(phase == 'complete', collection_complete('SEA', product, retailer, day, now))
                        self.assertEqual(phase, afternoon_collection_phase(day, retailer, now.astimezone(timezone.utc)))
        self.assertIsNone(afternoon_collection_phase(date(2026, 10, 25), 'Bestbuy'))
        self.assertIsNone(afternoon_collection_phase(DAY, 'Amazon'))
        for module in (bestbuy_dryer, lowes_dryer):
            self.assertFalse(module.complete(DAY, datetime(2026, 10, 26, 17, 59, tzinfo=KST)))
            self.assertTrue(module.complete(DAY, datetime(2026, 10, 26, 18, tzinfo=KST)))

    def test_dday_all_seven_scopes_and_collection_states(self):
        for hour, minute, count, status in ((12, 59, 0, 'scheduled'), (13, 0, 0, 'collecting'),
                (17, 59, 50, 'partial'), (18, 0, 0, 'uncollected'), (18, 0, 300, 'received')):
            with patch.object(dday, 'dx_connection', connection), patch.object(dday, 'fetch_collection',
                    return_value=(count, None, 'b1', count, 0)) as fetch:
                data = dday.get_collection_status(DAY, datetime(2026, 10, 26, hour, minute, tzinfo=KST))
            rows = [r for r in data['retailers'] if (r['retailer'], r['product']) in PAIRS]
            self.assertEqual(PAIRS, {(r['retailer'], r['product']) for r in rows})
            for row in rows:
                self.assertEqual(status, row['status'])
                self.assertEqual('2026-10-26T13:00:00+09:00', row['scheduled_at'])
                self.assertEqual('2026-10-26T18:00:00+09:00', row['scheduled_end_at'])
            self.assertTrue(all(c.args[2] == DAY for c in fetch.call_args_list))
        with patch.object(dday, 'dx_connection', connection), patch.object(dday, 'fetch_collection', side_effect=RuntimeError):
            data = dday.get_collection_status(DAY)
        self.assertTrue(all(r['status'] == 'error' and r['count'] is None for r in data['retailers']))

    def test_daily_remains_d_minus_one_and_uses_own_cutoff(self):
        for product in ('tv', 'ref', 'ldy', 'ldy_dryer'):
            for hour, phase in ((17, 'collecting'), (18, 'complete')):
                with patch.object(retail, '_matching_schedule_slots', return_value=[]), \
                        patch.object(retail, '_source_rows', return_value=[]):
                    category, _, _ = retail._build_category(Mock(), retail._get_layer1_source(product),
                        date(2026, 10, 27), datetime(2026, 10, 26, hour, tzinfo=KST))
                self.assertEqual('2026-10-26', category['source_date'])
                rows = [r for r in category['time_slots'][0]['retailers'] if (r['retailer'], product.upper()) in PAIRS]
                for row in rows:
                    self.assertEqual(phase, row['collection_phase'])
                    self.assertEqual('COLLECTING' if phase == 'collecting' else 'CRITICAL', row['status'])
                    self.assertEqual({'start_kst': '13:00', 'end_kst': '18:00'}, row['collection_window'])

    def test_new_dday_queries_keep_original_collection_date(self):
        self.assertEqual('2026-10-26', source_date_value('2026-10-26T23:37:34-04:00'))
        for source in repo.SOURCES:
            if source[:2] not in PAIRS:
                continue
            cursor = Mock()
            cursor.fetchone.return_value = (1, None, 'b1', 1, 0)
            repo.fetch_collection(cursor, source, DAY)
            sql, params = cursor.execute.call_args.args
            for where in sql.split('WHERE ')[1:]:
                condition = where.split('AND LOWER')[0]
                self.assertIn(source_date_sql('source.' + source[3]), condition)
                self.assertNotIn('AT TIME ZONE', condition)
            self.assertEqual(('2026-10-26', source[0]) * 2, params)
            self.assertIn('IS NOT DISTINCT FROM latest.batch_id', sql)

    def test_daily_schedule_metadata_and_previous_day_are_distinct(self):
        with patch.object(retail, '_matching_schedule_slots', return_value=[]), \
                patch.object(retail, '_source_rows', return_value=[]):
            new = retail.get_layer1_stats(Mock(), DAY, datetime(2026, 10, 26, 14))['check']
            old = retail.get_layer1_stats(Mock(), date(2026, 10, 25), datetime(2026, 10, 26, 14))['check']
        self.assertEqual('2026-10-25', new['source_date'])
        self.assertEqual({'start_kst': '13:00', 'end_kst': '18:00'}, new['time_info']['bestbuy_lowes'])
        self.assertEqual((('Amazon', '05:50'),), new['time_info']['am']['retailer_start_times'])
        self.assertIsNone(old['time_info']['bestbuy_lowes'])
        self.assertIn(('Best Buy', '06:55'), old['time_info']['am']['retailer_start_times'])
