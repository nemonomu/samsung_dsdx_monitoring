import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from apps.common import amazon_review_history as history
from apps.dx.dx_layer3.cross_field import seg_services, siel_services
from tests.unit.support import ScriptedCursor


def row(country='SEG', **overrides):
    result = {
        'id': 100, 'country': country, 'account_name': 'Amazon',
        'item': 'B000000001', 'page_type': 'MAIN', 'redirect': False,
        'crawl_strdatetime': '2026-09-30 08:00:00',
        'crawl_datetime': datetime(2026, 9, 29, 23, tzinfo=timezone.utc),
        'detailed_review_content': None, 'star_rating': '4.5',
        'count_of_star_ratings': '10', 'count_of_reviews': None,
    }
    result.update(overrides)
    return result


def day(day_number, body_id=None, item='B000000001'):
    return {'item': item, 'source_date': date(2026, 9, day_number),
            'history_rows': 2, 'body_record_id': body_id}


class AmazonReviewHistoryTests(unittest.TestCase):
    def evaluate(self, rows=None, summaries=(), evidence=(), country='SEG', product=None):
        service = seg_services if country == 'SEG' else siel_services
        parser = service.parse_seg_number if country == 'SEG' else service.parse_siel_number
        cursor = ScriptedCursor([{'fetchall': summaries}, {'fetchall': evidence}])
        findings, comparisons = history.load_findings(
            cursor, country, product or country.lower() + '_tv',
            [row(country)] if rows is None else rows,
            date_of=service._detail_row_source_date, parse_number=parser,
        )
        return findings, comparisons, cursor

    def test_prior_body_is_anomaly_even_if_latest_history_body_missing(self):
        for country in ('SEG', 'SIEL'):
            with self.subTest(country=country):
                evidence = row(country, id=80, detailed_review_content='review1 - Good')
                findings, comparisons, cursor = self.evaluate(
                    country=country, summaries=[day(20, 80), day(29)], evidence=[evidence],
                )
                self.assertEqual('2026-09-20', findings['100']['previous_source_date'])
                self.assertEqual(2, findings['100']['review_history_days'])
                self.assertEqual('2026-09-20', findings['100']['review_history_start'])
                self.assertEqual('2026-09-29', findings['100']['review_history_end'])
                self.assertEqual([evidence], comparisons)
                self.assertEqual(([80],), cursor.calls[1][1])

    def test_prior_rows_without_body_are_normal_even_with_positive_ratings(self):
        for country in ('SEG', 'SIEL'):
            findings, evidence, cursor = self.evaluate(country=country, summaries=[day(21), day(29)])
            self.assertEqual({}, findings)
            self.assertEqual([], evidence)
            self.assertEqual(1, len(cursor.calls))

    def test_no_history_with_rating_and_either_count_is_anomaly(self):
        for counts in ({'count_of_star_ratings': '12', 'count_of_reviews': None},
                       {'count_of_star_ratings': None, 'count_of_reviews': '1'}):
            findings, comparisons, _ = self.evaluate(rows=[row(**counts)])
            self.assertEqual(0, findings['100']['review_history_days'])
            self.assertIsNone(findings['100']['previous_source_date'])
            self.assertEqual([], comparisons)

    def test_no_history_without_positive_rating_and_count_does_not_trigger_this_rule(self):
        for fields in ({'star_rating': None}, {'star_rating': '0'},
                       {'count_of_star_ratings': '0'}, {'count_of_star_ratings': None}):
            with self.subTest(fields=fields):
                self.assertEqual({}, self.evaluate(rows=[row(**fields)])[0])

    def test_body_loss_does_not_depend_on_current_rating_or_count(self):
        findings, _, _ = self.evaluate(
            rows=[row(star_rating=None, count_of_star_ratings=None)], summaries=[day(28, 90)],
        )
        self.assertIn('100', findings)

    def test_window_excludes_today_and_day_eleven_and_keeps_day_ten(self):
        # Multiple displayed dates can return daily aggregates outside one row's window.
        rows = [row(id=99, crawl_strdatetime='2026-09-29'), row()]
        findings, _, _ = self.evaluate(rows=rows, summaries=[day(19, 70), day(20), day(30, 90)])
        self.assertIn('99', findings)
        self.assertNotIn('100', findings)
        findings, _, _ = self.evaluate(summaries=[day(20, 80)])
        self.assertIn('100', findings)

    def test_each_missing_row_uses_its_own_date_window_and_item(self):
        findings, _, cursor = self.evaluate(
            rows=[row(id=90, crawl_strdatetime='2026-09-29'), row(), row(id=101, item='OTHER')],
            summaries=[day(29, 85)],
        )
        self.assertIsNone(findings['90']['previous_source_date'])
        self.assertEqual('2026-09-29', findings['100']['previous_source_date'])
        self.assertIsNone(findings['101']['previous_source_date'])
        self.assertEqual(('2026-09-19', '2026-09-30', 'SEG', ['B000000001', 'OTHER']), cursor.calls[0][1])

    def test_present_body_other_retailer_redirect_and_missing_item_skip_history_query(self):
        for fields in ({'detailed_review_content': 'review1 - Good'},
                       {'account_name': 'Flipkart'}, {'redirect': True}, {'item': None}):
            findings, _, cursor = self.evaluate(rows=[row(**fields)])
            self.assertEqual({}, findings)
            self.assertEqual([], cursor.calls)
        self.assertEqual([], self.evaluate(product='seg_ldy')[2].calls)

    def test_null_sentinels_are_missing_bodies(self):
        for body in (None, '', '  ', '\n\t', 'NULL', ' None ', '-', 'n/a'):
            self.assertIn('100', self.evaluate(rows=[row(detailed_review_content=body)])[0])

    def test_history_sql_uses_bound_item_country_and_ten_day_scope(self):
        for country, products in (('SEG', ('tv', 'ref')), ('SIEL', ('tv', 'ref', 'ldy'))):
            for product in products:
                _, _, cursor = self.evaluate(country=country, product=country.lower() + '_' + product)
                sql, params = cursor.calls[0]
                self.assertEqual(('2026-09-20', '2026-09-30', country, ['B000000001']), params)
                self.assertIn(f'dx_{country.lower()}.dx_{country.lower()}_{product}_retail_com', sql)
                self.assertIn('source.redirect IS NOT TRUE', sql)
                self.assertIn("IN ('main', 'bsr')", sql)
                self.assertIn('= ANY(%s)', sql)
                self.assertNotIn('B000000001', sql)
                if country == 'SIEL':
                    self.assertIn("AT TIME ZONE 'Asia/Seoul'", sql)

    def test_database_error_is_not_treated_as_absent_history(self):
        cursor = Mock()
        cursor.execute.side_effect = RuntimeError('database unavailable')
        with self.assertRaisesRegex(RuntimeError, 'database unavailable'):
            history.load_findings(cursor, 'SEG', 'seg_tv', [row()],
                                  date_of=seg_services._detail_row_source_date,
                                  parse_number=seg_services.parse_seg_number)


class AmazonReviewIntegrationTests(unittest.TestCase):
    def detail(self, country, summaries, evidence=(), corrections=()):
        service = seg_services if country == 'SEG' else siel_services
        product = country.lower() + '_tv'
        rule = dict(history.RULE_SPEC, id=50, validation_type=history.RULE_KEY,
                    retailer='Amazon', detail_code=product + '_' + history.RULE_KEY,
                    select_fields='', sort_order=200)
        history_steps = [{'fetchall': summaries}, {'fetchall': evidence}] if evidence else [{'fetchall': summaries}]
        correction_step = {'fetchall': corrections}
        exclusions_step = {'fetchall': []}
        steps = [{'fetchall': [rule]}, {'fetchall': [row(country)]}]
        steps += ([exclusions_step] + history_steps + [correction_step] if country == 'SEG'
                  else [correction_step, exclusions_step] + history_steps)
        cursor = ScriptedCursor(steps)
        detail_fn = getattr(service, f'get_{country.lower()}_cross_field_rule_detail')
        return detail_fn(cursor, date(2026, 9, 30), product, 50, days=1)

    def test_body_evidence_outside_display_window_is_read_only_and_not_counted(self):
        for country in ('SEG', 'SIEL'):
            with self.subTest(country=country):
                evidence = row(country, id=80, crawl_strdatetime='2026-09-20 08:00:00',
                               crawl_datetime=datetime(2026, 9, 19, 23, tzinfo=timezone.utc),
                               detailed_review_content='review1 - Good')
                result = self.detail(country, [day(20, 80)], [evidence])
                self.assertTrue(result['found'])
                self.assertEqual(1, result['total_anomalies'])
                self.assertIn('detailed_review_content', result['editable_columns'])
                self.assertEqual(['comparison_history', 'target'], [r['row_role'] for r in result['anomalies']])
                self.assertEqual('2026-09-20', result['anomalies'][1]['previous_source_date'])
                self.assertIn('2026-09-20', result['query'])
                self.assertNotIn('    review_history_days', result['query'])

    def test_no_history_finding_and_normal_confirmation(self):
        for country in ('SEG', 'SIEL'):
            result = self.detail(country, [])
            self.assertEqual(1, result['total_anomalies'])
            self.assertEqual(0, result['anomalies'][0]['review_history_days'])
            result = self.detail(country, [], corrections=[{
                'record_id': 100, 'rule_id': 50, 'column_name': 'detailed_review_content',
            }])
            self.assertEqual(0, result['total_anomalies'])

    def test_existing_empty_history_is_normal_in_both_services(self):
        for country in ('SEG', 'SIEL'):
            self.assertEqual(0, self.detail(country, [day(29)])['total_anomalies'])

    def test_rule_registration_covers_only_supported_amazon_sources(self):
        sql = Path('sql/seed_amazon_review_body_history.sql').read_text(encoding='utf-8')
        for product in ('seg_tv', 'seg_ref', 'siel_tv', 'siel_ref', 'siel_ldy'):
            self.assertIn(f"'{product}_retail'", sql)
        self.assertNotIn("'seg_ldy_retail'", sql)
        self.assertIn('WHERE NOT EXISTS', sql)
        self.assertIn('Expected 5 active Amazon history rules', sql)


if __name__ == '__main__':
    unittest.main()
