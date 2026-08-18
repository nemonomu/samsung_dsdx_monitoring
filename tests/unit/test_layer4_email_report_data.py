import json
import unittest
from contextlib import contextmanager
from datetime import date

from tests.unit.support import ScriptedCursor, load_module, module_stub, package_stub


class DummyConnection:
    pass


def load_registry():
    return load_module(
        'apps/dx/dx_layer4/collection_status/email_registry.py',
        'layer4_email_registry_under_test',
    )


def load_service(cursor):
    @contextmanager
    def dx_connection():
        yield DummyConnection(), cursor

    registry = load_registry()
    package_name = 'apps.dx.dx_layer4.collection_status'
    return load_module(
        'apps/dx/dx_layer4/collection_status/email_services.py',
        f'{package_name}.email_services_under_test',
        stubs={
            'apps.common.db': module_stub(
                'apps.common.db', dx_connection=dx_connection,
            ),
            package_name: package_stub(package_name),
            f'{package_name}.email_registry': registry,
        },
    )


def source(key='siel_tv', date_mode='timestamp'):
    return {
        'key': key,
        'product_line': key,
        'country': 'SIEL',
        'product': 'TV',
        'label': 'SIEL TV',
        'table_name': 'dx_siel.dx_siel_tv_retail_com',
        'date_column': 'crawl_datetime',
        'date_mode': date_mode,
        'id_column': 'id',
        'batch_column': 'batch_id',
        'account_column': 'account_name',
        'has_page_type': True,
        'include_unassigned': False,
        'latest_batch': True,
        'collection_scope': 'main',
        'special_rules': None,
        'business_timezone': 'Asia/Seoul' if date_mode == 'timestamp' else None,
        'retailers': ({
            'name': 'Amazon',
            'aliases': ('Amazon',),
            'exclude_redirect': False,
        },),
    }


class EmailRegistryTests(unittest.TestCase):
    def test_registry_has_metadata_and_aliases_but_no_column_matrix(self):
        registry = load_registry()

        self.assertEqual(15, len(registry.EMAIL_REPORT_SOURCES))
        self.assertFalse(any(
            name.endswith('_COLUMNS') for name in vars(registry)
        ))
        for configured_source in registry.EMAIL_REPORT_SOURCES:
            self.assertNotIn('expected_count', configured_source)
            self.assertIn('product_line', configured_source)
            self.assertIn('email_include_skipped_columns', configured_source)
            self.assertIn('.', configured_source['table_name'])
            for retailer in configured_source['retailers']:
                self.assertNotIn('columns', retailer)
                self.assertNotIn('expected_count', retailer)
                self.assertTrue(retailer['aliases'])

        sea_tv = registry.EMAIL_REPORT_SOURCES[0]
        self.assertEqual('tv', sea_tv['product_line'])
        self.assertEqual('batch', sea_tv['date_mode'])
        self.assertFalse(sea_tv['latest_batch'])
        self.assertEqual(
            [
                'public.tv_retail_com',
                'public.ref_retail_com',
                'public.ldy_retail_com',
            ],
            [source['table_name'] for source in registry.EMAIL_REPORT_SOURCES[:3]],
        )
        tse_sources = {
            source['key']: source
            for source in registry.EMAIL_REPORT_SOURCES
            if source['country'] == 'TSE'
        }
        self.assertEqual(
            tse_sources['tse_tv']['email_include_skipped_columns'],
            ('original_sku_price', 'savings'),
        )
        self.assertEqual(
            tse_sources['tse_ref']['email_include_skipped_columns'],
            ('original_sku_price', 'savings', 'ref_refrigerator_type'),
        )
        self.assertEqual(
            tse_sources['tse_ldy']['email_include_skipped_columns'],
            ('original_sku_price', 'savings', 'ldy_loading_type'),
        )
        for configured_source in tse_sources.values():
            retailers = {
                retailer['name']: retailer
                for retailer in configured_source['retailers']
            }
            self.assertEqual(set(retailers), {'Homepro', 'Lotuss'})
            self.assertTrue(retailers['Homepro']['include_unassigned'])
            self.assertFalse(
                retailers['Homepro']['optional_if_unconfigured']
            )
            self.assertFalse(retailers['Lotuss']['include_unassigned'])
            self.assertTrue(
                retailers['Lotuss']['optional_if_unconfigured']
            )
            self.assertEqual(
                set(retailers['Lotuss']['unsupported_columns'])
                & {
                    'count_of_reviews', 'star_rating',
                    'count_of_star_ratings',
                },
                {
                    'count_of_reviews', 'star_rating',
                    'count_of_star_ratings',
                },
            )
        self.assertEqual(
            tse_sources['tse_tv']['retailers'][1]['conditional_columns'],
            ('original_sku_price', 'savings'),
        )
        for key in ('tse_ref', 'tse_ldy'):
            self.assertEqual(
                set(tse_sources[key]['retailers'][1]['unsupported_columns'])
                & {'original_sku_price', 'savings'},
                {'original_sku_price', 'savings'},
            )


class EmailReportDataTests(unittest.TestCase):
    def test_db_columns_latest_batch_and_whitespace_missing_counts(self):
        cursor = ScriptedCursor([
            {'fetchall': [
                ('sku', 'amazon'),
                ('final_sku_price', 'Amazon'),
                ('ignored', 'another-retailer'),
            ]},
            {'fetchone': ('a_20260811_000011',)},
            {'fetchone': (287, 287, 0, 287, 2, 287, 5)},
        ])
        service = load_service(cursor)

        result = service.get_email_report_data(
            date(2026, 8, 11), sources=(source(),)
        )

        self.assertTrue(result['complete'])
        row = result['sources'][0]
        self.assertEqual(
            row['column_order'], ['item', 'sku', 'final_sku_price'],
        )
        self.assertEqual(row['total_count'], 287)
        self.assertEqual(row['retailers'][0]['batch_id'], 'a_20260811_000011')
        self.assertEqual(row['retailers'][0]['columns'][2]['null_count'], 5)
        self.assertNotIn('expected_count', json.dumps(result))

        config_sql, config_params = cursor.calls[0]
        latest_sql, latest_params = cursor.calls[1]
        count_sql, count_params = cursor.calls[2]
        self.assertIn('FROM public.monitoring_retail_columns', config_sql)
        self.assertIn('is_active IS TRUE', config_sql)
        self.assertIn('COALESCE(is_del, FALSE) IS FALSE', config_sql)
        self.assertIn('COALESCE(skip_missing_check, FALSE)', config_sql)
        self.assertNotIn(
            'COALESCE(skip_missing_check, FALSE) IS FALSE', config_sql,
        )
        self.assertEqual(config_params, ['siel_tv'])
        self.assertIn(
            "source.crawl_datetime >= (%s::date::timestamp AT TIME ZONE "
            "'Asia/Seoul')",
            latest_sql,
        )
        self.assertIn("source.crawl_datetime < ((%s::date + 1)", latest_sql)
        self.assertIn("= 'main'", latest_sql)
        self.assertNotIn("IN ('main', 'bsr')", latest_sql)
        self.assertIn('ORDER BY source.id DESC LIMIT 1', latest_sql)
        self.assertEqual(count_sql.count("IN ('main', 'bsr')"), 7)
        self.assertIn('BTRIM(CAST(source.final_sku_price AS TEXT))', count_sql)
        self.assertIn('source.batch_id IS NOT DISTINCT FROM %s', count_sql)
        self.assertEqual(
            latest_params, ['amazon', '2026-08-11', '2026-08-11'],
        )
        self.assertEqual(count_params[-1], 'a_20260811_000011')

    def test_bsr_denominator_is_actual_bsr_rows(self):
        cursor = ScriptedCursor([
            {'fetchall': [('bsr_rank', 'Amazon')]},
            {'fetchone': ('a_20260811_000011',)},
            {'fetchone': (370, 370, 1, 83, 4)},
        ])
        service = load_service(cursor)

        result = service.get_email_report_data(
            date(2026, 8, 11), sources=(source(),)
        )

        columns = result['sources'][0]['retailers'][0]['columns']
        self.assertEqual(columns[0]['column'], 'item')
        self.assertEqual(result['sources'][0]['total_count'], 370)
        self.assertEqual(columns[0]['total_count'], 370)
        self.assertEqual(columns[0]['null_count'], 1)
        metric = columns[1]
        self.assertEqual(metric['total_count'], 83)
        self.assertEqual(metric['null_count'], 4)
        self.assertEqual(metric['remark'], 'BSR 페이지 실제 수집 건수')
        aggregate_sql = cursor.calls[2][0]
        self.assertIn("IN ('main', 'bsr')", aggregate_sql)
        self.assertIn("= 'bsr'", aggregate_sql)
        self.assertNotIn('100', aggregate_sql)

    def test_missing_batch_returns_zero_without_aggregate_query(self):
        cursor = ScriptedCursor([
            {'fetchall': [('sku', 'amazon')]},
            {'fetchone': None},
        ])
        service = load_service(cursor)

        result = service.get_email_report_data(
            date(2026, 8, 11), sources=(source(date_mode='text'),)
        )

        retailer = result['sources'][0]['retailers'][0]
        self.assertTrue(result['complete'])
        self.assertFalse(retailer['has_data'])
        self.assertEqual(retailer['total_count'], 0)
        self.assertEqual(len(cursor.calls), 2)
        self.assertIn(
            'LEFT(BTRIM(CAST(source.crawl_datetime AS TEXT)), 10)',
            cursor.calls[1][0],
        )

    def test_sea_tv_keeps_batch_scope_and_special_rules(self):
        configured_source = {
            **source(key='sea_tv', date_mode='batch'),
            'product_line': 'tv',
            'country': 'SEA',
            'table_name': 'public.tv_retail_com',
            'date_column': 'batch_id',
            'latest_batch': False,
            'collection_scope': 'all',
            'special_rules': 'sea_tv',
            'retailers': ({
                'name': 'Amazon',
                'aliases': ('Amazon',),
                'exclude_redirect': True,
            },),
        }
        cursor = ScriptedCursor([
            {'fetchall': [
                ('original_sku_price', 'amazon'),
                ('bsr_rank', 'amazon'),
            ]},
            {'fetchone': (350, 350, 0, 350, 7, 87, 4)},
            {'fetchone': (2,)},
        ])
        service = load_service(cursor)

        result = service.get_email_report_data(
            date(2026, 8, 11), sources=(configured_source,)
        )

        retailer = result['sources'][0]['retailers'][0]
        self.assertEqual(retailer['total_count'], 350)
        self.assertEqual(retailer['columns'][0]['column'], 'item')
        self.assertEqual(retailer['columns'][2]['total_count'], 87)
        self.assertEqual(retailer['columns'][2]['null_count'], 4)
        self.assertEqual(retailer['redirect_true_count'], 2)
        aggregate_sql, aggregate_params = cursor.calls[1]
        self.assertIn('FROM public.tv_retail_com source', aggregate_sql)
        self.assertIn("from '([0-9]{8})'", aggregate_sql)
        self.assertIn('COALESCE(source.redirect, FALSE) IS NOT TRUE', aggregate_sql)
        self.assertIn("= 'bsr'", aggregate_sql)
        self.assertNotIn("IN ('main', 'bsr')", aggregate_sql)
        self.assertEqual(aggregate_params[-1], '20260811')
        redirect_sql = cursor.calls[2][0]
        self.assertIn('FROM public.tv_retail_com source', redirect_sql)
        self.assertIn('source.redirect IS TRUE', redirect_sql)
        self.assertNotIn('ORDER BY source.id DESC LIMIT 1', aggregate_sql)

        promotion_total, promotion_missing, promotion_remark = (
            service._column_metrics(
                configured_source, configured_source['retailers'][0],
                'promotion_type',
            )
        )
        self.assertIn('source.promotion_position', promotion_total)
        self.assertIn('GREATEST', promotion_missing)
        self.assertIn('source.promotion_type', promotion_missing)
        self.assertEqual(promotion_remark, '프로모션 페이지 수집 항목')

    def test_tse_latest_batch_anchor_excludes_unassigned_rows(self):
        tse_source = {
            **source(key='tse_tv', date_mode='text'),
            'product_line': 'tse_tv',
            'country': 'TSE',
            'table_name': 'dx_tse.dx_tse_tv_retail_com',
            'has_page_type': False,
            'include_unassigned': True,
            'collection_scope': 'all',
            'retailers': ({
                'name': 'Homepro',
                'aliases': ('Homepro',),
                'exclude_redirect': False,
            },),
        }
        cursor = ScriptedCursor([
            {'fetchall': [('sku', 'homepro')]},
            {'fetchone': ('homepro_20260811',)},
            {'fetchone': (11, 11, 0, 11, 0)},
        ])
        service = load_service(cursor)

        result = service.get_email_report_data(
            date(2026, 8, 11), sources=(tse_source,)
        )

        self.assertTrue(result['complete'])
        latest_sql = cursor.calls[1][0]
        aggregate_sql = cursor.calls[2][0]
        self.assertNotIn('source.account_name IS NULL', latest_sql)
        self.assertIn('source.account_name IS NULL', aggregate_sql)
        self.assertNotIn('source.page_type', aggregate_sql)
        self.assertNotIn("IN ('main', 'bsr')", aggregate_sql)

    def test_tse_retailers_keep_separate_unassigned_scope_and_sum_counts(self):
        registry = load_registry()
        tse_source = next(
            configured_source
            for configured_source in registry.EMAIL_REPORT_SOURCES
            if configured_source['key'] == 'tse_ref'
        )
        cursor = ScriptedCursor([
            {'fetchall': [
                ('sku', 'homepro', False),
                ('sku', 'lotuss', False),
            ]},
            {'fetchone': ('homepro_20260814',)},
            {'fetchone': (300, 300, 0, 300, 0)},
            {'fetchone': ('l20260814_094943',)},
            {'fetchone': (45, 45, 0, 45, 0)},
        ])
        service = load_service(cursor)

        result = service.get_email_report_data(
            date(2026, 8, 14), sources=(tse_source,)
        )

        self.assertTrue(result['complete'])
        configured = result['sources'][0]
        self.assertEqual(configured['total_count'], 345)
        self.assertEqual(
            [retailer['retailer'] for retailer in configured['retailers']],
            ['Homepro', 'Lotuss'],
        )
        self.assertEqual(
            [retailer['total_count'] for retailer in configured['retailers']],
            [300, 45],
        )
        homepro_latest_sql = cursor.calls[1][0]
        homepro_count_sql = cursor.calls[2][0]
        lotuss_latest_sql = cursor.calls[3][0]
        lotuss_count_sql = cursor.calls[4][0]
        self.assertNotIn('source.account_name IS NULL', homepro_latest_sql)
        self.assertIn('source.account_name IS NULL', homepro_count_sql)
        self.assertNotIn('source.account_name IS NULL', lotuss_latest_sql)
        self.assertNotIn('source.account_name IS NULL', lotuss_count_sql)

    def test_inactive_lotuss_config_is_omitted_but_tse_source_completes(self):
        registry = load_registry()
        tse_source = next(
            configured_source
            for configured_source in registry.EMAIL_REPORT_SOURCES
            if configured_source['key'] == 'tse_ref'
        )
        cursor = ScriptedCursor([
            {'fetchall': [('sku', 'homepro', False)]},
            {'fetchone': ('homepro_20260818',)},
            {'fetchone': (300, 300, 0, 300, 0)},
        ])
        service = load_service(cursor)

        result = service.get_email_report_data(
            date(2026, 8, 18), sources=(tse_source,)
        )

        self.assertTrue(result['success'])
        self.assertTrue(result['complete'])
        self.assertEqual(result['errors'], [])
        configured = result['sources'][0]
        self.assertEqual(configured['total_count'], 300)
        self.assertEqual(
            [retailer['retailer'] for retailer in configured['retailers']],
            ['Homepro'],
        )
        self.assertEqual(len(cursor.calls), 3)

    def test_missing_homepro_config_still_marks_tse_source_incomplete(self):
        registry = load_registry()
        tse_source = next(
            configured_source
            for configured_source in registry.EMAIL_REPORT_SOURCES
            if configured_source['key'] == 'tse_ref'
        )
        cursor = ScriptedCursor([
            {'fetchall': [('sku', 'lotuss', False)]},
        ])
        service = load_service(cursor)

        result = service.get_email_report_data(
            date(2026, 8, 18), sources=(tse_source,)
        )

        self.assertFalse(result['success'])
        self.assertFalse(result['complete'])
        self.assertEqual(result['sources'], [])
        self.assertEqual(result['errors'][0]['source'], 'tse_ref')
        self.assertEqual(len(cursor.calls), 1)

    def test_active_but_unusable_lotuss_config_still_fails_closed(self):
        registry = load_registry()
        tse_source = next(
            configured_source
            for configured_source in registry.EMAIL_REPORT_SOURCES
            if configured_source['key'] == 'tse_ref'
        )
        cursor = ScriptedCursor([{'fetchall': [
            ('sku', 'homepro', False),
            ('count_of_reviews', 'lotuss', False),
        ]}])
        service = load_service(cursor)

        result = service.get_email_report_data(
            date(2026, 8, 18), sources=(tse_source,)
        )

        self.assertFalse(result['success'])
        self.assertFalse(result['complete'])
        self.assertEqual(result['sources'], [])
        self.assertEqual(result['errors'][0]['source'], 'tse_ref')
        self.assertEqual(len(cursor.calls), 1)

    def test_lotuss_unsupported_columns_are_omitted_but_partial_fields_remain(self):
        registry = load_registry()
        tse_source = next(
            configured_source
            for configured_source in registry.EMAIL_REPORT_SOURCES
            if configured_source['key'] == 'tse_ref'
        )
        cursor = ScriptedCursor([{'fetchall': [
            ('sku', 'homepro', False),
            ('count_of_reviews', 'homepro', False),
            ('original_sku_price', 'homepro', True),
            ('savings', 'homepro', True),
            ('ref_refrigerator_type', 'homepro', True),
            ('sku', 'lotuss', False),
            ('count_of_reviews', 'lotuss', False),
            ('star_rating', 'lotuss', False),
            ('count_of_star_ratings', 'lotuss', False),
            ('original_sku_price', 'lotuss', True),
            ('savings', 'lotuss', True),
            ('ref_refrigerator_type', 'lotuss', True),
        ]}])
        service = load_service(cursor)

        configured = service._configured_retailers(cursor, tse_source)
        homepro_columns = configured[0]['columns']
        lotuss_columns = configured[1]['columns']

        self.assertIn('count_of_reviews', homepro_columns)
        self.assertIn('original_sku_price', homepro_columns)
        self.assertIn('savings', homepro_columns)
        self.assertIn('ref_refrigerator_type', homepro_columns)
        self.assertEqual(
            lotuss_columns, ('item', 'sku', 'ref_refrigerator_type'),
        )

    def test_lotuss_tv_discount_columns_use_conditional_denominator(self):
        registry = load_registry()
        tse_source = next(
            configured_source
            for configured_source in registry.EMAIL_REPORT_SOURCES
            if configured_source['key'] == 'tse_tv'
        )
        lotuss = tse_source['retailers'][1]
        service = load_service(ScriptedCursor([]))

        for column in ('original_sku_price', 'savings'):
            with self.subTest(column=column):
                denominator, missing, remark = service._column_metrics(
                    tse_source, lotuss, column,
                )
                self.assertIn('source.original_sku_price', denominator)
                self.assertIn('source.savings', denominator)
                self.assertIn(' OR ', denominator)
                self.assertIn('source.original_sku_price', missing)
                self.assertIn('source.savings', missing)
                self.assertIn(' OR ', missing)
                self.assertIn(f'source.{column}', missing)
                self.assertEqual(remark, '')

    def test_tse_email_includes_only_approved_skipped_columns(self):
        registry = load_registry()
        tse_source = next(
            source for source in registry.EMAIL_REPORT_SOURCES
            if source['key'] == 'tse_tv'
        )
        tse_source = {
            **tse_source,
            'retailers': (tse_source['retailers'][0],),
        }
        cursor = ScriptedCursor([
            {'fetchall': [
                ('sku', 'homepro', False),
                ('original_sku_price', 'homepro', True),
                ('savings', 'homepro', True),
                ('product_url', 'homepro', True),
            ]},
            {'fetchone': ('homepro_20260811',)},
            {'fetchone': (11, 11, 0, 11, 1, 11, 2, 11, 3)},
        ])
        service = load_service(cursor)

        result = service.get_email_report_data(
            date(2026, 8, 11), sources=(tse_source,)
        )

        self.assertTrue(result['complete'])
        columns = result['sources'][0]['column_order']
        self.assertEqual(
            columns, ['item', 'sku', 'original_sku_price', 'savings'],
        )
        self.assertNotIn('product_url', columns)
        config_sql = cursor.calls[0][0]
        self.assertIn(
            'AS skip_missing_check', config_sql,
        )
        self.assertNotIn(
            'COALESCE(skip_missing_check, FALSE) IS FALSE', config_sql,
        )

    def test_tse_email_column_counts_match_the_approved_source_schema(self):
        registry = load_registry()
        base_columns = {
            'tse_tv': (
                'country', 'retailer_sku_name', 'star_rating', 'sku',
                'count_of_star_ratings', 'count_of_reviews', 'screen_size',
                'item', 'final_sku_price', 'product_url', 'account_name',
            ),
            'tse_ref': (
                'country', 'ref_capacity', 'sku', 'retailer_sku_name',
                'star_rating', 'count_of_reviews', 'item',
                'count_of_star_ratings', 'final_sku_price', 'product_url',
                'account_name',
            ),
            'tse_ldy': (
                'country', 'star_rating', 'retailer_sku_name', 'sku',
                'count_of_star_ratings', 'count_of_reviews', 'item',
                'ldy_capacity', 'final_sku_price', 'product_url',
                'account_name',
            ),
        }
        expected_counts = {'tse_tv': 13, 'tse_ref': 14, 'tse_ldy': 14}

        for key, expected_count in expected_counts.items():
            with self.subTest(product_line=key):
                configured_source = next(
                    source for source in registry.EMAIL_REPORT_SOURCES
                    if source['key'] == key
                )
                configured_source = {
                    **configured_source,
                    'retailers': (configured_source['retailers'][0],),
                }
                extras = configured_source['email_include_skipped_columns']
                configured_rows = [
                    (column, 'homepro', False)
                    for column in base_columns[key]
                ] + [
                    (column, 'homepro', True) for column in extras
                ] + [
                    ('unapproved_email_skip', 'homepro', True),
                ]
                cursor = ScriptedCursor([{'fetchall': configured_rows}])
                service = load_service(cursor)

                retailer = service._configured_retailers(
                    cursor, configured_source,
                )[0]
                columns = retailer['columns']

                self.assertEqual(len(columns), expected_count)
                self.assertEqual(columns[0], 'item')
                self.assertEqual(columns.count('item'), 1)
                self.assertEqual(columns.count('product_url'), 1)
                self.assertNotIn('unapproved_email_skip', columns)
                for column in extras:
                    self.assertIn(column, columns)

    def test_non_tse_columns_remain_db_driven_without_product_url_injection(self):
        configured_source = source(key='sea_ref', date_mode='text')
        configured_source['product_line'] = 'sea_ref'
        configured_source['email_include_skipped_columns'] = ()
        configured_source['retailers'] = ({
            'name': 'Bestbuy',
            'aliases': ('Bestbuy', 'BestBuy'),
            'exclude_redirect': False,
        },)
        cursor = ScriptedCursor([{'fetchall': [
            ('original_sku_price', 'bestbuy', False),
            ('product_url', 'bestbuy', True),
        ]}])
        service = load_service(cursor)

        columns = service._configured_retailers(
            cursor, configured_source,
        )[0]['columns']

        self.assertEqual(columns, ('item', 'original_sku_price'))
        self.assertNotIn('product_url', columns)

    def test_missing_or_unsafe_db_configuration_marks_source_incomplete(self):
        for configured_rows in (
            [],
            [('sku;drop table x', 'amazon')],
        ):
            with self.subTest(configured_rows=configured_rows):
                cursor = ScriptedCursor([{'fetchall': configured_rows}])
                service = load_service(cursor)

                result = service.get_email_report_data(
                    date(2026, 8, 11), sources=(source(key='broken'),)
                )

                self.assertFalse(result['success'])
                self.assertFalse(result['complete'])
                self.assertEqual(result['sources'], [])
                self.assertEqual(result['errors'][0]['source'], 'broken')
                self.assertEqual(len(cursor.calls), 1)


if __name__ == '__main__':
    unittest.main()
