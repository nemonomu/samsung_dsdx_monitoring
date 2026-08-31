import unittest
from contextlib import contextmanager
from datetime import date, datetime

from apps.common import inspection_dates, sea_retail
from tests.unit.support import load_module, module_stub, package_stub


class RepoStub:
    def __init__(self):
        self.calls = []
        self.tv_rows = []
        self.appliance_rows = {}
        self.summary_counts = {}
        self.detail_rows = []
        self.raw_rows = []
        self.raw_batch = None

    def query_retail_counts(self, cursor, table, date_field, extra_field,
                            start, end, daily_retailers):
        self.calls.append(('tv_counts', table, start, end))
        return list(self.tv_rows)

    def query_appliance_counts(self, cursor, table, date_column, target_date,
                               retailers):
        self.calls.append((
            'appliance_counts', table, target_date, tuple(retailers),
        ))
        return list(self.appliance_rows.get(table, []))

    def query_retail_counts_by_retailer(self, *args):
        retailer = args[-1]
        return self.summary_counts.get(retailer, (0, 0, 0, 0))

    def query_appliance_counts_by_retailer(self, cursor, table, date_column,
                                           target_date, retailer):
        self.calls.append((
            'appliance_summary', table, target_date, retailer,
        ))
        return self.summary_counts.get(
            (table, retailer), (0, 0, 0, 0, None)
        )

    def get_retail_summary_null_counts(self, *args):
        return ()

    def get_tv_retail_detail_list(self, cursor, target_date):
        return list(self.detail_rows)

    def get_appliance_retail_detail_list(self, cursor, table, date_column,
                                         target_date, retailers):
        self.calls.append(('appliance_detail', table, target_date))
        return list(self.detail_rows)

    def get_latest_appliance_main_batch(self, cursor, table, date_column,
                                        target_date, retailer):
        self.calls.append(('raw_anchor', table, target_date, retailer))
        return self.raw_batch

    def get_appliance_raw_data_list(self, cursor, table, columns, retailer,
                                    date_column, target_date):
        self.calls.append((
            'appliance_raw', table, tuple(columns), retailer, target_date,
        ))
        return list(self.raw_rows)

    def get_retailer_raw_data_list(self, *args):
        return list(self.raw_rows)


def load_service(repo_stub, schedule_loader=None):
    schedule_loader = schedule_loader or (
        lambda category, target_date, now=None: []
    )
    repo_module = module_stub(
        'apps.dx.dx_layer1.retail.retail_repositories'
    )
    for name in dir(repo_stub):
        if not name.startswith('_'):
            setattr(repo_module, name, getattr(repo_stub, name))

    stubs = {
        'apps': package_stub('apps'),
        'apps.common': package_stub('apps.common'),
        'apps.common.db': module_stub(
            'apps.common.db', dx_connection=lambda: None,
        ),
        'apps.common.dx_schedules': module_stub(
            'apps.common.dx_schedules',
            get_retail_time_slots=schedule_loader,
            get_kst_time_info=lambda hour, target_date: {
                'next_day': False,
                'is_dst': False,
                'hour': hour,
            },
        ),
        'apps.common.inspection_dates': inspection_dates,
        'apps.common.retail_columns': module_stub(
            'apps.common.retail_columns',
            get_retailer_columns=lambda product, retailer: [],
            get_all_retailer_columns=lambda product: {},
        ),
        'apps.common.response': module_stub(
            'apps.common.response', log_error=lambda error: str(error),
        ),
        'apps.common.sea_retail': sea_retail,
        'apps.dx': package_stub('apps.dx'),
        'apps.dx.dx_layer1': package_stub('apps.dx.dx_layer1'),
        'apps.dx.dx_layer1.common': package_stub(
            'apps.dx.dx_layer1.common'
        ),
        'apps.dx.dx_layer1.common.context': module_stub(
            'apps.dx.dx_layer1.common.context',
            SECTION_TITLES={'retail': 'SEA Retail'},
        ),
        'apps.dx.dx_layer1.retail': package_stub(
            'apps.dx.dx_layer1.retail'
        ),
        'apps.dx.dx_layer1.retail.retail_repositories': repo_module,
    }
    return load_module(
        'apps/dx/dx_layer1/retail/retail_services.py',
        'apps.dx.dx_layer1.retail.retail_services',
        stubs,
    )


class SeaLayer1ServiceTests(unittest.TestCase):
    def _all_ok_repo(self):
        repo = RepoStub()
        repo.tv_rows = [
            ('Amazon', 300, 300, 0, 0, 'a_20260819_000001'),
            (
                'Bestbuy', 300, 300, 0, 10,
                'b_20260819_000001, b_20260819_120001',
            ),
            ('Walmart', 300, 300, 0, 0, None),
        ]
        for table in ('public.ref_retail_com', 'public.ldy_retail_com'):
            repo.appliance_rows[table] = [
                ('Bestbuy', 300, 300, 100, 0, f'{table}-bestbuy'),
                ('Lowes', 300, 300, 100, 0, f'{table}-lowes'),
            ]
        return repo

    def test_stats_resolves_each_source_to_d_minus_one_and_returns_contract(self):
        repo = self._all_ok_repo()
        service = load_service(repo)

        result = service.get_layer1_stats(
            object(), date(2026, 8, 20), datetime(2026, 8, 20, 12, 0)
        )

        check = result['check']
        self.assertEqual('2026-08-20', check['inspection_date'])
        self.assertEqual('2026-08-19', check['source_date'])
        self.assertEqual(-1, check['offset_days'])
        self.assertEqual(
            ['sea_tv', 'sea_ref', 'sea_ldy'], check['source_keys']
        )
        self.assertEqual('3/3 카테고리 정상', check['description'])
        self.assertEqual('OK', check['status'])
        self.assertEqual(['TV', 'REF', 'LDY'], [
            category['name'] for category in check['categories']
        ])
        for category in check['categories']:
            self.assertEqual('2026-08-20', category['inspection_date'])
            self.assertEqual('2026-08-19', category['source_date'])
            self.assertEqual(-1, category['offset_days'])

        self.assertEqual(
            ('tv_counts', 'public.tv_retail_com',
             '2026-08-19 00:00:00', '2026-08-20 00:00:00'),
            repo.calls[0],
        )
        appliance_calls = [
            call for call in repo.calls if call[0] == 'appliance_counts'
        ]
        self.assertEqual(2, len(appliance_calls))
        self.assertTrue(all(
            call[2] == date(2026, 8, 19) for call in appliance_calls
        ))

        ref = check['categories'][1]
        self.assertEqual(['Bestbuy', 'Lowes'], [
            retailer['retailer']
            for retailer in ref['time_slots'][0]['retailers']
        ])
        self.assertTrue(all(
            retailer['batch_id']
            for retailer in ref['time_slots'][0]['retailers']
        ))

        tv_retailers = check['categories'][0]['time_slots'][0]['retailers']
        self.assertEqual(
            [
                'a_20260819_000001',
                'b_20260819_000001, b_20260819_120001',
                '',
            ],
            [retailer['batch_id'] for retailer in tv_retailers],
        )

    def test_no_schedule_uses_threshold_and_fixed_retailer_fallback(self):
        repo = RepoStub()
        service = load_service(repo)

        result = service.get_layer1_stats(
            object(), date(2026, 8, 20), datetime(2026, 8, 21, 12, 0)
        )

        check = result['check']
        self.assertEqual('CRITICAL', check['status'])
        self.assertEqual('0/3 카테고리 정상', check['description'])
        self.assertEqual(7, len(result['failed_items']))
        self.assertEqual(
            ['Amazon', 'Bestbuy', 'Walmart'],
            [
                retailer['retailer']
                for retailer in check['categories'][0]['time_slots'][0][
                    'retailers'
                ]
            ],
        )
        self.assertEqual(
            ['Bestbuy', 'Lowes'],
            [
                retailer['retailer']
                for retailer in check['categories'][1]['time_slots'][0][
                    'retailers'
                ]
            ],
        )
        ldy_lowes = check['categories'][2]['time_slots'][0][
            'retailers'
        ][1]
        self.assertEqual('CRITICAL', ldy_lowes['status'])
        self.assertEqual(0, ldy_lowes['count'])
        self.assertEqual(
            {'main_min': 150, 'bsr_min': 90}, ldy_lowes['criteria']
        )

    def test_ldy_lowes_component_threshold_normal(self):
        repo = self._all_ok_repo()
        repo.appliance_rows['public.ldy_retail_com'] = [
            ('Bestbuy', 300, 300, 100, 0, 'ldy-bestbuy'),
            ('Lowes', 197, 194, 100, 0, 'ldy-lowes'),
        ]
        service = load_service(repo)

        result = service.get_layer1_stats(
            object(), date(2026, 8, 20), datetime(2026, 8, 21, 12, 0)
        )
        ldy = result['check']['categories'][2]
        lowes = ldy['time_slots'][0]['retailers'][1]

        self.assertEqual('OK', result['check']['status'])
        self.assertEqual('OK', ldy['status'])
        self.assertEqual('OK', lowes['status'])
        self.assertEqual(
            {'main_min': 150, 'bsr_min': 90}, lowes['criteria']
        )
        self.assertEqual(
            {'main': 194, 'bsr': 100}, lowes['criteria_actual']
        )
        self.assertIsNone(lowes['ok_threshold'])

    def test_ldy_lowes_main_below_minimum_is_critical(self):
        repo = self._all_ok_repo()
        repo.appliance_rows['public.ldy_retail_com'] = [
            ('Bestbuy', 300, 300, 100, 0, 'ldy-bestbuy'),
            ('Lowes', 250, 149, 100, 0, 'ldy-lowes'),
        ]
        service = load_service(repo)

        result = service.get_layer1_stats(
            object(), date(2026, 8, 20), datetime(2026, 8, 21, 12, 0)
        )
        lowes = result['check']['categories'][2]['time_slots'][0][
            'retailers'
        ][1]

        self.assertEqual('CRITICAL', lowes['status'])
        self.assertEqual(250, lowes['count'])
        self.assertEqual(1, len(result['failed_items']))
        self.assertEqual(
            'MAIN >= 150 / BSR >= 90',
            result['failed_items'][0]['expected'],
        )
        self.assertEqual(
            'MAIN 149 / BSR 100',
            result['failed_items'][0]['actual_detail'],
        )

    def test_ldy_lowes_bsr_below_minimum_is_critical(self):
        service = load_service(RepoStub())

        retailers, _total, _status = service.check_retailer_data(
            [('Lowes', 250, 180, 89, 0, 'ldy-lowes')],
            'LDY',
        )
        lowes = next(
            row for row in retailers if row['retailer'] == 'Lowes'
        )

        self.assertEqual('CRITICAL', lowes['status'])

    def test_ldy_lowes_component_threshold_boundary_is_ok(self):
        service = load_service(RepoStub())

        retailers, _total, _status = service.check_retailer_data(
            [('Lowes', 150, 150, 90, 0, 'ldy-lowes')],
            'LDY',
        )
        lowes = next(
            row for row in retailers if row['retailer'] == 'Lowes'
        )

        self.assertEqual('OK', lowes['status'])

    def test_other_sea_retailers_keep_total_200_threshold(self):
        service = load_service(RepoStub())

        below_rows, _total, _status = service.check_retailer_data(
            [('Bestbuy', 199, 199, 100, 0, 'ldy-bestbuy')],
            'LDY',
        )
        boundary_rows, _total, _status = service.check_retailer_data(
            [('Bestbuy', 200, 150, 90, 0, 'ldy-bestbuy')],
            'LDY',
        )
        below = next(
            row for row in below_rows if row['retailer'] == 'Bestbuy'
        )
        boundary = next(
            row for row in boundary_rows if row['retailer'] == 'Bestbuy'
        )

        self.assertEqual('CRITICAL', below['status'])
        self.assertEqual('OK', boundary['status'])
        self.assertEqual({'total_min': 200}, boundary['criteria'])
        self.assertEqual(200, boundary['ok_threshold'])

    def test_schedule_collecting_overrides_zero_count_and_suppresses_failures(self):
        repo = RepoStub()

        def schedules(category, target_date, now=None):
            retailers = (
                ('Amazon', 'Bestbuy', 'Walmart')
                if category == 'TV' else ('Bestbuy', 'Lowes')
            )
            return [{
                'time_status': 'COLLECTING',
                'retailers': [
                    {'name': retailer, 'expected_count': 300}
                    for retailer in retailers
                ],
            }]

        service = load_service(repo, schedules)
        result = service.get_layer1_stats(
            object(), date(2026, 8, 20), datetime(2026, 8, 20, 9, 0)
        )

        self.assertEqual('COLLECTING', result['check']['status'])
        self.assertEqual([], result['failed_items'])
        self.assertTrue(all(
            category['status'] == 'COLLECTING'
            for category in result['check']['categories']
        ))
        self.assertTrue(all(
            retailer['status'] == 'COLLECTING'
            for category in result['check']['categories']
            for retailer in category['time_slots'][0]['retailers']
        ))

    def test_schedule_pending_zero_is_displayed_as_collecting(self):
        repo = RepoStub()

        def schedules(category, target_date, now=None):
            retailers = (
                ('Amazon', 'Bestbuy', 'Walmart')
                if category == 'TV' else ('Bestbuy', 'Lowes')
            )
            return [{
                'time_status': 'PENDING',
                'retailers': [
                    {'name': retailer, 'expected_count': 300}
                    for retailer in retailers
                ],
            }]

        service = load_service(repo, schedules)
        result = service.get_layer1_stats(
            object(), date(2026, 8, 20), datetime(2026, 8, 20, 7, 0)
        )

        self.assertEqual('COLLECTING', result['check']['status'])
        self.assertEqual([], result['failed_items'])
        self.assertTrue(all(
            category['status'] == 'COLLECTING'
            for category in result['check']['categories']
        ))
        self.assertTrue(all(
            retailer['status'] == 'COLLECTING'
            for category in result['check']['categories']
            for retailer in category['time_slots'][0]['retailers']
        ))

    def test_partial_schedule_never_drops_a_fixed_source_retailer(self):
        repo = self._all_ok_repo()

        def schedules(category, target_date, now=None):
            first_retailer = 'Amazon' if category == 'TV' else 'Bestbuy'
            return [{
                'time_status': None,
                'retailers': [{
                    'name': first_retailer,
                    'expected_count': 250,
                }],
            }]

        service = load_service(repo, schedules)
        result = service.get_layer1_stats(
            object(), date(2026, 8, 20), datetime(2026, 8, 21, 12, 0)
        )

        categories = result['check']['categories']
        self.assertEqual(
            ['Amazon', 'Bestbuy', 'Walmart'],
            [
                retailer['retailer']
                for retailer in categories[0]['time_slots'][0]['retailers']
            ],
        )
        self.assertEqual(
            ['Bestbuy', 'Lowes'],
            [
                retailer['retailer']
                for retailer in categories[1]['time_slots'][0]['retailers']
            ],
        )
        self.assertEqual(
            [250, 300, 300],
            [
                retailer['expected']
                for retailer in categories[0]['time_slots'][0]['retailers']
            ],
        )

    def test_appliance_summary_returns_anchor_and_date_contract(self):
        repo = RepoStub()
        repo.summary_counts = {
            ('public.ref_retail_com', 'Bestbuy'):
                (300, 2, 0, 302, 'bestbuy-ref'),
            ('public.ref_retail_com', 'Lowes'):
                (300, 21, 0, 321, 'lowes-ref'),
        }
        service = load_service(repo)

        @contextmanager
        def connection():
            yield object(), object()

        service.dx_connection = connection
        result = service.get_retail_summary(date(2026, 8, 20), 'ref')

        self.assertEqual('2026-08-20', result['inspection_date'])
        self.assertEqual('2026-08-19', result['source_date'])
        self.assertEqual('sea_ref', result['source_key'])
        self.assertFalse(result['has_extra_rank'])
        self.assertEqual('', result['extra_rank_name'])
        self.assertEqual(623, result['totals']['grand_total'])
        self.assertEqual(
            ['bestbuy-ref', 'lowes-ref'],
            [row['batch_id'] for row in result['summary']],
        )

    def test_tv_summary_and_detail_return_all_nonblank_daily_batch_ids(self):
        repo = RepoStub()
        repo.summary_counts = {
            'Amazon': (300, 0, 0, 300, 'a_20260819_000001'),
            'Bestbuy': (
                300, 100, 10, 305,
                'b_20260819_000001, b_20260819_120001',
            ),
            'Walmart': (300, 0, 0, 300, None),
        }
        repo.detail_rows = [
            ('Amazon', 300, 300, 0, 300, 'a_20260819_000001'),
            (
                'Bestbuy', 305, 300, 100, 305,
                'b_20260819_000001, b_20260819_120001',
            ),
            ('Walmart', 300, 300, 0, 300, None),
        ]
        service = load_service(repo)

        @contextmanager
        def connection():
            yield object(), object()

        service.dx_connection = connection
        summary = service.get_retail_summary(date(2026, 8, 20), 'tv')
        detail = service.get_retail_detail(date(2026, 8, 20), 'tv')

        expected_batch_ids = [
            'a_20260819_000001',
            'b_20260819_000001, b_20260819_120001',
            '',
        ]
        self.assertEqual(
            expected_batch_ids,
            [row['batch_id'] for row in summary['summary']],
        )
        self.assertEqual(
            expected_batch_ids,
            [row['batch_id'] for row in detail['results']],
        )

    def test_appliance_detail_and_raw_use_safe_core_columns(self):
        repo = RepoStub()
        repo.detail_rows = [
            ('Lowes', 190, 182, 8, 180, 'l_260819_190923')
        ]
        repo.raw_batch = 'l_260819_190923'
        repo.raw_rows = [(1, 'Lowes', 'main')]
        service = load_service(repo)

        @contextmanager
        def connection():
            yield object(), object()

        service.dx_connection = connection
        detail = service.get_retail_detail(date(2026, 8, 20), 'ldy')
        raw = service.get_retailer_raw_data(
            'LDY', 'Lowes', '일일', date(2026, 8, 20)
        )

        self.assertEqual('2026-08-19', detail['source_date'])
        self.assertEqual('l_260819_190923', detail['results'][0]['batch_id'])
        self.assertEqual('2026-08-19', raw['source_date'])
        self.assertEqual('sea_ldy', raw['source_key'])
        self.assertEqual('l_260819_190923', raw['batch_id'])
        self.assertEqual(list(
            sea_retail.SEA_RETAIL_SOURCES['ldy']['raw_columns']
        ), raw['columns'])
        raw_call = next(call for call in repo.calls if call[0] == 'appliance_raw')
        self.assertEqual(date(2026, 8, 19), raw_call[-1])


if __name__ == '__main__':
    unittest.main()
