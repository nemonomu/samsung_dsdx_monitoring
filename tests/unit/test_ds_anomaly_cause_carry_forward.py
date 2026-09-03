import unittest
from contextlib import contextmanager
from datetime import date
from unittest.mock import Mock, patch

from tests.unit.support import (
    ScriptedCursor,
    load_module,
    module_stub,
    package_stub,
)


def anomaly(**overrides):
    values = {
        'retailersku': 'SKU-1',
        'title': 'Portable SSD',
        'retailprice': '1149.99',
        'ships_from': '',
        'sold_by': 'Seller A',
        'imageurl': 'https://example.com/one.jpg',
        'cause': '',
    }
    values.update(overrides)
    return values


class AnomalyCauseMatchingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.causes = load_module(
            'apps/ds/ds_layer2/report/anomaly_causes.py',
            'ds_anomaly_causes_under_test',
        )

    def test_non_null_values_are_ignored_when_null_layout_matches(self):
        previous = anomaly(cause='상품페이지 내 항목 부재')
        current = anomaly(
            title='A renamed product',
            retailprice='1299.00',
            sold_by='A different seller',
            imageurl='https://example.com/two.jpg',
        )

        carried = self.causes.carry_forward_causes([current], [previous])

        self.assertEqual('상품페이지 내 항목 부재', carried[0]['cause'])

    def test_signature_tracks_each_requested_anomaly_state(self):
        cases = [
            ({'title': None}, 'title_null'),
            ({'imageurl': None}, 'imageurl_null'),
            ({'imageurl': 'not-an-http-url'}, 'imageurl_invalid'),
            ({'retailprice': None}, 'retailprice_null'),
            ({'ships_from': None}, 'ships_from_null'),
            ({'sold_by': None}, 'sold_by_null'),
        ]

        for overrides, expected in cases:
            with self.subTest(expected=expected):
                self.assertIn(
                    expected,
                    self.causes.anomaly_signature(anomaly(**overrides)),
                )

    def test_different_null_field_does_not_match(self):
        previous = anomaly(ships_from='', sold_by='Seller A', cause='전날 원인')
        current = anomaly(ships_from='Amazon', sold_by='')

        carried = self.causes.carry_forward_causes([current], [previous])

        self.assertEqual('', carried[0]['cause'])

    def test_image_null_and_invalid_are_different_signatures(self):
        image_null = anomaly(imageurl=None, ships_from='Amazon')
        image_invalid = anomaly(imageurl='ftp://example.com/a.jpg', ships_from='Amazon')

        self.assertNotEqual(
            self.causes.anomaly_signature(image_null),
            self.causes.anomaly_signature(image_invalid),
        )
        self.assertIn(
            'imageurl_invalid',
            self.causes.anomaly_signature(image_invalid),
        )

    def test_existing_cause_is_not_overwritten(self):
        previous = anomaly(cause='전날 원인')
        current = anomaly(cause='오늘 확정 원인')

        carried = self.causes.carry_forward_causes([current], [previous])

        self.assertEqual('오늘 확정 원인', carried[0]['cause'])

    def test_ambiguous_previous_causes_are_not_carried(self):
        previous = [
            anomaly(cause='원인 A'),
            anomaly(cause='원인 B'),
        ]

        carried = self.causes.carry_forward_causes([anomaly()], previous)

        self.assertEqual('', carried[0]['cause'])

    def test_blank_sku_is_not_carried(self):
        previous = anomaly(retailersku='', cause='전날 원인')
        current = anomaly(retailersku='')

        carried = self.causes.carry_forward_causes([current], [previous])

        self.assertEqual('', carried[0]['cause'])


class PreviousAnomalyRepositoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repository = load_module(
            'apps/ds/ds_layer2/report/report_repositories.py',
            'ds_report_repository_carry_forward_under_test',
            stubs={
                'apps.common.db': module_stub(
                    'apps.common.db', ds_connection=None,
                ),
                'apps.common.response': module_stub(
                    'apps.common.response', log_error=lambda error: str(error),
                ),
            },
        )

    def test_query_limits_matches_to_active_previous_day_causes(self):
        cursor = ScriptedCursor([{
            'fetchall': [(
                'SKU-1', 'Portable SSD', '1149.99', None,
                'Seller A', 'https://example.com/a.jpg', '원인 A',
            )],
        }])

        result = self.repository.fetch_previous_anomalies_with_causes(
            cursor, date(2026, 9, 2), 17,
        )

        sql, params = cursor.calls[0]
        self.assertEqual((date(2026, 9, 2), 17), params)
        self.assertIn('o.is_active = 1', sql)
        self.assertIn('a.is_del = 0', sql)
        self.assertEqual('원인 A', result[0]['cause'])

    def test_crawler_marker_is_replaced_by_carried_cause(self):
        self.assertEqual(
            '상품페이지 내 항목 부재',
            self.repository._resolved_cause(
                'crawler_null_capture', '상품페이지 내 항목 부재',
            ),
        )

    def test_existing_user_cause_is_preserved(self):
        self.assertEqual(
            '오늘 확정 원인',
            self.repository._resolved_cause(
                '오늘 확정 원인', '전날 원인',
            ),
        )

    def test_crawler_marker_without_match_becomes_blank(self):
        self.assertEqual(
            '',
            self.repository._resolved_cause('crawler_null_capture', ''),
        )

    def test_existing_capture_row_receives_carried_cause_on_save(self):
        cursor = ScriptedCursor([
            {},
            {},
            {'fetchone': (31,)},
            {},
            {'fetchall': [(
                34943, 'SKU-1', 40282, 'crawler_null_capture', '',
            )]},
            {},
        ])

        class Connection:
            committed = False

            def commit(self):
                self.committed = True

        connection = Connection()
        stats = {
            'expected_count': 1,
            'final_batch_count': 1,
            'total_count': 1,
            'completion_rate': 100,
            'rerun_count': 0,
            'anomaly_total': 1,
            'anomaly_title_null': 0,
            'anomaly_image_null': 0,
            'anomaly_partial_null': 1,
            'anomaly_price_zero': 0,
        }
        current = anomaly(
            country_code='JP',
            producturl='https://example.com/product',
            cause='상품페이지 내 항목 부재',
        )

        self.repository.db_save_retailer_transaction(
            '2026-09-03', 17, stats, [current], '', 'tester',
            '2026-09-03 10:30:00', cursor, connection,
        )

        anomaly_update = next(
            (sql, params) for sql, params in cursor.calls
            if 'UPDATE ssd_crawl_db.ds_monitoring_report_anomaly' in sql
            and 'SET is_del = 0' in sql
        )
        self.assertIn('cause = %s', anomaly_update[0])
        self.assertEqual('상품페이지 내 항목 부재', anomaly_update[1][7])
        self.assertTrue(connection.committed)


class SaveRetailerCarryForwardTests(unittest.TestCase):
    def test_save_uses_exact_previous_calendar_day(self):
        causes = load_module(
            'apps/ds/ds_layer2/report/anomaly_causes.py',
            'apps.ds.ds_layer2.report.anomaly_causes',
        )
        previous_fetch = Mock(return_value=[
            anomaly(cause='상품페이지 내 항목 부재'),
        ])
        save_transaction = Mock(return_value=(31, [401]))
        repository = module_stub(
            'apps.ds.ds_layer2.report.report_repositories',
            fetch_previous_anomalies_with_causes=previous_fetch,
            db_save_retailer_transaction=save_transaction,
        )
        cursor = object()
        connection = object()

        @contextmanager
        def ds_connection():
            yield connection, cursor

        package_name = 'apps.ds.ds_layer2.report'
        service = load_module(
            'apps/ds/ds_layer2/report/report_services.py',
            f'{package_name}.report_services_carry_forward_under_test',
            stubs={
                'apps.common.db': module_stub(
                    'apps.common.db', ds_connection=ds_connection,
                ),
                'apps.common.response': module_stub(
                    'apps.common.response', log_error=lambda error: str(error),
                ),
                'apps.ds.ds_layer2.stats.stats_repositories': module_stub(
                    'apps.ds.ds_layer2.stats.stats_repositories',
                    fetch_batches_for_date=None,
                    fetch_expected_count=None,
                    fetch_quality_counts=None,
                    fetch_quality_counts_by_time_range=None,
                ),
                package_name: package_stub(package_name),
                f'{package_name}.report_repositories': repository,
                f'{package_name}.anomaly_causes': causes,
                'apps.ds.ds_layer4.report.report_services': module_stub(
                    'apps.ds.ds_layer4.report.report_services',
                    get_file_info_for_date=None,
                ),
            },
        )

        with patch.object(
            service,
            'get_retailer_stats',
            return_value={'retailer_id': 17},
        ):
            result = service.save_retailer(
                '2026-09-03', 'Amazon_USA', [anomaly()], '', 'tester',
            )

        self.assertTrue(result['success'])
        previous_fetch.assert_called_once_with(cursor, date(2026, 9, 2), 17)
        saved_anomalies = save_transaction.call_args.args[3]
        self.assertEqual('상품페이지 내 항목 부재', saved_anomalies[0]['cause'])


if __name__ == '__main__':
    unittest.main()
