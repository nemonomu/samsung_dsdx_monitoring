"""SEDA cross-field checks on D-1 latest MAIN batches; history is display-only."""

from datetime import date, timedelta

from apps.common.crossfield_history import build_detail_history
from apps.common.inspection_dates import resolve_monitoring_date
from apps.common.null_review_evidence import exclude_page_absent_records
from apps.common.seda_retail import get_seda_source, display_seda_retailer
from apps.dx.dx_layer2.seda_null_validation import _scope, _rows
from .seda_rules import SEDA_RULE_SPECS, body_numbers, evaluate_seda_row, missing, recommendation_valid


RETAILER = 'Casas Bahia'
RULE_KEY = 'recommendation_intent'
RULE_NAME = SEDA_RULE_SPECS[RULE_KEY]['detail_name']
RULE_DESCRIPTION = SEDA_RULE_SPECS[RULE_KEY]['description']
SELECT_FIELDS = 'count_of_reviews|recommendation_intent'
SUMMARY_HISTORY_DAYS = 5
SELECT_COLUMNS = (
    'id', 'country', 'item', 'account_name', 'page_type', 'batch_id',
    'crawl_strdatetime', 'retailer_sku_name', 'count_of_reviews',
    'count_of_star_ratings', 'star_rating', 'main_rank', 'bsr_rank',
    'original_sku_price', 'final_sku_price', 'savings', 'detailed_review_content',
    'summarized_review_content', 'recommendation_intent', 'product_url',
)


def load_active_rules(cursor, source):
    cursor.execute("""
        SELECT id, detail_code, retailer
        FROM monitoring_validation_rules
        WHERE rule_type = 'crossfield' AND is_active = TRUE
          AND section_code = %s AND table_name = %s
        ORDER BY sort_order, id
    """, (source['section_code'], source['table_name']))
    rules = {}
    prefix = source['source_key'] + '_'
    for rule_id, detail_code, retailer_value in cursor.fetchall():
        if not str(detail_code).startswith(prefix):
            continue
        key = detail_code[len(prefix):]
        spec = SEDA_RULE_SPECS.get(key)
        retailer = display_seda_retailer(retailer_value)
        if spec is None or retailer not in spec['retailers']:
            continue
        if key not in rules:
            fields = spec['fields']
            rules[key] = {
                'rule_id': rule_id, 'detail_code': detail_code, 'rule_key': key,
                'source_rule_ids': [], 'retailers': [], 'retailer_rule_ids': {},
                'detail_name': spec['detail_name'], 'guide_name': spec['detail_name'],
                'guide_description': spec['description'], 'error_message': spec['description'],
                'field1': fields[0], 'field2': fields[1] if len(fields) > 1 else None,
                'validation_type': key, 'select_fields': '|'.join(spec['display_fields']),
            }
        rule = rules[key]
        rule['source_rule_ids'].append(rule_id)
        rule['retailer_rule_ids'].setdefault(retailer, []).append(rule_id)
        if retailer not in rule['retailers']:
            rule['retailers'].append(retailer)
    return list(rules.values())


def _select_sql(source, start, end, items=None, retailer=None,
                window_start=None, comparison_ids=(), target_ids=()):
    cte, scope, params = _scope(source, start, end, retailer)
    fields = ', '.join('source.' + column for column in SELECT_COLUMNS)
    sql = f"{cte} SELECT {fields} {scope}"
    if items is not None:
        sql += ' AND (source.item = ANY(%s)'
        params.append(list(items))
        if target_ids:
            sql += ' OR source.id = ANY(%s)'
            params.append(list(target_ids))
        sql += ')'
    if comparison_ids:
        sql += f" AND (LEFT(BTRIM(source.{source['date_column']}), 10) >= %s OR source.id = ANY(%s))"
        params.extend([str(window_start), list(comparison_ids)])
    sql += f" ORDER BY source.item, source.{source['date_column']}, source.id"
    return sql, params


def _load_rows(cursor, source, start, end, items=None, retailer=None):
    sql, params = _select_sql(source, start, end, items, retailer)
    cursor.execute(sql, params)
    return [{**row, 'account_name': display_seda_retailer(row.get('account_name'))}
            for row in _rows(cursor)]


def display_query(cursor, source, source_date, days=3, items=None, retailer=None, comparison_rows=(), target_ids=()):
    end = date.fromisoformat(str(source_date))
    start = end - timedelta(days=min(30, max(1, int(days))) - 1)
    column = source['date_column']
    date_filter = f'{column} >= %s AND {column} < %s'
    params = [str(start), str(end + timedelta(days=1))]
    comparison_ids = [row['id'] for row in comparison_rows]
    if comparison_ids:
        placeholders = ', '.join('%s' for _ in comparison_ids)
        date_filter = f'(({date_filter}) OR id IN ({placeholders}))'
        params.extend(comparison_ids)
    filters = [date_filter]
    if retailer is not None:
        filters.append('account_name = %s')
        params.append('CasasBahia' if retailer == 'Casas Bahia' else retailer)
    if items is not None:
        item_filters = []
        if items:
            item_filters.append('item IN (' + ', '.join('%s' for _ in items) + ')')
            params.extend(items)
        if target_ids:
            item_filters.append('id IN (' + ', '.join('%s' for _ in target_ids) + ')')
            params.extend(target_ids)
        filters.append('(' + ' OR '.join(item_filters) + ')' if item_filters else 'FALSE')
    sql = (f"SELECT *\nFROM {source['table_name']}\nWHERE "
           + '\n  AND '.join(filters) + f'\nORDER BY item, {column}')
    return cursor.mogrify(sql, params).decode('utf-8').strip() + ';'


def _identity(row):
    item = row.get('item')
    return (row['account_name'], str(item)) if not missing(item) else None


def _summary_baselines(cursor, source, source_date, rows, rules):
    rule = next((rule for rule in rules if rule['rule_key'] == 'summary_review_disappeared'), None)
    if rule is None:
        return {}
    end = date.fromisoformat(source_date)
    baselines = {}
    for retailer in rule['retailers']:
        items = sorted({str(row['item']) for row in rows if row['account_name'] == retailer
                        and _identity(row) and not missing(row.get('detailed_review_content'))
                        and missing(row.get('summarized_review_content'))})
        if not items:
            continue
        history = _load_rows(cursor, source, end - timedelta(days=SUMMARY_HISTORY_DAYS),
                             end - timedelta(days=1), items, retailer)
        for row in history:
            identity = _identity(row)
            previous = baselines.get(identity)
            order = lambda item: (str(item[source['date_column']]).strip()[:10], int(item['id']))
            if previous is None or order(row) > order(previous):
                baselines[identity] = row
    return baselines


def _result(cursor, inspection_date, product_line):
    source = get_seda_source(product_line)
    mapping = resolve_monitoring_date(inspection_date, 'SEDA', source['source_key'])
    rules = load_active_rules(cursor, source)
    result = {
        **mapping, 'date': mapping['inspection_date'], 'source': source,
        'product_line': source['source_key'].upper(), 'label': source['display_name'],
        'table_name': source['table_name'], 'date_col': source['date_column'],
        'configured': bool(rules), 'rules': rules,
        'rows': [], 'corrections': [], 'page_exclusions': [],
    }
    if not rules:
        return result
    retailers = {retailer for rule in rules for retailer in rule['retailers']}
    rows = [row for row in _load_rows(cursor, source, mapping['source_date'], mapping['source_date'])
            if row['account_name'] in retailers]
    rows, exclusions = exclude_page_absent_records(
        cursor, inspection_date, rows, table_name=source['table_name'],
        country='SEDA', product_line=source['category'].lower(),
    )
    cursor.execute("""
        SELECT record_id, rule_id, column_name, memo, reason, created_id, created_at
        FROM monitoring_corrections
        WHERE layer = 3 AND correction_type = 'cross_field' AND status = 'normal'
          AND table_name = %s AND crawl_date = %s AND rule_id = ANY(%s)
    """, (source['table_name'], str(inspection_date),
          [rule_id for rule in rules for rule_id in rule['source_rule_ids']]))
    corrections = [dict(zip(('record_id', 'rule_id', 'column_name', 'memo', 'reason', 'created_id', 'created_at'), record))
                   for record in cursor.fetchall()]
    normal = {(str(record['record_id']), str(record['rule_id'])) for record in corrections}
    baselines = _summary_baselines(cursor, source, mapping['source_date'], rows, rules)
    evaluated = {row['id']: evaluate_seda_row(row) for row in rows}
    for rule in rules:
        key = rule['rule_key']
        spec = SEDA_RULE_SPECS[key]
        rule.update(findings=[], comparison_rows=[])
        for row in rows:
            retailer = row['account_name']
            if retailer not in rule['retailers']:
                continue
            # The merged rule ID is what the UI persists, including the second retailer.
            ids = {rule['rule_id'], *rule['retailer_rule_ids'][retailer]}
            if any((str(row['id']), str(rule_id)) in normal for rule_id in ids):
                continue
            issue = evaluated[row['id']].get(key)
            baseline = baselines.get(_identity(row))
            if key == 'summary_review_disappeared':
                if (baseline and not missing(row.get('detailed_review_content'))
                        and missing(row.get('summarized_review_content'))
                        and not missing(baseline.get('detailed_review_content'))
                        and not missing(baseline.get('summarized_review_content'))):
                    issue = ('review_needed', spec['detail_name'])
                    rule['comparison_rows'].append(baseline)
            if issue is None:
                continue
            level, message = issue
            detail = {**row, 'finding_level': level, 'issue_type': message,
                      'validation_tag': message, 'rule_key': key, 'error_message': spec['description']}
            if key.startswith('review_body') or key == 'review_zero_body':
                detail['review_body_count'] = len(body_numbers(row.get('detailed_review_content')))
            if key == 'summary_review_disappeared':
                detail['previous_source_date'] = str(baseline[source['date_column']]).strip()[:10]
                detail['comparison_record_id'] = baseline['id']
            rule['findings'].append(detail)
    result.update(rows=rows, corrections=corrections, page_exclusions=exclusions)
    return result


def _counts(rules):
    errors = {row['id'] for rule in rules for row in rule['findings'] if row['finding_level'] == 'anomaly'}
    reviews = {row['id'] for rule in rules for row in rule['findings'] if row['finding_level'] == 'review_needed'}
    return errors, reviews


def _public_rule(rule):
    return {key: value for key, value in rule.items()
            if key not in ('findings', 'comparison_rows', 'retailer_rule_ids')}


def get_seda_cross_field_summary(cursor, inspection_date, product_line):
    result = _result(cursor, inspection_date, product_line)
    source, rows, rules = result['source'], result['rows'], result['rules']
    errors, reviews = _counts(rules)
    summaries = []
    for rule in rules:
        errors_for_rule = sum(row['finding_level'] == 'anomaly' for row in rule['findings'])
        summaries.append({
            **_public_rule(rule), 'error_count': errors_for_rule,
            'review_count': len(rule['findings']) - errors_for_rule,
            'query': display_query(cursor, source, result['source_date'],
                                   retailer=rule['retailers'][0] if len(rule['retailers']) == 1 else None,
                                   comparison_rows=rule['comparison_rows']),
        })
    retailers = sorted({retailer for rule in rules for retailer in rule['retailers']})
    return {
        **{key: value for key, value in result.items() if key not in ('source', 'rows', 'rules', 'corrections')},
        'total_checked': len(rows), 'failed_records': len(errors),
        'review_needed_records': len(reviews - errors),
        'total_anomalies': sum(rule['error_count'] for rule in summaries),
        'total_review_needed': sum(rule['review_count'] for rule in summaries),
        'passed_records': len(rows) - len(errors | reviews),
        'rule_summary': summaries, 'no_review_texts': '',
        'retailers': [{'retailer': retailer, 'total': sum(row['account_name'] == retailer for row in rows),
                       'error_count': sum(row['id'] in errors for row in rows if row['account_name'] == retailer)}
                      for retailer in retailers],
    }


def get_seda_cross_field_rule_detail(cursor, inspection_date, product_line, rule_id, days=3):
    result = _result(cursor, inspection_date, product_line)
    rule = next((rule for rule in result['rules'] if str(rule['rule_id']) == str(rule_id)), None)
    if rule is None:
        return {'found': False}
    days = min(30, max(1, int(days)))
    source = result['source']
    end = date.fromisoformat(result['source_date'])
    spec = SEDA_RULE_SPECS[rule['rule_key']]
    history, retailer_summary, queries = [], {}, {}
    for retailer in rule['retailers']:
        targets = [row for row in rule['findings'] if row['account_name'] == retailer]
        items = sorted({str(row['item']) for row in targets if not missing(row.get('item'))})
        if days > 1 and items:
            history.extend(_load_rows(cursor, source, end - timedelta(days=days - 1),
                                      end - timedelta(days=1), items, retailer))
        error_count = sum(row['finding_level'] == 'anomaly' for row in targets)
        retailer_summary[retailer] = {'count': error_count, 'review_count': len(targets) - error_count,
                                      'items': items}
        queries[retailer] = display_query(
            cursor, source, end, days, items, retailer,
            [row for row in rule['comparison_rows'] if row['account_name'] == retailer],
            target_ids=[row['id'] for row in targets],
        )
    anomalies = build_detail_history(history, rule['findings'], result['source_date'], source['date_column'], days,
                                     comparison_rows=rule['comparison_rows'])
    if rule['rule_key'].startswith('review_body') or rule['rule_key'] == 'review_zero_body':
        for row in anomalies:
            row['review_body_count'] = len(body_numbers(row.get('detailed_review_content')))
    normal_reviews = {}
    for record in result['corrections']:
        if record['rule_id'] not in rule['source_rule_ids']:
            continue
        payload = {key: str(record[key] or '') for key in ('memo', 'reason', 'created_id', 'created_at')}
        for column in spec['editable']:
            normal_reviews[f"{record['record_id']}_{column}"] = payload
    return {
        **{key: result[key] for key in ('date', 'inspection_date', 'source_date',
                                       'offset_days', 'product_line', 'table_name', 'date_col')},
        **_public_rule(rule), 'found': True, 'days': days, 'anomalies': anomalies,
        'total_anomalies': sum(entry['count'] for entry in retailer_summary.values()),
        'total_review_needed': sum(entry['review_count'] for entry in retailer_summary.values()),
        'total_findings': len(rule['findings']), 'retailer_summary': retailer_summary,
        'editable_columns': list(spec['editable']),
        'retailer_columns': {retailer: list(SELECT_COLUMNS) for retailer in rule['retailers']},
        'retailer_editable_columns': {retailer: list(spec['editable']) for retailer in rule['retailers']},
        'normal_reviews': normal_reviews, 'queries': queries,
    }
