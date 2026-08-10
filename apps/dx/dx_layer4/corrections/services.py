"""
Layer 4 검수기록 Services — 목록 조회, 취소, 이력 조회
"""

from datetime import datetime, timedelta
from apps.common.db import dx_connection
from apps.common.retail_columns import (
    get_retailer_columns,
    get_tse_retailer_columns,
    load_retail_columns,
)
from apps.common.tse_retail import (
    TSE_SOURCE_CONFIG,
    TSE_TABLE_TO_PRODUCT_LINE,
    get_tse_editable_columns,
)


# 원본 테이블별 수집 시간 컬럼 매핑
_CRAWL_TIME_COLUMN = {
    'tv_retail_com': 'crawl_datetime',
    'youtube_videos': 'created_at',
    'youtube_collection_logs': 'started_at',
    'youtube_comments': 'created_at',
    'market_trend': 'crawl_at_local_time',
    'market_comp_product': 'created_at',
    'market_comp_event': 'created_at',
    'openai_forecast_results': 'crawled_at',
    **{
        config['table_name']: 'crawl_datetime'
        for config in TSE_SOURCE_CONFIG.values()
    },
}

_ALLOWED_TABLES = set(_CRAWL_TIME_COLUMN.keys())

# 이력 조회: 허용 테이블 → (product_line, date_column)
_HISTORY_TABLES = {
    'tv_retail_com': ('tv', 'crawl_datetime'),
    **{
        config['table_name']: (product_line, 'crawl_datetime')
        for product_line, config in TSE_SOURCE_CONFIG.items()
    },
}

_BULK_HISTORY_TABLES = {
    # Preserve the pre-TSE API default: ``all`` means the existing TV source.
    'all': ('tv_retail_com',),
    'tv': ('tv_retail_com',),
    **{
        product_line: (config['table_name'],)
        for product_line, config in TSE_SOURCE_CONFIG.items()
    },
}


def _enrich_crawl_time(cursor, items):
    """items에 crawl_time 필드를 추가 (원본 테이블에서 수집 시간 조회)"""
    ids_by_table = {}
    for item in items:
        tn = item.get('table_name')
        rid = item.get('record_id')
        if tn and rid and tn in _ALLOWED_TABLES:
            ids_by_table.setdefault(tn, set()).add(rid)

    crawl_time_map = {}
    for tn, record_ids in ids_by_table.items():
        col = _CRAWL_TIME_COLUMN[tn]
        placeholders = ','.join(['%s'] * len(record_ids))
        cursor.execute(
            f"SELECT id, {col} FROM {tn} WHERE id IN ({placeholders})",
            list(record_ids)
        )
        for row in cursor.fetchall():
            if row[1]:
                crawl_time_map[(tn, row[0])] = row[1].strftime('%Y-%m-%d %H:%M') if hasattr(row[1], 'strftime') else str(row[1])

    for item in items:
        key = (item.get('table_name'), item.get('record_id'))
        item['crawl_time'] = crawl_time_map.get(key, '')


def get_corrections(target_date, correction_type='all', status='all',
                    search_field='', search_value='', page=1, page_size=50):
    """검수기록 목록 조회"""
    with dx_connection() as (conn, cursor):
        base_clauses = ["c.crawl_date = %s", "c.status IS NOT NULL", "c.table_name <> 'hhp_retail_com'"]
        base_params = [str(target_date)]

        if correction_type != 'all':
            base_clauses.append("c.correction_type = %s")
            base_params.append(correction_type)

        _SEARCH_FIELDS = {
            'category': 'c.table_name',
            'retailer': 'c.retailer',
            'column_name': 'c.column_name',
            'item': 'c.item',
            'record_id': None,
            'correction_type': 'c.correction_type',
        }
        if search_value and search_field in _SEARCH_FIELDS:
            if search_field == 'record_id':
                base_clauses.append("CAST(c.record_id AS TEXT) LIKE %s")
                base_params.append(f'%{search_value}%')
            else:
                col = _SEARCH_FIELDS[search_field]
                base_clauses.append(f"{col} ILIKE %s")
                base_params.append(f'%{search_value}%')

        base_where_sql = " AND ".join(base_clauses)
        cursor.execute(f"""
            SELECT c.status, COUNT(*) FROM monitoring_corrections c
            WHERE {base_where_sql}
            GROUP BY c.status
        """, base_params)
        status_counts = {}
        for row in cursor.fetchall():
            status_counts[row[0]] = row[1]

        where_clauses = list(base_clauses)
        params = list(base_params)
        if status != 'all':
            where_clauses.append("c.status = %s")
            params.append(status)

        where_sql = " AND ".join(where_clauses)

        cursor.execute(f"SELECT COUNT(*) FROM monitoring_corrections c WHERE {where_sql}", params)
        total_count = cursor.fetchone()[0]

        offset = (page - 1) * page_size
        cursor.execute(f"""
            SELECT c.id, c.layer, c.correction_type, c.table_name, c.record_id,
                   c.column_name, c.old_value, c.new_value, c.crawl_date,
                   c.status, c.memo, c.created_id, c.created_at, c.reason,
                   c.retailer, c.item, c.rule_id, r.detail_name,
                   c.updated_id, c.updated_at, c.cancel_memo
            FROM monitoring_corrections c
            LEFT JOIN monitoring_validation_rules r ON c.rule_id = r.id
            WHERE {where_sql}
            ORDER BY c.created_at DESC
            LIMIT %s OFFSET %s
        """, params + [page_size, offset])

        items = []
        for row in cursor.fetchall():
            items.append({
                'id': row[0],
                'layer': row[1],
                'correction_type': row[2],
                'table_name': row[3],
                'record_id': row[4],
                'column_name': row[5],
                'old_value': row[6],
                'new_value': row[7],
                'crawl_date': str(row[8]) if row[8] else '',
                'status': row[9],
                'memo': row[10] or '',
                'created_id': row[11] or '',
                'created_at': row[12].strftime('%Y-%m-%d %H:%M:%S') if row[12] else '',
                'reason': row[13] or '',
                'retailer': row[14] or '',
                'item': row[15] or '',
                'rule_id': row[16],
                'rule_name': row[17] or '',
                'updated_id': row[18] or '',
                'updated_at': row[19].strftime('%Y-%m-%d %H:%M:%S') if row[19] else '',
                'cancel_memo': row[20] or '',
            })

        _enrich_crawl_time(cursor, items)

        rule_options = []
        if correction_type == 'cross_field':
            cursor.execute("""
                SELECT DISTINCT r.detail_name
                FROM monitoring_corrections c
                LEFT JOIN monitoring_validation_rules r ON c.rule_id = r.id
                WHERE c.crawl_date = %s AND c.correction_type = 'cross_field'
                  AND c.status IS NOT NULL AND c.rule_id IS NOT NULL
                ORDER BY r.detail_name
            """, [str(target_date)])
            for rrow in cursor.fetchall():
                if rrow[0]:
                    rule_options.append({'name': rrow[0]})

    total_pages = (total_count + page_size - 1) // page_size
    resp = {
        'success': True,
        'items': items,
        'total': total_count,
        'page': page,
        'page_size': page_size,
        'total_pages': total_pages,
        'status_counts': {
            'corrected': status_counts.get('corrected', 0),
            'normal': status_counts.get('normal', 0),
            'reverted': status_counts.get('reverted', 0),
        },
    }
    if rule_options:
        resp['rule_options'] = rule_options
    return resp


def cancel_corrections(ids, cancel_memo, username):
    """정상처리 일괄 취소"""
    now = datetime.now()
    with dx_connection() as (conn, cursor):
        placeholders = ','.join(['%s'] * len(ids))
        cursor.execute(f"""
            UPDATE monitoring_corrections
            SET status = 'reverted', updated_id = %s, updated_at = %s, cancel_memo = %s
            WHERE id IN ({placeholders}) AND status = 'normal'
        """, [username, now, cancel_memo or None] + ids)
        cancelled = cursor.rowcount
        conn.commit()

    return {'success': True, 'cancelled': cancelled}


def get_bulk_history(target_date, correction_type='all', category='all', days=3):
    """일괄 이력 조회 (Retail 테이블 한정)"""
    if category == 'hhp':
        return {
            'success': True, 'rows': [], 'columns': [],
            'default_visible': [], 'fixed': [], 'corrected_map': {}
        }
    allowed_tables = _BULK_HISTORY_TABLES.get(category)
    if not allowed_tables:
        raise ValueError('지원하지 않는 카테고리입니다.')

    table_placeholders = ','.join(['%s'] * len(allowed_tables))

    with dx_connection() as (conn, cursor):
        extra_clause = "AND correction_type = %s" if correction_type != 'all' else ""
        extra_params = [correction_type] if correction_type != 'all' else []

        cursor.execute(f"""
            SELECT record_id, table_name, retailer, item, column_name
            FROM monitoring_corrections
            WHERE crawl_date = %s
              AND table_name IN ({table_placeholders})
              AND status IN ('corrected', 'normal')
              {extra_clause}
        """, [str(target_date)] + list(allowed_tables) + extra_params)

        rows_raw = cursor.fetchall()
        if not rows_raw:
            return {
                'success': True, 'rows': [], 'columns': [],
                'default_visible': [], 'fixed': [], 'corrected_map': {}
            }

        corrected_map = {}
        items_by_table = {}
        corrected_columns = set()

        for rec_id, table_name, retailer, item, col_name in rows_raw:
            if rec_id:
                key = str(rec_id)
                if key not in corrected_map:
                    corrected_map[key] = []
                if col_name and col_name not in corrected_map[key]:
                    corrected_map[key].append(col_name)
            if col_name:
                corrected_columns.add(col_name)
            if table_name not in items_by_table:
                items_by_table[table_name] = {}
            if retailer and item:
                items_by_table[table_name].setdefault(retailer, set()).add(item)

        all_col_data = load_retail_columns()
        since_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        FIXED = ['id', 'crawl_datetime', 'account_name', 'item']
        all_other = set()
        has_product_url = False
        all_rows = []

        for table_name, retailers_items in items_by_table.items():
            is_tse = table_name in TSE_TABLE_TO_PRODUCT_LINE
            if is_tse:
                product_line = TSE_TABLE_TO_PRODUCT_LINE[table_name]
                orig_date_col = 'crawl_datetime'
                server_allowed = set(get_tse_editable_columns(product_line))
                pl_cols = set()
                for config in get_tse_retailer_columns(product_line).values():
                    pl_cols.update(config.get('required_columns', []))
                    pl_cols.update(config.get('editable_columns', []))
                pl_cols.intersection_update(server_allowed)
            else:
                product_line = 'tv' if table_name == 'tv_retail_com' else 'hhp'
                orig_date_col = 'crawl_datetime' if table_name == 'tv_retail_com' else 'crawl_strdatetime'
                pl_cols = set()
                for r_cols in all_col_data.get(product_line, {}).values():
                    pl_cols.update(r_cols)

            other_cols = sorted(
                c for c in pl_cols
                if c not in {'id', orig_date_col, 'item', 'account_name', 'product_url'}
            )
            table_has_url = 'product_url' in pl_cols
            if table_has_url:
                has_product_url = True
            all_other.update(other_cols)

            date_expr = (
                'crawl_datetime'
                if table_name == 'tv_retail_com' or is_tse
                else 'crawl_strdatetime AS crawl_datetime'
            )
            select_parts = ['id', date_expr, 'account_name', 'item'] + other_cols
            col_names_local = ['id', 'crawl_datetime', 'account_name', 'item'] + other_cols
            if table_has_url:
                select_parts.append('product_url')
                col_names_local.append('product_url')

            items_list = [(r, i) for r, items_set in retailers_items.items() for i in items_set]
            if not items_list:
                continue

            cond_sql = ' OR '.join(['(account_name = %s AND item = %s)'] * len(items_list))
            params = [p for r, i in items_list for p in (r, i)]

            date_condition = (
                f"LEFT(TRIM({orig_date_col}), 10) >= %s"
                if is_tse
                else f"({orig_date_col})::date >= %s::date"
            )
            cursor.execute(
                f"SELECT {', '.join(select_parts)} FROM {table_name} "
                f"WHERE ({cond_sql}) AND {date_condition} "
                f"ORDER BY account_name, item, {orig_date_col} ASC",
                params + [since_date]
            )

            for row in cursor.fetchall():
                d = {}
                for idx, val in enumerate(row):
                    if hasattr(val, 'strftime'):
                        d[col_names_local[idx]] = val.strftime('%Y-%m-%d %H:%M:%S')
                    elif val is None:
                        d[col_names_local[idx]] = ''
                    else:
                        d[col_names_local[idx]] = str(val)
                all_rows.append(d)

    other_sorted = sorted(all_other - set(FIXED))
    final_columns = FIXED + other_sorted
    if has_product_url:
        final_columns.append('product_url')

    default_visible = list(FIXED)
    for col in sorted(corrected_columns):
        if col in final_columns and col not in default_visible:
            default_visible.append(col)
    if has_product_url and 'product_url' not in default_visible:
        default_visible.append('product_url')

    return {
        'success': True,
        'columns': final_columns,
        'fixed': ['id', 'crawl_datetime', 'item'],
        'default_visible': default_visible,
        'rows': all_rows,
        'corrected_map': corrected_map,
    }


def get_history(table_name, retailer, item, column, days, record_id):
    """원본 테이블 이력 조회 (retailer+item 기준 최근 N일)"""
    if table_name not in _HISTORY_TABLES:
        raise ValueError('지원하지 않는 테이블입니다.')
    if not retailer or not item:
        raise ValueError('retailer, item은 필수입니다.')

    product_line, date_col = _HISTORY_TABLES[table_name]

    is_tse = table_name in TSE_TABLE_TO_PRODUCT_LINE
    if is_tse:
        retailer_key = str(retailer).strip().lower()
        config = next(
            (
                value for value in get_tse_retailer_columns(product_line).values()
                if value.get('retailer') == retailer_key
            ),
            None,
        )
        configured = set()
        if config:
            configured.update(config.get('required_columns', []))
            configured.update(config.get('editable_columns', []))
        configured.intersection_update(get_tse_editable_columns(product_line))
        retail_columns = sorted(configured)
    else:
        retail_columns = get_retailer_columns(product_line, retailer)
    if not retail_columns:
        raise ValueError('컬럼 정보를 찾을 수 없습니다.')

    fixed_cols = ['id', date_col, 'item']
    other_cols = [c for c in retail_columns if c not in fixed_cols and c != 'product_url']
    select_cols = fixed_cols + other_cols
    has_product_url = 'product_url' in retail_columns
    if has_product_url:
        select_cols.append('product_url')
    select_sql = ', '.join(select_cols)

    default_visible = ['id', date_col, 'item']
    if column and column in retail_columns and column not in default_visible:
        default_visible.append(column)
    if has_product_url:
        default_visible.append('product_url')

    with dx_connection() as (conn, cursor):
        since_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        date_condition = (
            f"LEFT(TRIM({date_col}), 10) >= %s"
            if is_tse
            else f"({date_col})::date >= %s::date"
        )
        cursor.execute(
            f"SELECT {select_sql} FROM {table_name} "
            f"WHERE account_name = %s AND item = %s AND {date_condition} "
            f"ORDER BY {date_col} ASC",
            (retailer, item, since_date)
        )

        col_names = [desc[0] for desc in cursor.description]
        rows = []
        for row in cursor.fetchall():
            item_dict = {}
            for i, val in enumerate(row):
                if hasattr(val, 'strftime'):
                    item_dict[col_names[i]] = val.strftime('%Y-%m-%d %H:%M:%S')
                elif val is None:
                    item_dict[col_names[i]] = ''
                else:
                    item_dict[col_names[i]] = str(val)
            rows.append(item_dict)

    return {
        'success': True,
        'columns': list(select_cols),
        'fixed': list(fixed_cols),
        'default_visible': default_visible,
        'record_id': int(record_id) if record_id else None,
        'rows': rows,
    }
