"""
NULL 검증 서비스 — 순수 비즈니스 로직 (DB cursor/conn을 받아 처리, HttpResponse 없음)
"""

import time
from copy import deepcopy
from datetime import datetime, timedelta
from apps.common.db import execute_dx_query, dx_table
from apps.common.response import log_error
from apps.common.retail_columns import load_retail_columns, get_editable_columns
from apps.common.retail_validation import get_tv_validation_condition
from apps.common.monitoring_exclusions import DISABLED_SOURCE_TABLES
from apps.dx.dx_layer2.common.context import get_status

try:
    from apps.common.retail_columns import load_tse_retail_columns
    from apps.common.tse_retail import (
        TSE_SOURCE_CONFIG,
        TSE_TABLE_TO_PRODUCT_LINE,
        get_tse_editable_columns,
        get_tse_required_columns,
        get_tse_product_line_for_table,
    )
except (ImportError, AttributeError):
    load_tse_retail_columns = None
    TSE_SOURCE_CONFIG = None
    TSE_TABLE_TO_PRODUCT_LINE = {}
    get_tse_editable_columns = None
    get_tse_required_columns = None
    get_tse_product_line_for_table = None

try:
    from apps.common.tse_retail import TSE_COUNTRY
except (ImportError, AttributeError):
    TSE_COUNTRY = 'TSE'

try:
    from apps.common.tse_retail import (
        tse_retailer_include_unassigned,
        tse_retailer_supports_column,
    )
except (ImportError, AttributeError):
    def tse_retailer_include_unassigned(retailer):
        return str(retailer or '').strip().casefold() == 'homepro'

    def tse_retailer_supports_column(_product_line, _retailer, _column):
        return True


# ==================== NULL 검증 설정 (monitoring_null_check 테이블) ====================

_CACHE_TTL = 60
_null_check_config_cache = None
_null_check_config_cache_time = None
EXCLUDED_RETAIL_TABLES = {'hhp_retail_com'}
EXCLUDED_RETAIL_CATEGORIES = {'hhp_retail'}
YOUTUBE_NULL_TABLES = {
    'youtube_collection_logs',
    'youtube_country_collection_runs',
    'youtube_videos',
    'youtube_comments',
}


def _youtube_column(check_type, display_columns):
    return {
        'check_type': check_type,
        'display_columns': display_columns,
        'query_columns': display_columns,
        'query_days': 0,
    }


_YOUTUBE_RUN_COLUMNS = [
    'id', 'batch_id', 'collection_date', 'collection_country', 'country_label',
    'status', 'keyword_count', 'filtered_video_count', 'raw_video_count',
    'comment_row_count', 'started_at', 'completed_at',
]
_YOUTUBE_VIDEO_COLUMNS = [
    'id', 'collection_country', 'collection_batch_id', 'video_id', 'keyword',
    'title', 'published_at', 'channel_country', 'created_at',
]
_YOUTUBE_COMMENT_COLUMNS = [
    'id', 'collection_country', 'collection_batch_id', 'comment_id', 'video_id',
    'comment_text_display', 'published_at', 'created_at',
]

_YOUTUBE_NULL_CONFIG = {
    'display_name': 'YouTube',
    'display_order': 3,
    'has_retailer': False,
    'checks': {
        'youtube_country_runs': {
            'display_name': 'Country Runs',
            'table_name': 'youtube_country_collection_runs',
            'date_column': 'collection_date',
            'youtube_scope': 'runs',
            'columns': {
                'batch_id': _youtube_column('both', _YOUTUBE_RUN_COLUMNS),
                'collection_date': _youtube_column('null', _YOUTUBE_RUN_COLUMNS),
                'collection_country': _youtube_column('both', _YOUTUBE_RUN_COLUMNS),
                'status': _youtube_column('both', _YOUTUBE_RUN_COLUMNS),
                'keyword_count': _youtube_column('null', _YOUTUBE_RUN_COLUMNS),
                'filtered_video_count': _youtube_column('null', _YOUTUBE_RUN_COLUMNS),
                'raw_video_count': _youtube_column('null', _YOUTUBE_RUN_COLUMNS),
                'comment_row_count': _youtube_column('null', _YOUTUBE_RUN_COLUMNS),
                'started_at': _youtube_column('null', _YOUTUBE_RUN_COLUMNS),
            },
        },
        'youtube_videos': {
            'display_name': 'Videos',
            'table_name': 'youtube_videos',
            'date_column': 'created_at',
            'scope_condition': "category = 'HHP'",
            'youtube_scope': 'records',
            'columns': {
                'collection_country': _youtube_column('both', _YOUTUBE_VIDEO_COLUMNS),
                'collection_batch_id': _youtube_column('both', _YOUTUBE_VIDEO_COLUMNS),
                'video_id': _youtube_column('both', _YOUTUBE_VIDEO_COLUMNS),
                'keyword': _youtube_column('both', _YOUTUBE_VIDEO_COLUMNS),
                'title': _youtube_column('both', _YOUTUBE_VIDEO_COLUMNS),
                'published_at': _youtube_column('both', _YOUTUBE_VIDEO_COLUMNS),
                'channel_country': _youtube_column('both', _YOUTUBE_VIDEO_COLUMNS),
            },
        },
        'youtube_comments': {
            'display_name': 'Comments',
            'table_name': 'youtube_comments',
            'date_column': 'created_at',
            'youtube_scope': 'records',
            'columns': {
                'collection_country': _youtube_column('both', _YOUTUBE_COMMENT_COLUMNS),
                'collection_batch_id': _youtube_column('both', _YOUTUBE_COMMENT_COLUMNS),
                'comment_id': _youtube_column('both', _YOUTUBE_COMMENT_COLUMNS),
                'video_id': _youtube_column('both', _YOUTUBE_COMMENT_COLUMNS),
                'comment_text_display': _youtube_column('both', _YOUTUBE_COMMENT_COLUMNS),
                'published_at': _youtube_column('both', _YOUTUBE_COMMENT_COLUMNS),
            },
        },
    },
}
_YOUTUBE_REVIEW_COLUMNS = {
    check['table_name']: set(check['columns'])
    for check in _YOUTUBE_NULL_CONFIG['checks'].values()
}


def load_null_check_config():
    """
    DB에서 NULL 검증 설정 로드 (3계층: 카테고리 → 그룹 → 컬럼)

    Returns: {
        'tv_retail': {
            'display_name': 'TV Retail',
            'display_order': 1,
            'has_retailer': True,
            'checks': {
                'amazon_tv': {
                    'display_name': 'Amazon',
                    'table_name': 'tv_retail_com',
                    'date_column': 'crawl_datetime',
                    'columns': {
                        'item': {'check_type': 'both', 'display_columns': [...], 'query_columns': [...]},
                        'screen_size': {...},
                    }
                },
                ...
            }
        },
        ...
    }
    """
    global _null_check_config_cache, _null_check_config_cache_time
    now = time.time()
    if _null_check_config_cache is not None and _null_check_config_cache_time and (now - _null_check_config_cache_time) < _CACHE_TTL:
        return _null_check_config_cache

    result = {}
    db_load_succeeded = False

    try:
        query = f"""
            SELECT c.category_name as category, c.display_name as cat_display_name,
                   c.display_order, c.has_retailer,
                   g.check_name, g.display_name as group_display_name,
                   g.table_name, g.date_column,
                   col.check_column, col.check_type,
                   col.display_columns, col.query_columns, col.query_days
            FROM {dx_table('monitoring_null_column')} col
            JOIN {dx_table('monitoring_null_group')} g ON g.id = col.group_id
            JOIN {dx_table('monitoring_null_category')} c ON c.id = g.category_id
            WHERE col.is_active = TRUE AND col.is_del = false
              AND g.is_active = TRUE AND g.is_del = false
              AND c.is_active = TRUE AND c.is_del = false
            ORDER BY c.display_order, g.display_order, col.id
        """
        rows = execute_dx_query(query)

        for row in rows:
            category = row.get('category', '')
            table_name = row.get('table_name', '')
            if (
                category in EXCLUDED_RETAIL_CATEGORIES
                or table_name in EXCLUDED_RETAIL_TABLES
                or str(table_name).lower() in DISABLED_SOURCE_TABLES
                or str(category).lower() == 'youtube'
                or table_name in YOUTUBE_NULL_TABLES
            ):
                continue
            check_name = row['check_name']
            check_column = row['check_column']
            display_columns = row.get('display_columns', '') or ''
            query_columns = row.get('query_columns', '') or ''

            if category not in result:
                result[category] = {
                    'display_name': row.get('cat_display_name', ''),
                    'display_order': row.get('display_order', 0),
                    'has_retailer': row.get('has_retailer', False),
                    'checks': {}
                }

            if check_name not in result[category]['checks']:
                result[category]['checks'][check_name] = {
                    'display_name': row.get('group_display_name', ''),
                    'table_name': row['table_name'],
                    'date_column': row.get('date_column', ''),
                    'columns': {}
                }

            result[category]['checks'][check_name]['columns'][check_column] = {
                'check_type': row.get('check_type', 'both'),
                'display_columns': [col.strip() for col in display_columns.split('|') if col.strip()],
                'query_columns': [col.strip() for col in query_columns.split('|') if col.strip()],
                'query_days': int(row.get('query_days', 0) or 0)
            }

        db_load_succeeded = True

    except Exception as e:
        log_error(e, 'db')

    # DB 설정 조회 결과와 무관하게 구형 YouTube 설정을 신규 구조로 교체한다.
    result['youtube'] = deepcopy(_YOUTUBE_NULL_CONFIG)
    result = dict(sorted(
        result.items(),
        key=lambda item: (
            item[1].get('display_order')
            if isinstance(item[1].get('display_order'), (int, float))
            else 999
        ),
    ))

    # DB 조회 실패 시 비-YouTube 설정을 60초간 빈 상태로 고정하지 않는다.
    if db_load_succeeded:
        _null_check_config_cache = result
        _null_check_config_cache_time = now

    return result


def get_all_categories():
    """모든 대시보드 카테고리 목록 반환 (display_order 순)."""
    categories = list(load_null_check_config().keys())
    runtime = _get_tse_runtime()
    if runtime:
        try:
            tse_config = runtime['load_columns']()
        except Exception as exc:
            log_error(exc, 'db')
            tse_config = {}
        for product_line, source in runtime['sources'].items():
            if (
                tse_config.get(product_line)
                and source['section_code'] not in categories
            ):
                categories.append(source['section_code'])
    return categories


def get_check_names_by_category(category):
    """특정 카테고리의 모든 check_name 목록 반환"""
    config = load_null_check_config()
    cat_config = config.get(category)
    if not cat_config:
        return []
    return list(cat_config['checks'].keys())


def get_null_check_config(category, check_name, check_column=None):
    """특정 check_name(또는 컬럼)의 NULL 검증 설정 반환"""
    config = load_null_check_config()
    cat_config = config.get(category)
    if not cat_config:
        return None
    check_config = cat_config['checks'].get(check_name)
    if not check_config:
        return None
    if check_column:
        col_config = check_config['columns'].get(check_column)
        if col_config:
            return {
                'table_name': check_config['table_name'],
                'date_column': check_config['date_column'],
                **col_config
            }
        return None
    return check_config


def reload_null_check_config():
    """캐시 초기화 후 다시 로드"""
    global _null_check_config_cache
    _null_check_config_cache = None
    return load_null_check_config()


# ==================== NULL 판정 공통 로직 ====================

def _build_null_sql_condition(col_name, check_type):
    """NULL 판정 SQL 조건 생성 (공통) — stats COUNT / detail WHERE 양쪽에서 사용"""
    if check_type == 'null':
        return f"{col_name} IS NULL"
    elif check_type == 'empty':
        return f"TRIM(CAST({col_name} AS TEXT)) = ''"
    else:  # both
        return f"({col_name} IS NULL OR TRIM(CAST({col_name} AS TEXT)) = '')"


def _is_field_null(val, check_type):
    """NULL 판정 Python 로직 (공통) — detail에서 레코드별 null_fields 판정에 사용"""
    if check_type == 'null':
        return val is None
    elif check_type == 'empty':
        return val is not None and str(val).strip() == ''
    else:  # both
        return val is None or str(val).strip() == ''


def _get_tse_runtime():
    """Load the TSE registry lazily so legacy Layer 2 imports stay isolated."""
    if not all((
        load_tse_retail_columns,
        TSE_SOURCE_CONFIG,
        get_tse_editable_columns,
        get_tse_required_columns,
        get_tse_product_line_for_table,
    )):
        return None

    return {
        'load_columns': load_tse_retail_columns,
        'sources': TSE_SOURCE_CONFIG,
        'max_editable': get_tse_editable_columns,
        'max_required': get_tse_required_columns,
        'product_line_for_table': get_tse_product_line_for_table,
    }


def _get_tse_product_line_for_category(category, runtime=None):
    runtime = runtime or _get_tse_runtime()
    if not runtime:
        return None
    for product_line, source in runtime['sources'].items():
        if source['section_code'] == category:
            return product_line
    return None


def _get_tse_retailer_config(product_line, retailer, runtime=None, config=None):
    """Resolve an active retailer config case-insensitively."""
    runtime = runtime or _get_tse_runtime()
    if not runtime:
        return None
    if config is None:
        config = runtime['load_columns']()
    retailer_key = str(retailer or '').strip().lower()
    product_configs = config.get(product_line, {})
    if not retailer_key:
        unassigned_configs = [
            (display_name, retailer_config)
            for display_name, retailer_config in product_configs.items()
            if tse_retailer_include_unassigned(
                retailer_config.get('retailer') or display_name
            )
        ]
        if len(unassigned_configs) == 1:
            return unassigned_configs[0]
    for display_name, retailer_config in product_configs.items():
        if (
            str(display_name).strip().lower() == retailer_key
            or str(retailer_config.get('retailer') or '').strip().lower()
            == retailer_key
        ):
            return display_name, retailer_config
    return None


def _safe_tse_required_columns(product_line, retailer_config, runtime):
    """Keep DB-configured identifiers inside the server-owned allowlist."""
    allowed = set(runtime['max_required'](product_line))
    return [
        column for column in retailer_config.get('required_columns', [])
        if column in allowed and tse_retailer_supports_column(
            product_line, retailer_config.get('retailer'), column
        )
    ]


def _safe_tse_editable_columns(product_line, retailer_config, runtime):
    """Require both the server maximum and DB ``is_editable`` flag."""
    allowed = set(runtime['max_editable'](product_line))
    return [
        column for column in retailer_config.get('editable_columns', [])
        if column in allowed and tse_retailer_supports_column(
            product_line, retailer_config.get('retailer'), column
        )
    ]


def _get_tse_null_display_columns(column, select_columns):
    """Return the compact default TSE detail columns in display order."""
    price_columns = (
        'final_sku_price', 'original_sku_price', 'savings',
    )
    candidates = ['id', 'crawl_datetime', 'item', 'retailer_sku_name']
    if column in price_columns:
        candidates.extend(price_columns)
    else:
        candidates.append(column)
    candidates.append('product_url')

    available = set(select_columns)
    result = []
    for candidate in candidates:
        if candidate in available and candidate not in result:
            result.append(candidate)
    return result


def _get_tse_null_query_columns(column, select_columns):
    """Return a compact, correction-friendly column list for display SQL."""
    candidates = [
        'id', 'item', 'sku', 'retailer_sku_name', column,
        'final_sku_price', 'original_sku_price', 'savings',
        'crawl_datetime', 'product_url',
    ]
    available = set(select_columns)
    result = []
    for candidate in candidates:
        if candidate in available and candidate not in result:
            result.append(candidate)
    return result


def _build_tse_country_scope(alias='source'):
    """Keep TSE rows plus missing-country rows that Layer 2 must report."""
    country_column = f'{alias}.country'
    null_condition = _build_null_sql_condition(country_column, 'both')
    return f'({country_column} = %s OR {null_condition})'


TSE_NORMAL_REVIEW_RECHECK_DAYS = 7


def _tse_review_date(value):
    """Return a date for source/correction values, or ``None`` if invalid."""
    if isinstance(value, datetime):
        return value.date()
    try:
        return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def _tse_review_identity(item, retailer_sku_name):
    """Build the stable identity used to carry a normal review forward."""
    item_text = str(item or '').strip()
    if not item_text:
        return None
    retailer_sku_text = str(retailer_sku_name or '').strip()
    return item_text.casefold(), retailer_sku_text.casefold()


def _load_tse_recent_normal_reviews(
        cursor, canonical_table, retailer, columns, start_date, end_date):
    """Load normal reviews and their original item/SKU identity."""
    if not columns:
        return []
    placeholders = ', '.join(['%s'] * len(columns))
    cursor.execute(f"""
        SELECT correction.record_id,
               correction.column_name,
               correction.memo,
               correction.created_id,
               correction.created_at,
               correction.reason,
               correction.crawl_date,
               reviewed_source.item,
               reviewed_source.retailer_sku_name
        FROM monitoring_corrections correction
        JOIN {canonical_table} reviewed_source
          ON reviewed_source.id = correction.record_id
        WHERE correction.table_name = %s
          AND correction.crawl_date >= %s
          AND correction.crawl_date <= %s
          AND correction.correction_type = 'null_check'
          AND correction.status = 'normal'
          AND LOWER(correction.retailer) = LOWER(%s)
          AND correction.column_name IN ({placeholders})
        ORDER BY correction.crawl_date DESC, correction.id DESC
    """, (
        canonical_table, str(start_date), str(end_date), retailer, *columns,
    ))
    reviews = []
    for row in cursor.fetchall():
        review_date = _tse_review_date(row[6])
        if review_date is None:
            continue
        reviews.append({
            'record_id': row[0],
            'column_name': row[1],
            'memo': row[2],
            'created_id': row[3],
            'created_at': row[4],
            'reason': row[5],
            'crawl_date': review_date,
            'identity': _tse_review_identity(row[7], row[8]),
        })
    return reviews


def _is_tse_review_suppressed(record, column, row_date, reviews):
    """Hide the same reviewed identity until its seven-day recheck date."""
    effective_date = _tse_review_date(row_date)
    if effective_date is None:
        return False
    identity = _tse_review_identity(
        record.get('item'), record.get('retailer_sku_name')
    )
    record_id = str(record.get('id'))
    for review in reviews:
        if review['column_name'] != column:
            continue
        elapsed_days = (effective_date - review['crawl_date']).days
        if elapsed_days < 0 or elapsed_days >= TSE_NORMAL_REVIEW_RECHECK_DAYS:
            continue
        if elapsed_days == 0 and record_id == str(review['record_id']):
            return True
        if identity is not None and identity == review['identity']:
            return True
    return False


def _get_tse_null_tables(cursor, target_date, runtime, tse_config):
    """Return TSE NULL cards using only each retailer's latest daily batch."""
    tables = []
    total_issues = 0
    target_date_text = str(target_date)

    for product_line, source in runtime['sources'].items():
        retailer_rows = []
        table_total = 0
        table_issues = 0
        table_fields = []
        canonical_table = source['table_name']
        product_configs = tse_config.get(product_line, {})
        country_scope = _build_tse_country_scope()

        for display_name, retailer_config in product_configs.items():
            required_columns = _safe_tse_required_columns(
                product_line, retailer_config, runtime
            )
            if not required_columns:
                continue

            retailer_value = retailer_config['retailer']
            include_unassigned = tse_retailer_include_unassigned(
                retailer_value
            )
            account_scope = "LOWER(source.account_name) = LOWER(%s)"
            if include_unassigned:
                account_scope = f"""(
                    {account_scope}
                    OR source.account_name IS NULL
                    OR TRIM(CAST(source.account_name AS TEXT)) = ''
                )"""
            count_parts = []
            for column in required_columns:
                condition = _build_null_sql_condition(column, 'both')
                count_parts.append(
                    f"COUNT(CASE WHEN {condition} THEN 1 END) AS null_{column}"
                )

            query = f"""
                WITH latest_batch AS (
                    SELECT source.batch_id
                    FROM {canonical_table} source
                    WHERE LEFT(TRIM(source.crawl_datetime), 10) = %s
                      AND LOWER(source.account_name) = LOWER(%s)
                      AND {country_scope}
                    ORDER BY source.id DESC
                    LIMIT 1
                )
                SELECT (SELECT batch_id FROM latest_batch) AS latest_batch_id,
                       COUNT(*) AS total,
                       {', '.join(count_parts)}
                FROM {canonical_table} source
                WHERE LEFT(TRIM(source.crawl_datetime), 10) = %s
                  AND {account_scope}
                  AND {country_scope}
                  AND source.batch_id IS NOT DISTINCT FROM
                      (SELECT batch_id FROM latest_batch)
                  AND EXISTS (SELECT 1 FROM latest_batch)
            """
            cursor.execute(
                query,
                (
                    target_date_text, retailer_value, TSE_COUNTRY,
                    target_date_text, retailer_value, TSE_COUNTRY,
                ),
            )
            row = cursor.fetchone()

            latest_batch_id = row[0] if row else None
            total = (row[1] or 0) if row else 0
            fields_detail = {
                column: ((row[index + 2] or 0) if row else 0)
                for index, column in enumerate(required_columns)
            }

            # Carry a normal review forward for the same item and
            # retailer_sku_name.  The identity is exposed again on day seven.
            if latest_batch_id is not None and any(fields_detail.values()):
                recent_reviews = _load_tse_recent_normal_reviews(
                    cursor,
                    canonical_table,
                    retailer_value,
                    required_columns,
                    target_date - timedelta(
                        days=TSE_NORMAL_REVIEW_RECHECK_DAYS - 1
                    ),
                    target_date,
                )
                if recent_reviews:
                    review_columns = []
                    for review_column in (
                        'id', 'item', 'retailer_sku_name', *required_columns
                    ):
                        if review_column not in review_columns:
                            review_columns.append(review_column)
                    review_select_sql = ', '.join(
                        f'source.{review_column}'
                        for review_column in review_columns
                    )
                    cursor.execute(f"""
                        SELECT {review_select_sql}
                        FROM {canonical_table} source
                        WHERE LEFT(TRIM(source.crawl_datetime), 10) = %s
                          AND {account_scope}
                          AND {country_scope}
                          AND source.batch_id IS NOT DISTINCT FROM %s
                    """, (
                        target_date_text, retailer_value, TSE_COUNTRY,
                        latest_batch_id,
                    ))
                    current_rows = [
                        dict(zip(review_columns, current_row))
                        for current_row in cursor.fetchall()
                    ]
                    fields_detail = {
                        review_column: sum(
                            1 for current_row in current_rows
                            if _is_field_null(
                                current_row.get(review_column), 'both'
                            )
                            and not _is_tse_review_suppressed(
                                current_row,
                                review_column,
                                target_date,
                                recent_reviews,
                            )
                        )
                        for review_column in required_columns
                    }

            issue_count = sum(fields_detail.values())
            retailer_rows.append({
                'retailer': display_name,
                'total': total,
                'total_null_count': issue_count,
                'status': get_status(issue_count),
                'fields_detail': fields_detail,
                'latest_batch_id': latest_batch_id,
            })
            table_total += total
            table_issues += issue_count
            for column in required_columns:
                if column not in table_fields:
                    table_fields.append(column)

        if retailer_rows:
            tables.append({
                'table': source['section_code'],
                'table_name': source['display_name'],
                'total_records': table_total,
                'total_issues': table_issues,
                'status': get_status(table_issues),
                'retailers': retailer_rows,
                'fields': table_fields,
            })
            total_issues += table_issues

    return tables, total_issues


def _append_tse_null_stats(cursor, target_date, validation):
    """Append TSE stats behind a savepoint so legacy stats still render."""
    runtime = _get_tse_runtime()
    if not runtime:
        return 0
    try:
        tse_config = runtime['load_columns']()
    except Exception as exc:
        log_error(exc, 'db')
        return 0
    if not any(tse_config.get(key) for key in runtime['sources']):
        return 0

    savepoint = 'layer2_tse_null_stats'
    cursor.execute(f'SAVEPOINT {savepoint}')
    try:
        tables, issue_count = _get_tse_null_tables(
            cursor, target_date, runtime, tse_config
        )
    except Exception as exc:
        cursor.execute(f'ROLLBACK TO SAVEPOINT {savepoint}')
        cursor.execute(f'RELEASE SAVEPOINT {savepoint}')
        log_error(exc, 'db')
        return 0

    cursor.execute(f'RELEASE SAVEPOINT {savepoint}')
    validation['tables'].extend(tables)
    return issue_count


def _get_tse_null_detail(
    cursor, target_date, category, retailer, column, runtime, tse_config,
    days=1,
):
    """Return latest-batch TSE NULL rows and edit/history metadata."""
    product_line = _get_tse_product_line_for_category(category, runtime)
    source = runtime['sources'].get(product_line) if product_line else None
    resolved = (
        _get_tse_retailer_config(
            product_line, retailer, runtime, tse_config
        )
        if source else None
    )
    if not source or not resolved:
        return {
            'results': [], 'display_config': {}, 'query_config': {},
            'date': str(target_date),
        }

    display_name, retailer_config = resolved
    required_columns = _safe_tse_required_columns(
        product_line, retailer_config, runtime
    )
    if column not in required_columns:
        return {
            'results': [], 'display_config': {}, 'query_config': {},
            'date': str(target_date),
        }

    canonical_table = source['table_name']
    retailer_value = retailer_config['retailer']
    target_date_text = str(target_date)
    history_days = min(max(int(days or 1), 1), 30)
    where_condition = _build_null_sql_condition(f'source.{column}', 'both')
    country_scope = _build_tse_country_scope()
    include_unassigned = tse_retailer_include_unassigned(retailer_value)
    account_scope = "LOWER(source.account_name) = LOWER(%s)"
    if include_unassigned:
        account_scope = f"""(
            {account_scope}
            OR source.account_name IS NULL
            OR TRIM(CAST(source.account_name AS TEXT)) = ''
        )"""
    cursor.execute(f"""
        WITH latest_batch AS (
            SELECT source.id, source.batch_id
            FROM {canonical_table} source
            WHERE LEFT(TRIM(source.crawl_datetime), 10) = %s
              AND LOWER(source.account_name) = LOWER(%s)
              AND {country_scope}
            ORDER BY source.id DESC
            LIMIT 1
        )
        SELECT source.*
        FROM {canonical_table} source
        CROSS JOIN latest_batch
        WHERE LEFT(TRIM(source.crawl_datetime), 10) = %s
          AND {account_scope}
          AND {country_scope}
          AND source.batch_id IS NOT DISTINCT FROM latest_batch.batch_id
          AND {where_condition}
        ORDER BY source.id
    """, (
        target_date_text, retailer_value, TSE_COUNTRY,
        target_date_text, retailer_value, TSE_COUNTRY,
    ))
    select_columns = [description[0] for description in cursor.description]
    raw_rows = cursor.fetchall()
    column_index = {
        column_name: index for index, column_name in enumerate(select_columns)
    }
    recent_reviews = _load_tse_recent_normal_reviews(
        cursor,
        canonical_table,
        retailer_value,
        [column],
        target_date - timedelta(
            days=history_days + TSE_NORMAL_REVIEW_RECHECK_DAYS - 2
        ),
        target_date,
    )
    normal_reviews = {}
    for review in recent_reviews:
        normal_reviews[
            f"{review['record_id']}_{review['column_name']}"
        ] = {
            'memo': review['memo'],
            'created_id': review['created_id'],
            'created_at': (
                review['created_at'].strftime('%Y-%m-%d %H:%M:%S')
                if isinstance(review['created_at'], datetime)
                else str(review['created_at'] or '') or None
            ),
            'reason': review['reason'],
        }

    def row_as_mapping(row):
        return {
            column_name: row[index]
            for column_name, index in column_index.items()
        }

    def row_is_suppressed(row):
        row_record = row_as_mapping(row)
        if not _is_field_null(row_record.get(column), 'both'):
            return False
        return _is_tse_review_suppressed(
            row_record,
            column,
            row_record.get('crawl_datetime') or target_date,
            recent_reviews,
        )

    is_expanded = False
    item_index = column_index.get('item')
    if history_days > 1 and item_index is not None:
        unreviewed_rows = [
            row for row in raw_rows if not row_is_suppressed(row)
        ]
        error_items = sorted({
            row[item_index]
            for row in unreviewed_rows
            if not _is_field_null(row[item_index], 'both')
        }, key=lambda value: str(value))
        has_missing_item = any(
            _is_field_null(row[item_index], 'both')
            for row in unreviewed_rows
        )
        history_conditions = []
        history_values = []
        if error_items:
            placeholders = ', '.join(['%s'] * len(error_items))
            history_conditions.append(f'source.item IN ({placeholders})')
            history_values.extend(error_items)
        if has_missing_item:
            item_null_condition = _build_null_sql_condition(
                'source.item', 'both'
            )
            history_conditions.append(
                f'(({item_null_condition}) AND ({where_condition}))'
            )

        if history_conditions:
            start_date_text = str(
                target_date - timedelta(days=history_days - 1)
            )
            history_scope = ' OR '.join(history_conditions)
            cursor.execute(f"""
                WITH latest_batches AS (
                    SELECT DISTINCT ON (
                        LEFT(TRIM(source.crawl_datetime), 10),
                        LOWER(source.account_name)
                    )
                           LEFT(TRIM(source.crawl_datetime), 10) AS crawl_date,
                           LOWER(source.account_name) AS retailer_key,
                           source.batch_id,
                           source.id
                    FROM {canonical_table} source
                    WHERE LEFT(TRIM(source.crawl_datetime), 10) >= %s
                      AND LEFT(TRIM(source.crawl_datetime), 10) <= %s
                      AND LOWER(source.account_name) = LOWER(%s)
                      AND {country_scope}
                    ORDER BY crawl_date, retailer_key, source.id DESC
                )
                SELECT source.*
                FROM {canonical_table} source
                JOIN latest_batches latest
                  ON LEFT(TRIM(source.crawl_datetime), 10)
                     = latest.crawl_date
                 AND source.batch_id IS NOT DISTINCT FROM latest.batch_id
                WHERE {account_scope}
                  AND {country_scope}
                  AND ({history_scope})
                ORDER BY source.item,
                         LEFT(TRIM(source.crawl_datetime), 10),
                         source.id
            """, (
                start_date_text, target_date_text, retailer_value, TSE_COUNTRY,
                retailer_value, TSE_COUNTRY, *history_values,
            ))
            raw_rows = cursor.fetchall()
            is_expanded = True

    results = []
    for row in raw_rows:
        if row_is_suppressed(row):
            continue
        record = {}
        for column_name, index in column_index.items():
            value = row[index]
            record[column_name] = (
                value.strftime('%Y-%m-%d %H:%M:%S')
                if isinstance(value, datetime) else value
            )
        column_value = row[column_index[column]]
        record['null_fields'] = (
            [column] if _is_field_null(column_value, 'both') else []
        )
        results.append(record)

    editable_columns = _safe_tse_editable_columns(
        product_line, retailer_config, runtime
    )
    return {
        'results': results,
        'select_cols': select_columns,
        'editable_cols': editable_columns,
        'actual_table': canonical_table,
        'display_config': {
            column: {
                'select_columns': _get_tse_null_display_columns(
                    column, select_columns
                ),
            },
        },
        'query_config': {
            column: _get_tse_null_query_columns(column, select_columns),
        },
        'query_retailer': retailer_value,
        'query_include_unassigned': include_unassigned,
        'supports_day_history': True,
        'normal_reviews': normal_reviews,
        'date_column': 'crawl_datetime',
        'date': target_date_text,
        'history_days': history_days,
        'latest_batch_only': not is_expanded,
        'retailer': display_name,
    }


def get_null_check_query_parts(category, check_name):
    """NULL 체크 쿼리 파트 생성 (stats 건수 체크용)"""
    category_config = get_null_check_config(category, check_name)
    if not category_config:
        return None

    count_parts = []
    column_names = []

    for col_name, col_config in category_config['columns'].items():
        column_names.append(col_name)
        check_type = col_config.get('check_type', 'both')
        cond = _build_null_sql_condition(col_name, check_type)
        count_parts.append(f"COUNT(CASE WHEN {cond} THEN 1 END) as null_{col_name}")

    return {
        'table_name': category_config['table_name'],
        'date_column': category_config['date_column'],
        'count_parts': count_parts,
        'column_names': column_names,
        'scope_condition': category_config.get('scope_condition'),
        'youtube_scope': category_config.get('youtube_scope'),
    }


def _build_null_date_where(query_parts, target_date):
    """날짜 기준과 신규 YouTube 국가·배치 범위를 함께 생성한다."""
    table_name = query_parts['table_name']
    date_column = query_parts['date_column']
    youtube_scope = query_parts.get('youtube_scope')

    if youtube_scope == 'runs':
        return (
            f"COALESCE({date_column}, DATE(started_at)) = %s",
            [target_date],
        )

    if youtube_scope == 'records':
        missing_country = f"""
            ({table_name}.collection_country IS NULL
             OR TRIM(CAST({table_name}.collection_country AS TEXT)) = '')
        """
        missing_batch = f"""
            ({table_name}.collection_batch_id IS NULL
             OR TRIM(CAST({table_name}.collection_batch_id AS TEXT)) = '')
        """
        return (
            f"""
                (
                    EXISTS (
                        SELECT 1
                        FROM youtube_country_collection_runs matched_run
                        WHERE matched_run.collection_date = %s
                          AND matched_run.collection_country = {table_name}.collection_country
                          AND matched_run.batch_id = {table_name}.collection_batch_id
                    )
                    OR (
                        {missing_country}
                        AND NOT {missing_batch}
                        AND EXISTS (
                            SELECT 1
                            FROM youtube_country_collection_runs batch_run
                            WHERE batch_run.collection_date = %s
                              AND batch_run.batch_id = {table_name}.collection_batch_id
                        )
                    )
                    OR (
                        {missing_batch}
                        AND NOT {missing_country}
                        AND EXISTS (
                            SELECT 1
                            FROM youtube_country_collection_runs country_run
                            WHERE country_run.collection_date = %s
                              AND country_run.collection_country = {table_name}.collection_country
                        )
                    )
                    OR (
                        ({missing_country} OR {missing_batch})
                        AND DATE({table_name}.{date_column}) = %s
                        AND EXISTS (
                            SELECT 1
                            FROM youtube_country_collection_runs day_run
                            WHERE day_run.collection_date = %s
                        )
                    )
                )
            """,
            [target_date, target_date, target_date, target_date, target_date],
        )

    return f"DATE({date_column}) = %s", [target_date]


def _apply_static_scope(date_where, params, query_parts):
    """코드에 고정된 추가 범위 조건만 적용한다."""
    scope_condition = query_parts.get('scope_condition')
    if scope_condition:
        date_where += f" AND ({scope_condition})"

    return date_where, params


def get_non_product_exclusion_condition(table_name):
    """Layer 2 TV NULL validation scope excluding item-master non-products."""
    if table_name != 'tv_retail_com':
        return ''

    item_master_table = dx_table('tv_item_mst')
    return f"""
        NOT EXISTS (
            SELECT 1
            FROM {item_master_table} non_product
            WHERE non_product.is_product IS FALSE
              AND non_product.item IS NOT DISTINCT FROM {table_name}.item
              AND non_product.account_name IS NOT DISTINCT FROM {table_name}.account_name
        )
    """




def get_null_stats(cursor, target_date, include_youtube=True):
    """NULL 검증 통계 — 대시보드용"""
    total_null_issues = 0

    null_validation = {
        'type': 'null',
        'type_name': 'NULL 검증',
        'type_name_en': 'Null Validation',
        'description': '필수 필드의 NULL 또는 빈값 검증',
        'icon': '🔍',
        'tables': []
    }

    config = load_null_check_config()

    for category, cat_info in config.items():
        if not include_youtube and str(category).lower() == 'youtube':
            continue
        if not cat_info['checks']:
            continue

        display_name = cat_info['display_name']
        has_retailer = cat_info['has_retailer']

        cat_retailers = []
        cat_total_records = 0
        cat_total_issues = 0
        all_cat_fields = []

        for check_name, check_info in cat_info['checks'].items():
            query_parts = get_null_check_query_parts(category, check_name)
            if not query_parts:
                continue

            retailer_name = check_info['display_name']

            date_where, params = _build_null_date_where(
                query_parts, target_date
            )
            date_where, params = _apply_static_scope(
                date_where, params, query_parts
            )

            if has_retailer:
                date_where += " AND account_name = %s"
                params.append(retailer_name)

            if query_parts['table_name'] == 'tv_retail_com':
                date_where += f" AND {get_tv_validation_condition()}"
                date_where += (
                    f" AND {get_non_product_exclusion_condition(query_parts['table_name'])}"
                )

            query = f"""
                SELECT COUNT(*) as total,
                       {', '.join(query_parts['count_parts'])}
                FROM {query_parts['table_name']}
                WHERE {date_where}
            """
            cursor.execute(query, params)

            row = cursor.fetchone()

            if row:
                total = row[0] or 0
                fields_detail = {}
                total_null_count = 0
                for i, col_name in enumerate(query_parts['column_names']):
                    null_count = row[i + 1] or 0
                    fields_detail[col_name] = null_count
                    total_null_count += null_count
                    if col_name not in all_cat_fields:
                        all_cat_fields.append(col_name)

                # 정상처리(normal) 건 차감
                correction_where = "table_name = %s AND crawl_date = %s AND correction_type = 'null_check' AND status = 'normal'"
                correction_params = [query_parts['table_name'], str(target_date)]

                if has_retailer:
                    correction_where += " AND retailer = %s"
                    correction_params.append(retailer_name)

                cursor.execute(f"""
                    SELECT column_name, COUNT(*) FROM monitoring_corrections
                    WHERE {correction_where}
                    GROUP BY column_name
                """, correction_params)

                for correction_row in cursor.fetchall():
                    correction_col, correction_count = correction_row[0], correction_row[1]
                    if correction_col in fields_detail:
                        fields_detail[correction_col] = max(0, fields_detail[correction_col] - correction_count)
                        total_null_count = max(0, total_null_count - correction_count)

                cat_retailers.append({
                    'retailer': retailer_name,
                    'total': total,
                    'total_null_count': total_null_count,
                    'status': get_status(total_null_count),
                    'fields_detail': fields_detail
                })
                cat_total_records += total
                cat_total_issues += total_null_count

        null_validation['tables'].append({
            'table': category,
            'table_name': display_name,
            'total_records': cat_total_records,
            'total_issues': cat_total_issues,
            'status': get_status(cat_total_issues),
            'retailers': cat_retailers,
            'fields': all_cat_fields
        })
        total_null_issues += cat_total_issues

    total_null_issues += _append_tse_null_stats(
        cursor, target_date, null_validation
    )
    null_validation['total_issues'] = total_null_issues
    null_validation['status'] = get_status(total_null_issues)
    return null_validation, total_null_issues


def get_null_detail(cursor, target_date, category, retailer, days, column):
    """NULL 필드 상세 조회 — 특정 컬럼의 NULL 행만 조회. dict 반환."""

    runtime = _get_tse_runtime()
    product_line = _get_tse_product_line_for_category(category, runtime)
    if runtime and product_line:
        tse_config = runtime['load_columns']()
        return _get_tse_null_detail(
            cursor, target_date, category, retailer, column,
            runtime, tse_config, days=days,
        )

    if category in EXCLUDED_RETAIL_CATEGORIES:
        return {'results': [], 'display_config': {}, 'query_config': {}, 'date': str(target_date)}

    next_date = target_date + timedelta(days=1)

    # 카테고리 정보 가져오기
    config = load_null_check_config()
    cat_info = config.get(category)
    if not cat_info or not cat_info['checks']:
        return {'results': [], 'display_config': {}, 'query_config': {}, 'date': str(target_date)}

    has_retailer = cat_info['has_retailer']

    # retailer 이름으로 check_name 매칭 (display_name 비교)
    check_name = None
    if retailer:
        for cn, check_info in cat_info['checks'].items():
            if check_info['display_name'].lower() == retailer.lower():
                check_name = cn
                break
    if not check_name:
        check_name = list(cat_info['checks'].keys())[0]

    # 설정 가져오기
    category_config = get_null_check_config(category, check_name)
    if not category_config or column not in category_config['columns']:
        return {'results': [], 'display_config': {}, 'query_config': {}, 'date': str(target_date)}

    col_config = category_config['columns'][column]
    actual_table = category_config['table_name']
    date_col = category_config.get('date_column', 'created_at')
    query_parts = {
        'table_name': actual_table,
        'date_column': date_col,
        'scope_condition': category_config.get('scope_condition'),
        'youtube_scope': category_config.get('youtube_scope'),
    }

    # WHERE 조건: 해당 컬럼만
    check_type = col_config.get('check_type', 'both')
    where_cond = _build_null_sql_condition(column, check_type)

    # 쿼리 생성 — 전체 컬럼 조회 (프론트 컬럼 선택 지원)
    if has_retailer:
        query = f"""
            SELECT *
            FROM {actual_table}
            WHERE {date_col}::timestamp >= %s AND {date_col}::timestamp < %s
              AND {where_cond}
        """
        params = [str(target_date), str(next_date)]
        if retailer:
            query += " AND account_name = %s"
            params.append(retailer)
        if actual_table == 'tv_retail_com':
            query += f" AND {get_tv_validation_condition()}"
            query += f" AND {get_non_product_exclusion_condition(actual_table)}"
        query += f" ORDER BY {date_col}"
    else:
        detail_where, params = _build_null_date_where(
            query_parts, target_date
        )
        detail_where, params = _apply_static_scope(
            detail_where, params, query_parts
        )
        query = f"""
            SELECT *
            FROM {actual_table}
            WHERE {detail_where}
              AND {where_cond}
            ORDER BY {date_col} DESC
        """

    cursor.execute(query, params)
    select_cols = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()

    # 컬럼 인덱스 매핑
    col_index = {col: idx for idx, col in enumerate(select_cols)}

    # 정상 처리(normal) 건 조회 — 확장 조회 전에 실행하여 정상처리 item 제외
    normal_set = set()
    normal_reviews = {}
    cursor.execute("""
        SELECT record_id, column_name, memo, created_id, created_at, reason
        FROM monitoring_corrections
        WHERE table_name = %s AND crawl_date = %s AND column_name = %s
          AND correction_type = 'null_check' AND status = 'normal'
    """, (actual_table, str(target_date), column))
    for nr_row in cursor.fetchall():
        normal_set.add(nr_row[0])  # record_id만
        normal_reviews[f"{nr_row[0]}_{nr_row[1]}"] = {
            'memo': nr_row[2],
            'created_id': nr_row[3],
            'created_at': nr_row[4].strftime('%Y-%m-%d %H:%M:%S') if nr_row[4] else None,
            'reason': nr_row[5]
        }

    # retail + days > 1: 오류 item 추출 후 N일치 확장 조회
    is_expanded = False
    id_idx = col_index['id']
    if has_retailer and days > 1 and rows:
        item_idx = select_cols.index('item') if 'item' in select_cols else None
        if item_idx is not None:
            # 정상처리 건 제외 후 에러 item 추출
            error_items = list(set(r[item_idx] for r in rows if r[item_idx] and r[id_idx] not in normal_set))
            if error_items:
                start_date = target_date - timedelta(days=days - 1)
                placeholders = ', '.join(['%s'] * len(error_items))
                non_product_scope = get_non_product_exclusion_condition(actual_table)
                expand_query = f"""
                    SELECT *
                    FROM {actual_table}
                    WHERE {date_col}::timestamp >= %s AND {date_col}::timestamp < %s
                      AND account_name = %s
                      AND item IN ({placeholders})
                      {f'AND {get_tv_validation_condition()}' if actual_table == 'tv_retail_com' else ''}
                      {f'AND {non_product_scope}' if non_product_scope else ''}
                    ORDER BY item, {date_col}
                """
                expand_params = [str(start_date), str(next_date), retailer] + error_items
                cursor.execute(expand_query, expand_params)
                rows = cursor.fetchall()
                is_expanded = True

    results = []
    col_idx = col_index.get(column)
    for row in rows:
        # 정상처리 건이면 스킵
        if row[id_idx] in normal_set:
            continue

        # 확장 조회(days > 1)면 전체 이력 표시, 1일치면 NULL만 필터
        if not is_expanded:
            if col_idx is not None and not _is_field_null(row[col_idx], check_type):
                continue

        record_data = {}
        for col_name in select_cols:
            idx = col_index.get(col_name)
            if idx is not None:
                val = row[idx]
                if isinstance(val, datetime):
                    record_data[col_name] = val.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    record_data[col_name] = val
        record_data['null_fields'] = [column] if (col_idx is not None and _is_field_null(row[col_idx], check_type)) else []
        results.append(record_data)

    # display_config, query_config 생성
    display_config = {}
    query_config = {}
    display_cols = col_config.get('display_columns', [])
    query_cols = col_config.get('query_columns', [])
    if display_cols:
        display_config[column] = {'select_columns': display_cols}
    if query_cols:
        query_config[column] = query_cols

    # 리테일러 전체 수집항목 컬럼 + 수정 가능 컬럼
    all_retail_cols = []
    editable_cols = []
    if has_retailer and retailer:
        product_line = 'tv' if category == 'tv_retail' else 'hhp'
        retail_cols_data = load_retail_columns()
        all_retail_cols = retail_cols_data.get(product_line, {}).get(retailer, [])
        editable_cols = get_editable_columns(product_line, retailer)

    return {
        'results': results,
        'select_cols': all_retail_cols,
        'editable_cols': editable_cols,
        'actual_table': actual_table,
        'display_config': display_config,
        'query_config': query_config,
        'normal_reviews': normal_reviews,
        'date_column': date_col,
        'date': str(target_date)
    }


# null_review 테이블 화이트리스트
VALID_TABLES_UPDATE = ({
    'tv_retail_com',
    'youtube_country_collection_runs', 'youtube_videos', 'youtube_comments',
    'market_trend', 'market_comp_product', 'market_comp_event', 'openai_forecast_results',
} | set(TSE_TABLE_TO_PRODUCT_LINE)) - DISABLED_SOURCE_TABLES


def save_null_review(cursor, conn, table_name, record_id, column_name, status, memo, reason, crawl_date, correction_type, username):
    """NULL 검증 정상 처리 저장. dict 반환."""

    valid_correction_types = {'null': 'null_check', 'format': 'format_check', 'duplicate': 'duplicate_check'}
    correction_type_value = valid_correction_types.get(correction_type, 'null_check')

    if not all([table_name, record_id, column_name, status]):
        return {'error': '필수 파라미터 누락', 'status_code': 400}

    # 정상 처리만 허용 (reverted 불가)
    if status != 'normal':
        return {'error': '잘못된 status 값', 'status_code': 400}

    if not reason:
        return {'error': '이유 선택은 필수입니다', 'status_code': 400}

    if table_name not in VALID_TABLES_UPDATE:
        return {'error': '허용되지 않는 테이블', 'status_code': 400}

    runtime = _get_tse_runtime()
    tse_product_line = None
    if runtime:
        try:
            tse_product_line = runtime['product_line_for_table'](table_name)
        except ValueError:
            tse_product_line = None
    if tse_product_line:
        tse_allowed_columns = (
            runtime['max_editable'](tse_product_line)
            if correction_type_value == 'format_check'
            else runtime['max_required'](tse_product_line)
        )
        if column_name not in set(tse_allowed_columns):
            return {'error': '허용되지 않는 컬럼', 'status_code': 400}

    youtube_columns = _YOUTUBE_REVIEW_COLUMNS.get(table_name)
    if youtube_columns is not None and column_name not in youtube_columns:
        return {'error': '허용되지 않는 컬럼', 'status_code': 400}

    # 신규 YouTube 테이블에는 account_name/item 컬럼이 없다.
    if youtube_columns is not None:
        select_columns = column_name
    else:
        select_columns = f"{column_name}, account_name, item"

    if tse_product_line:
        country_scope = _build_tse_country_scope()
        cursor.execute(f"""
            SELECT {select_columns}
            FROM {table_name} source
            WHERE source.id = %s
              AND {country_scope}
              AND LEFT(TRIM(source.crawl_datetime), 10) = %s
        """, (record_id, TSE_COUNTRY, str(crawl_date)))
    else:
        cursor.execute(
            f"SELECT {select_columns} FROM {table_name} WHERE id = %s",
            (record_id,)
        )
    row = cursor.fetchone()
    if not row:
        return {'error': '해당 레코드가 없습니다', 'status_code': 404}

    old_value = row[0]
    retailer = None if youtube_columns is not None else row[1]
    item_value = (
        None if youtube_columns is not None
        else str(row[2]) if row[2] else None
    )

    if tse_product_line:
        try:
            tse_config = runtime['load_columns']()
            retailer_config = _get_tse_retailer_config(
                tse_product_line, retailer, runtime, tse_config
            )
        except Exception as exc:
            log_error(exc, 'db')
            return {'error': 'TSE 설정 조회 실패', 'status_code': 500}
        if not retailer_config:
            return {'error': '허용되지 않는 리테일러', 'status_code': 400}
        if not retailer:
            retailer = retailer_config[1].get('retailer') or retailer_config[0]
        configured_columns = (
            _safe_tse_editable_columns(
                tse_product_line, retailer_config[1], runtime
            )
            if correction_type_value == 'format_check'
            else _safe_tse_required_columns(
                tse_product_line, retailer_config[1], runtime
            )
        )
        if column_name not in configured_columns:
            return {'error': '허용되지 않는 컬럼', 'status_code': 400}

    # 중복 정상처리 체크
    cursor.execute("""
        SELECT id FROM monitoring_corrections
        WHERE table_name = %s AND record_id = %s AND column_name = %s
          AND correction_type = %s AND status = 'normal' AND crawl_date = %s
    """, (table_name, record_id, column_name, correction_type_value, str(crawl_date)))
    if cursor.fetchone():
        return {'error': '이미 정상처리된 항목입니다', 'status_code': 400}

    now = datetime.now()

    # monitoring_corrections에 이력 저장 (실제 데이터는 수정하지 않음)
    cursor.execute("""
        INSERT INTO monitoring_corrections
            (layer, correction_type, table_name, record_id, column_name,
             old_value, new_value, crawl_date, created_id, created_at, status, memo, reason, retailer, item)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        2, correction_type_value, table_name, record_id, column_name,
        str(old_value) if old_value is not None else None,
        None,
        crawl_date, username, now, status, memo or None,
        reason or None, retailer or None, item_value
    ))

    conn.commit()

    return {'success': True, 'status': status}
