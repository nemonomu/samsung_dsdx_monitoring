"""History date semantics, whole-result searching and read-only source lookup."""
import unittest
from datetime import date, datetime, timezone
from unittest.mock import Mock

from apps.dx.dx_layer2.null_validation import review_history as history


TODAY = date(2026, 9, 23)


def filters(**values):
    return history.parse_filters(values, today=TODAY)


def entry(number, **values):
    return dict(id=f'manual:{number}', record_id=number,
                country='SEG', product_line='REF', retailer='OTTO',
                applied_date='2026-09-23', original_created_at='2026-09-23T09:00:00+09:00',
                item=f'item-{number}', sku=f'sku-{number}', memo='',
                **values)


class HistoryTests(unittest.TestCase):
    def setUp(self):
        history._HISTORY_CACHE.clear()

    def test_default_today_and_all_and_inclusive_calendar(self):
        self.assertEqual((TODAY, TODAY), (filters()['start'], filters()['end']))
        self.assertIsNone(filters(period='all')['start'])
        self.assertIsNone(filters(period='all')['end'])
        value = filters(period='calendar', start_date='2026-09-01', end_date='2026-09-23')
        self.assertEqual(date(2026, 9, 1), value['start'])
        self.assertEqual(TODAY, value['end'])
        self.assertEqual(TODAY, filters(date='2026-09-23')['start'])

    def test_invalid_dates_page_and_filter_fail(self):
        for args in ({'period': 'bad'}, {'period': 'calendar'},
                     {'period': 'calendar', 'start_date': '2026-09-24', 'end_date': '2026-09-23'},
                     {'date': '2026-02-30'}, {'page': 'bad'}, {'page': '-1'},
                     {'country': 'no'}, {'product_line': 'no'}, {'kind': 'no'}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                filters(**args)

    def test_search_is_before_pagination_and_searches_every_displayed_field(self):
        rows = [entry(n) for n in range(121)]
        first = history.paginate(rows, filters())
        second = history.paginate(rows, filters(page='2'))
        last = history.paginate(rows, filters(page='999'))
        self.assertEqual((121, 3, 50), (first['total'], first['pages'], len(first['logs'])))
        self.assertTrue({r['id'] for r in first['logs']}.isdisjoint(r['id'] for r in second['logs']))
        self.assertEqual((3, 21), (last['page'], len(last['logs'])))
        for field in history.SEARCH_FIELDS:
            fixture = entry(999)
            fixture[field] = 'unique-needle'
            result = history.paginate(rows + [fixture], filters(q='UNIQUE-needle', page='20'))
            self.assertEqual(1, result['total'], field)
            self.assertEqual(1, result['page'])

    def test_memo_filter_excludes_blank_and_combines_country_product_kind(self):
        rows = [entry(1), entry(2), entry(3), entry(4), entry(5)]
        rows[0]['memo'] = '   \n'
        rows[1]['memo'] = '품절 확인'
        rows[2].update(memo='품절 확인', country='SEA')
        rows[3].update(memo='품절 확인', auto_applied=True)
        rows[4].update(memo='품절 확인', product_line='TV')
        result = history.paginate(rows, filters(memo_only='1', country='SEG',
                                               product_line='REF', kind='manual', q='품절'))
        self.assertEqual(1, result['total'])
        self.assertEqual(2, result['logs'][0]['record_id'])
        self.assertEqual(4, history.paginate(rows, filters(memo_only='1'))['total'])

    def test_manual_uses_actual_review_time_in_korea_not_collection_day(self):
        cursor = Mock()
        cursor.fetchall.return_value = [(1, 'tv_retail_com', 23, 'Amazon', 'item',
            'sku', '해당값 정상 확인', 'fallback', date(2026, 9, 10), 'fallback',
            datetime(2026, 9, 22, 15, 30, tzinfo=timezone.utc),
            11, 'SEA', 'TV', 'Product', datetime(2026, 9, 22, 16, tzinfo=timezone.utc),
            'original-reviewer', 'original-memo', None)]
        logs = history._manual_rows(cursor, history._sources())
        self.assertEqual('2026-09-23', logs[0]['applied_date'])
        self.assertEqual('2026-09-10', logs[0]['crawl_date'])
        self.assertEqual('original-memo', logs[0]['memo'])
        self.assertEqual('original-reviewer', logs[0]['created_id'])
        self.assertTrue(cursor.execute.call_args.args[0].lstrip().startswith('SELECT'))

    def test_today_keeps_old_row_reviewed_today_and_automatic_application_today(self):
        manual = entry(1, crawl_date='2026-09-10')
        auto = entry(2, auto_applied=True, table_name='dx_seg.dx_seg_ref_retail_com')
        auto['original_created_at'] = '2026-09-12T09:00:00+09:00'
        old = entry(3)
        old['applied_date'] = '2026-09-22'
        from unittest.mock import patch
        with patch.object(history, '_manual_rows', return_value=[manual, old]), \
                patch.object(history, '_auto_days', return_value=[(TODAY, 'seg_ref_retail')]), \
                patch.object(history, '_enrich_rows'):
            loader = Mock(return_value=[auto])
            result = history.get_review_history(Mock(), filters(), loader)
        self.assertEqual({1, 2}, {r['record_id'] for r in result['logs']})
        self.assertEqual('2026-09-12T09:00:00+09:00', result['logs'][1]['original_created_at'])
        self.assertEqual('seg_ref_retail', loader.call_args.kwargs['category'])

    def test_auto_dates_use_only_sources_with_evidence_and_selected_bounds(self):
        cursor = Mock()
        cursor.fetchall.return_value = [('tv_retail_com', date(2026, 9, 12)),
                                       ('dx_seg.dx_seg_ref_retail_com', date(2026, 9, 20))]
        scopes = history._auto_days(cursor, filters(period='calendar', start_date='2026-09-22',
            end_date='2026-09-23', country='SEG'), [], history._sources())
        self.assertEqual([(TODAY, 'seg_ref_retail'), (date(2026, 9, 22), 'seg_ref_retail')], scopes)

    def test_enrichment_only_uses_registry_tables_and_keeps_deleted_source_evidence(self):
        cursor = Mock()
        cursor.fetchall.return_value = [(1, 'sku-1', 'https://example.com/product',
                                        '2026-09-22 13:00', 'Product', 'item-1')]
        rows = [entry(1, table_name='tv_retail_com'), entry(2, table_name='tv_retail_com'),
                entry(3, table_name='malicious; DROP TABLE review')]
        rows[1]['retailer_sku_name'] = 'original-product'
        history._enrich_rows(cursor, rows, history._sources())
        self.assertEqual(1, cursor.execute.call_count)
        self.assertIn('FROM public.tv_retail_com', cursor.execute.call_args.args[0])
        self.assertEqual('sku-1', rows[0]['sku'])
        self.assertEqual('original-product', rows[1]['retailer_sku_name'])
        self.assertEqual('SEA', rows[0]['country'])

    def test_all_six_countries_three_products_have_allowlisted_sources(self):
        self.assertEqual({(c, p) for c in history.COUNTRIES for p in history.PRODUCTS},
                         {(s['country'], s['product_line']) for s in history._sources().values()})

    def test_pagination_and_search_reuse_snapshot_but_query_refreshes(self):
        from unittest.mock import patch
        with patch.object(history, '_manual_rows', return_value=[entry(n) for n in range(60)]) as manual, \
                patch.object(history, '_enrich_rows'):
            first = history.get_review_history(Mock(), filters(kind='manual'), Mock())
            second = history.get_review_history(Mock(), filters(kind='manual', page='2'), Mock())
            found = history.get_review_history(Mock(), filters(kind='manual', q='sku-59'), Mock())
            self.assertEqual((50, 10, 1), tuple(len(r['logs']) for r in (first, second, found)))
            self.assertEqual(1, manual.call_count)
            history.get_review_history(Mock(), filters(kind='manual', refresh='1'), Mock())
            self.assertEqual(2, manual.call_count)
            with patch.object(history, 'monotonic', return_value=10**12):
                history.get_review_history(Mock(), filters(kind='manual'), Mock())
            self.assertEqual(3, manual.call_count)


if __name__ == '__main__':
    unittest.main()
