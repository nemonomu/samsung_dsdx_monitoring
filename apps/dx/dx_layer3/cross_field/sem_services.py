"""SEM cross-field validation for each retailer's latest daily batch."""

from datetime import date, timedelta
from decimal import Decimal

from apps.common.crossfield_history import build_detail_history
from apps.common.null_review_evidence import exclude_page_absent_records
from apps.common.source_dates import source_date_sql
from apps.common.sem_retail import (
    SEM_COUNTRY,
    SEM_COPPEL_RETAILER,
    SEM_HOMEDEPOT_RETAILER,
    SEM_RETAILER,
    SEM_SOURCE_CONFIG,
    get_sem_editable_columns,
    get_sem_table_columns,
    active_sem_retailers,
    sem_start_date,
    sem_tv_observation_retailer,
)
from apps.dx.dx_layer2.sem_validation import (
    _COPPEL_SAVINGS, _format_checks, _history_rows, _latest_rows, product_line_for, _mapping,
    homedepot_savings_rate, _validation_retailers,
)

from . import sem_tv_rules


_RULES = (
    ('rating_count_consistency', '평점과 평가 수 일치', 'star_rating',
     'count_of_star_ratings',
     '평점과 평가 수 또는 리뷰 수의 0 여부가 다르거나 평점과 리뷰 수의 존재 여부가 다릅니다.'),
    ('review_rating_count', '리뷰 수와 평가 수 일치', 'count_of_reviews',
     'count_of_star_ratings',
     '리뷰 수와 평가 수가 일치하지 않습니다.'),
    ('final_original_price', '최종가와 원가 순서', 'final_sku_price',
     'original_sku_price', '두 가격이 숫자이고 원가가 0이 아닐 때 최종 판매가가 원가보다 크거나 같으면 이상입니다.'),
    ('original_price_zero', '원가 0 검사', 'original_sku_price',
     None, 'original_sku_price가 0입니다.'),
)
_HOMEDEPOT_RULES = (
    ('savings_missing', 'HomeDepot savings 누락', 'final_sku_price',
     'original_sku_price', '최종가와 원가가 있는데 savings가 없습니다.'),
    ('original_missing', 'HomeDepot 원가 누락', 'original_sku_price',
     'savings', '최종가와 savings가 있는데 원가가 없습니다.'),
    ('final_missing', 'HomeDepot 최종가 누락', 'final_sku_price',
     'savings', '최종가가 없는데 원가 또는 savings가 있습니다.'),
    ('savings_rate_match', 'HomeDepot 할인율 일치', 'savings',
     'original_sku_price',
     '최종가·원가·savings 형식이 유효하고 원가 > 0, 최종가 < 원가일 때 계산 할인율이 savings의 할인율 크기 이상, 그 값+1 미만 범위를 벗어나면 이상입니다.'),
)
_REVIEW_COLUMNS = (
    'star_rating', 'count_of_star_ratings', 'count_of_reviews',
)
_COPPEL_RULES = (
    ('coppel_savings_missing', 'Coppel savings 누락', 'final_sku_price',
     'original_sku_price', '최종가와 원가가 있는데 savings가 없습니다.'),
    ('coppel_original_missing', 'Coppel 원가 누락', 'original_sku_price',
     'savings', '최종가와 savings가 있는데 원가가 없습니다.'),
    ('coppel_final_missing', 'Coppel 최종가 누락', 'final_sku_price',
     'savings', '최종가가 없는데 원가 또는 savings가 있습니다.'),
    ('coppel_savings_amount_match', 'Coppel 할인금액 일치', 'savings',
     'original_sku_price', '가격과 savings 형식이 유효하고 원가 > 0, 최종가 < 원가일 때 원가−최종가와 savings 할인금액이 다르면 이상입니다.'),
    ('coppel_savings_rate_match', 'Coppel 할인율 일치', 'savings',
     'original_sku_price', '가격과 savings 형식이 유효하고 원가 > 0, 최종가 < 원가일 때 계산 할인율이 표시 할인율 이상, 표시 할인율+1 미만 범위를 벗어나면 이상입니다.'),
)


def _blank(value):
    return value is None or str(value).strip() == ''


def _number(value):
    try:
        return float(str(value).replace('$', '').replace(',', '').strip())
    except (TypeError, ValueError):
        return None


def _rule_select_fields(field1, field2, rule_key=None):
    if rule_key in sem_tv_rules.PRICE_RULE_KEYS or rule_key in {rule[0] for rule in (*_HOMEDEPOT_RULES, *_COPPEL_RULES)}:
        return 'final_sku_price|original_sku_price|savings'
    fields = (field1, field2)
    if any(field in _REVIEW_COLUMNS for field in fields):
        return '|'.join(_REVIEW_COLUMNS)
    return '|'.join(field for field in fields if field)


def _failed_rules(row, retailer=SEM_RETAILER, product_line='sem_ref'):
    if sem_tv_observation_retailer(product_line, retailer):
        retailer = sem_tv_observation_retailer(product_line, retailer)
        return [rule for rule, verdict in sem_tv_rules.evaluate(
            row, retailer, _format_checks(product_line, retailer)).items() if verdict == 'anomaly']
    if retailer == SEM_COPPEL_RETAILER:
        return _coppel_price_rules(row, _format_checks(product_line, retailer))
    original_row = row
    if retailer == SEM_HOMEDEPOT_RETAILER:
        # Invalid present values belong to format validation. Do not compare
        # their failed parses to zero or calculate dependent price errors.
        checks = _format_checks(product_line, retailer)
        row = dict(row)
        for field in (*_REVIEW_COLUMNS, 'final_sku_price', 'original_sku_price'):
            if not _blank(row.get(field)) and not checks[field](row[field]):
                row[field] = None
    rating = row.get('star_rating')
    rating_count = row.get('count_of_star_ratings')
    review_count = row.get('count_of_reviews')
    rating_present = not _blank(rating)
    rating_count_present = not _blank(rating_count)
    review_count_present = not _blank(review_count)
    failed = []
    if rating_present and rating_count_present:
        rating_value = _number(rating)
        rating_count_value = _number(rating_count)
        if ((rating_value == 0) != (rating_count_value == 0)):
            failed.append('rating_count_consistency')
    if _blank(original_row.get('star_rating')) != _blank(original_row.get('count_of_reviews')):
        if 'rating_count_consistency' not in failed:
            failed.append('rating_count_consistency')
    rating_value = _number(rating)
    review_count_value = _number(review_count)
    if rating_value is not None and review_count_value is not None:
        if (rating_value == 0) != (review_count_value == 0):
            if 'rating_count_consistency' not in failed:
                failed.append('rating_count_consistency')
    if rating_count_present and review_count_present:
        rating_count_value = _number(rating_count)
        review_count_value = _number(review_count)
        if rating_count_value != review_count_value:
            failed.append('review_rating_count')
    final_price = _number(row.get('final_sku_price'))
    original_price = _number(row.get('original_sku_price'))
    if original_price == 0:
        failed.append('original_price_zero')
    elif final_price is not None and original_price is not None and final_price >= original_price:
        failed.append('final_original_price')
    if retailer == SEM_HOMEDEPOT_RETAILER:
        failed.extend(_homedepot_price_rules(original_row, checks))
    return failed


def _homedepot_price_rules(row, checks):
    fields = ('final_sku_price', 'original_sku_price', 'savings')
    final, original, savings = [not _blank(row.get(field)) for field in fields]
    if not final and (original or savings):
        return ['final_missing']
    if final and original and not savings:
        return ['savings_missing']
    if final and savings and not original:
        return ['original_missing']
    if not all((final, original, savings)):
        return []
    discount = homedepot_savings_rate(row['savings'], row.get('crawl_datetime'))
    if discount is None or any(not checks[field](row[field]) for field in fields[:2]):
        return []
    # Integer cents make the boundary comparison exact without a float or
    # a rounded division, even immediately below the next integer percent.
    cents = lambda value: int(Decimal(str(value).strip().replace('$', '').replace(',', '')) * 100)
    final_cents = cents(row['final_sku_price'])
    original_cents = cents(row['original_sku_price'])
    if original_cents <= 0 or final_cents >= original_cents:
        return []
    difference = (original_cents - final_cents) * 100
    if not discount * original_cents <= difference < (discount + 1) * original_cents:
        return ['savings_rate_match']
    return []


def _coppel_price_rules(row, checks):
    fields = ('final_sku_price', 'original_sku_price', 'savings')
    final, original, savings = [not _blank(row.get(field)) for field in fields]
    money = lambda value: Decimal(str(value).strip().replace('$', '').replace(',', ''))
    final_price = money(row[fields[0]]) if final and checks[fields[0]](row[fields[0]]) else None
    original_price = money(row[fields[1]]) if original and checks[fields[1]](row[fields[1]]) else None
    failed = []
    if original_price == 0:
        failed.append('original_price_zero')
    elif original_price is not None and final_price is not None and final_price >= original_price:
        failed.append('final_original_price')
    if not final and (original or savings):
        failed.append('coppel_final_missing')
    elif final and original and not savings:
        failed.append('coppel_savings_missing')
    elif final and savings and not original:
        failed.append('coppel_original_missing')
    if not all((final, original, savings)) or any(not checks[field](row[field]) for field in fields):
        return failed
    if original_price <= 0 or final_price >= original_price:
        return failed
    match = _COPPEL_SAVINGS.fullmatch(str(row['savings']).strip())
    amount, rate = money(match[1]), int(match[2])
    difference = original_price - final_price
    if difference != amount:
        failed.append('coppel_savings_amount_match')
    # Compare exact decimal amounts without rounding the calculated percent.
    if not rate * original_price <= difference * 100 < (rate + 1) * original_price:
        failed.append('coppel_savings_rate_match')
    return failed


def _registered_tv_rules(cursor, source):
    from apps.common.db import dx_table

    cursor.execute(f"""
        SELECT validation_type, id
        FROM public.{dx_table('monitoring_validation_rules')}
        WHERE rule_type = 'crossfield' AND is_active IS TRUE
          AND section_code = %s AND table_name = %s
          AND detail_code = 'sem_tv_' || validation_type
    """, (source['section_code'], source['table_name']))
    return {key: rule_id for key, rule_id in cursor.fetchall() if key in sem_tv_rules.RULE_KEYS}


def _tv_corrections(cursor, inspection_date, source, registered_rules):
    if not registered_rules:
        return {}
    cursor.execute("""
        SELECT record_id, rule_id, column_name, memo, reason, created_id, created_at
        FROM public.monitoring_corrections
        WHERE layer = 3 AND correction_type = 'cross_field' AND status = 'normal'
          AND table_name = %s AND crawl_date = %s AND rule_id = ANY(%s)
    """, (source['table_name'], str(inspection_date), list(registered_rules.values())))
    return {
        (str(record_id), rule_id): {
            'column_name': column_name, 'memo': memo or '', 'reason': reason or '',
            'created_id': created_id or '', 'created_at': str(created_at or ''),
        }
        for record_id, rule_id, column_name, memo, reason, created_id, created_at in cursor.fetchall()
    }


def can_review_tv_rule(cursor, source, retailer, rule_id, column_name):
    registered = _registered_tv_rules(cursor, source)
    return any(
        str(registered.get(key)) == str(rule_id)
        and key in registered
        and (retailer == 'Walmart' or key not in sem_tv_rules.WALMART_ONLY)
        and column_name in _rule_select_fields(field1, field2, key).split('|')
        for key, _, field1, field2, _ in sem_tv_rules.RULES
    )


def _result(cursor, target_date, product_line):
    key = product_line_for(product_line)
    source = SEM_SOURCE_CONFIG.get(key)
    if not source:
        raise ValueError(f'Unsupported SEM product line: {product_line}')
    mapping = _mapping(target_date, source)
    active_retailers = active_sem_retailers(key, mapping['source_date'])
    new_tv_retailers = tuple(
        retailer for retailer in _validation_retailers(key, mapping['source_date'])
        if sem_tv_observation_retailer(key, retailer)
    )
    registered_rules = _registered_tv_rules(cursor, source) if new_tv_retailers else {}
    corrections = _tv_corrections(cursor, target_date, source, registered_rules)
    definitions = _RULES + (
        _HOMEDEPOT_RULES if SEM_HOMEDEPOT_RETAILER in active_retailers else ()
    ) + (
        _COPPEL_RULES if SEM_COPPEL_RETAILER in active_retailers else ()
    ) + (sem_tv_rules.RULES if new_tv_retailers else ())
    rows = []
    page_exclusions = []
    failures = {rule[0]: [] for rule in definitions}
    failed_ids = set()
    review_ids = set()
    new_tv_stats = {}
    rule_stats = {rule: {} for rule in sem_tv_rules.RULE_KEYS}
    for retailer in (*active_retailers, *new_tv_retailers):
        if retailer == SEM_RETAILER:
            retailer_rows, mapping = _latest_rows(cursor, target_date, source)
        else:
            retailer_rows, mapping = _latest_rows(cursor, target_date, source, retailer=retailer)
        retailer_rows, excluded = exclude_page_absent_records(
            cursor, target_date, retailer_rows, table_name=source['table_name'],
            country='SEM', product_line=source['category'],
        )
        page_exclusions.extend(excluded)
        if retailer in new_tv_retailers:
            checks = _format_checks(key, retailer)
            checked = 0
            seller_failed, seller_reviews = set(), set()
            for rule_key, counts in rule_stats.items():
                if retailer == 'Walmart' or rule_key not in sem_tv_rules.WALMART_ONLY:
                    counts[retailer] = {'received': len(retailer_rows), 'checked': 0,
                                        'failed': 0, 'review_count': 0}
            for row in retailer_rows:
                verdicts = sem_tv_rules.evaluate(row, retailer, checks)
                if not verdicts:
                    continue
                checked += 1
                rows.append(row)
                for rule_key, verdict in verdicts.items():
                    stats = rule_stats[rule_key][retailer]
                    stats['checked'] += 1
                    if verdict == 'ok' or (str(row['id']), registered_rules.get(rule_key)) in corrections:
                        continue
                    failures[rule_key].append({**row, 'account_name': retailer, 'finding_level': verdict})
                    if verdict == 'review_needed':
                        stats['review_count'] += 1
                        seller_reviews.add(row['id'])
                    else:
                        stats['failed'] += 1
                        seller_failed.add(row['id'])
            new_tv_stats[retailer] = {'received': len(retailer_rows), 'checked': checked,
                                      'failed': len(seller_failed), 'review_count': len(seller_reviews - seller_failed)}
            review_ids.update(seller_reviews)
            failed_ids.update(seller_failed)
            continue
        rows.extend(retailer_rows)
        for row in retailer_rows:
            for rule_key in _failed_rules(row, retailer, key):
                failures[rule_key].append(row)
                failed_ids.add(row.get('id'))
    summaries = []
    for index, rule in enumerate(definitions, 1):
        rule_key, name, field1, field2, message = rule
        applicable_retailers = (
            list(rule_stats[rule_key]) if rule_key in sem_tv_rules.RULE_KEYS
            else [SEM_COPPEL_RETAILER] if rule in _COPPEL_RULES
            else [SEM_HOMEDEPOT_RETAILER] if rule in _HOMEDEPOT_RULES
            else [retailer for retailer in active_retailers
                  if retailer != SEM_COPPEL_RETAILER
                  or not any(field in _REVIEW_COLUMNS for field in (field1, field2))]
        )
        summaries.append({
            'rule_id': registered_rules.get(rule_key, f'{key}:{rule_key}'),
            'detail_code': f'{key}_{rule_key}',
            'rule_key': rule_key,
            'detail_name': name,
            'retailers': applicable_retailers,
            'field1': field1,
            'field2': field2,
            'validation_type': rule_key,
            'error_message': message,
            'error_count': sum(row.get('finding_level') != 'review_needed' for row in failures[rule_key]),
            'review_count': sum(row.get('finding_level') == 'review_needed' for row in failures[rule_key]),
            'select_fields': _rule_select_fields(field1, field2, rule_key),
            'sort_order': index * 10,
            **({'retailer_checks': rule_stats[rule_key]} if rule_key in sem_tv_rules.RULE_KEYS else {}),
        })
    mapping = {**mapping, 'page_exclusions': page_exclusions}
    return source, rows, failures, failed_ids, summaries, mapping, new_tv_stats, review_ids - failed_ids, corrections


def build_sem_display_query(source, source_date, retailers, days=3, rows=None, fields=''):
    """Copy-only lookup for the displayed source scope and item identities."""
    end = date.fromisoformat(str(source_date))
    start = end - timedelta(days=min(30, max(1, int(days))) - 1)
    literal = lambda value: "'" + str(value).replace("'", "''") + "'"
    scopes = []
    column = source['date_column']
    source_day = source_date_sql(column)
    for retailer in retailers:
        scope = 'account_name = ' + literal(retailer)
        new_tv = sem_tv_observation_retailer(source['source_key'], retailer)
        if new_tv:
            launch = sem_start_date(source['source_key'], retailer)
            scope = (
                f'LOWER(BTRIM(account_name)) = LOWER({literal(retailer)})'
                f' AND {source_day} BETWEEN {literal(max(start, launch))} AND {literal(end)}'
                f' AND batch_id = (SELECT latest.batch_id FROM {source["table_name"]} latest'
                f' WHERE {source_date_sql("latest." + column)} = {source_date_sql("source." + column)}'
                ' AND LOWER(BTRIM(latest.account_name)) = LOWER(BTRIM(source.account_name))'
                " AND NULLIF(BTRIM(latest.batch_id), '') IS NOT NULL ORDER BY latest.id DESC LIMIT 1)"
            )
        if rows is not None:
            targets = [row for row in rows if str(row.get('account_name') or '').strip().casefold() == retailer.casefold()]
            items = sorted({str(row['item']) for row in targets if not _blank(row.get('item'))})
            ids = [row['id'] for row in targets if _blank(row.get('item'))]
            conditions = []
            if items:
                conditions.append('item IN (' + ', '.join(map(literal, items)) + ')')
            if ids:
                conditions.append('id IN (' + ', '.join(str(int(value)) for value in ids) + ')')
            scope += ' AND (' + ' OR '.join(conditions or ['FALSE']) + ')'
        scopes.append(scope)
    new_tv_rule = bool(retailers) and all(sem_tv_observation_retailer(source['source_key'], r) for r in retailers)
    date_expression = source_day if source['source_key'] == 'sem_ldy_dryer' else column
    requested = ('id', 'item', column, 'retailer_sku_name', *fields.split('|'), 'product_url')
    allowed = set(get_sem_table_columns(source['source_key']))
    columns = ', '.join(field for field in dict.fromkeys(requested) if field in allowed)
    where = scopes[0] if len(scopes) == 1 else '(' + ' OR '.join(f'({scope})' for scope in scopes) + ')'
    date_scope = (f"  AND {date_expression} >= '{start}'\n"
                  f"  AND {date_expression} < '{end + timedelta(days=1)}'\n")
    has_new_tv = any(sem_tv_observation_retailer(source['source_key'], r) for r in retailers)
    table = source['table_name'] + (' source' if has_new_tv else '')
    return (f"SELECT {columns}\nFROM {table}\nWHERE {where if scopes else 'FALSE'}\n"
            + ('' if new_tv_rule else date_scope) + f'ORDER BY item, {column};')


def get_sem_cross_field_summary(cursor, target_date, product_line):
    source, rows, failures, failed_ids, rules, mapping, new_tv_stats, review_ids, _ = _result(
        cursor, target_date, product_line
    )
    for rule in rules:
        rule['query'] = build_sem_display_query(
            source, mapping['source_date'], rule['retailers'], fields=rule['select_fields'],
            rows=failures[rule['rule_key']] or None,
        )
    return {
        'configured': True,
        'date': mapping['inspection_date'],
        'label': source['display_name'],
        'product_line': source['source_key'],
        'table_name': source['table_name'],
        'date_col': source['date_column'],
        'total_checked': len(rows),
        'failed_records': len(failed_ids),
        'passed_records': max(0, len(rows) - len(failed_ids) - len(review_ids)),
        'review_needed_records': len(review_ids),
        'total_anomalies': sum(rule['error_count'] for rule in rules),
        'total_review_needed': sum(rule['review_count'] for rule in rules),
        'retailer_checks': new_tv_stats,
        'rule_summary': rules,
        'no_review_texts': '',
        **mapping,
    }


def get_sem_cross_field_rule_detail(cursor, target_date, product_line, rule_id, days=1):
    source, _, failures, _, rules, mapping, _, _, corrections = _result(
        cursor, target_date, product_line
    )
    rule = next((item for item in rules if str(rule_id) in (
        str(item['rule_id']), f"{source['source_key']}:{item['rule_key']}",
    )), None)
    if rule is None:
        return {'found': False}
    target_anomalies = failures[rule['rule_key']]
    days = min(30, max(1, int(days or 1)))
    source_date = date.fromisoformat(mapping['source_date'])
    history = []
    retailer_summary = {}
    new_tv_rule = rule['rule_key'] in sem_tv_rules.RULE_KEYS
    readonly = new_tv_rule and not isinstance(rule['rule_id'], int)
    review_columns = rule['select_fields'].split('|') if new_tv_rule else None
    detail_retailers = rule['retailers'] if new_tv_rule else [
        retailer for retailer in active_sem_retailers(source['source_key'], source_date)
        if (not rule['rule_key'].startswith('coppel_') or retailer == SEM_COPPEL_RETAILER)
        and (retailer != SEM_COPPEL_RETAILER or retailer in rule['retailers'])
    ]
    for retailer in detail_retailers:
        targets = [row for row in target_anomalies
                   if str(row.get('account_name') or '').strip().casefold() == retailer.casefold()]
        items = sorted({str(row['item']) for row in targets if not _blank(row.get('item'))})
        stats = rule.get('retailer_checks', {}).get(retailer, {})
        retailer_summary[retailer] = {'count': stats.get('failed', len(targets)), 'items': items, **stats}
        if days > 1 and items:
            options = {} if retailer == SEM_RETAILER else {'retailer': retailer}
            prior = _history_rows(
                cursor, source, source_date - timedelta(days=days - 1),
                source_date - timedelta(days=1), items, **options,
            )
            if new_tv_rule:
                history.extend({**row, 'account_name': retailer} for row in prior)
            else:
                history.extend(row for row in prior if str(row.get('country') or '').strip().upper() == SEM_COUNTRY)
    anomalies = build_detail_history(
        history, target_anomalies, source_date, source['date_column'], days,
    )
    editable_by_retailer = {} if readonly else {
        retailer: [column for column in get_sem_editable_columns(source['source_key'], retailer)
                   if review_columns is None or column in review_columns]
        for retailer in detail_retailers
    }
    editable_columns = list(dict.fromkeys(
        column for columns in editable_by_retailer.values() for column in columns
    ))
    table_columns = list(get_sem_table_columns(source['source_key']))
    return {
        'found': True,
        'date': mapping['inspection_date'],
        'days': days,
        'product_line': source['source_key'].upper(),
        'rule_id': rule['rule_id'],
        'detail_code': rule['detail_code'],
        'field1': rule['field1'],
        'field2': rule['field2'],
        'validation_type': rule['validation_type'],
        'error_message': rule['error_message'],
        'total_anomalies': rule['error_count'],
        'total_review_needed': rule['review_count'],
        'retailer_summary': retailer_summary,
        'queries': {
            retailer: build_sem_display_query(source, source_date, [retailer], days, target_anomalies,
                                              fields=rule['select_fields'])
            for retailer in retailer_summary
        },
        'anomalies': anomalies,
        'select_fields': rule['select_fields'],
        'table_name': source['table_name'],
        'date_col': source['date_column'],
        'readonly': readonly,
        'review_columns': [] if readonly else review_columns,
        'editable_columns': editable_columns,
        'retailer_editable_columns': editable_by_retailer,
        'normal_reviews': {
            f"{record_id}_{review['column_name']}": review
            for (record_id, reviewed_rule), review in corrections.items()
            if reviewed_rule == rule['rule_id']
        },
        'retailer_columns': {retailer: table_columns for retailer in detail_retailers},
        **mapping,
    }
