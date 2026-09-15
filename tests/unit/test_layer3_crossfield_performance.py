import unittest
from datetime import date
from unittest.mock import Mock, patch

from tests.unit import test_layer3_stopped_market_monitoring as support


class CrossfieldConnectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        support.Layer3StoppedMarketMonitoringTests.setUpClass()
        cls.service = support.Layer3StoppedMarketMonitoringTests.service

    def run_rules(self, *, rule_id=None, fail_first=False, supplied_cursor=False):
        cursor = Mock()
        cursor.description = [('item',)]
        cursor.fetchall.return_value = [('example',)]
        connection = Mock()
        connection.cursor.return_value = cursor
        rules = [dict(rule_id=i, section_code='tv_retail', table_name='tv_retail_com',
                      date_column='crawl_datetime', query=f'SELECT item FROM {{table}} WHERE rule_{i} = %s')
                 for i in (1, 2)]

        def execute(sql, params=None):
            if fail_first and 'WHERE rule_1' in sql:
                raise RuntimeError('invalid rule')

        cursor.execute.side_effect = execute
        with patch.object(self.service, 'get_dx_connection', return_value=connection) as connect, \
                patch.object(self.service, 'load_crossfield_rules', return_value=rules), \
                patch.object(self.service, 'load_page_exclusions', return_value=[]), \
                patch.object(self.service, 'get_all_no_review_texts', return_value=''), \
                patch.object(self.service, 'apply_tv_validation_scope', side_effect=lambda query, *_args, **_kwargs: query):
            result = self.service.validate_crossfield(
                date(2026, 9, 14), 'tv_retail',
                cursor=cursor if supplied_cursor else None, rule_id=rule_id)
        return result, cursor, connection, connect

    def test_all_rules_share_one_connection_and_close_it(self):
        result, cursor, connection, connect = self.run_rules()
        self.assertEqual(2, result['total_errors'])
        connect.assert_called_once_with()
        cursor.close.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_detail_runs_only_selected_rule_and_keeps_callers_cursor_open(self):
        result, cursor, connection, connect = self.run_rules(rule_id='2', supplied_cursor=True)
        self.assertEqual([2], [rule['rule_id'] for rule in result['rule_results']])
        self.assertFalse(any('WHERE rule_1' in call.args[0] for call in cursor.execute.call_args_list))
        connect.assert_not_called()
        cursor.close.assert_not_called()
        connection.close.assert_not_called()

    def test_failed_rule_rolls_back_before_next_rule_on_shared_connection(self):
        result, cursor, connection, connect = self.run_rules(fail_first=True)
        self.assertEqual([0, 1], [rule['error_count'] for rule in result['rule_results']])
        statements = [call.args[0] for call in cursor.execute.call_args_list]
        rollback = statements.index('ROLLBACK TO SAVEPOINT crossfield_rule')
        second_query = next(i for i, sql in enumerate(statements) if 'WHERE rule_2' in sql)
        self.assertLess(rollback, second_query)
        connect.assert_called_once_with()
        connection.close.assert_called_once_with()
