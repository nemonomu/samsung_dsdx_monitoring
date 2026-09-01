"""
anomaly_validation 서비스 — 중복 검증 비즈니스 로직
cursor + params 를 받아 plain dict 를 반환한다.
"""

from datetime import date

from apps.common.retail_columns import (
    get_editable_columns, get_duplicate_key_columns,
    get_retailer_list, get_retail_duplicate_keys,
)
from apps.common.retail_validation import get_tv_validation_condition
from apps.common.monitoring_exclusions import DISABLED_SOURCE_TABLES
from apps.dx.dx_layer2.common.context import get_status

try:
    from apps.common.retail_columns import get_tse_retailer_columns
    from apps.common.tse_retail import TSE_COUNTRY, TSE_SOURCE_CONFIG
except ImportError:  # Backward-compatible fallback for isolated legacy tests.
    get_tse_retailer_columns = None
    TSE_COUNTRY = 'TSE'
    TSE_SOURCE_CONFIG = {}

try:
    from apps.common.tse_retail import tse_retailer_include_unassigned
except (ImportError, AttributeError):
    def tse_retailer_include_unassigned(_retailer):
        return False

try:
    from apps.common.inspection_dates import resolve_monitoring_date
    from apps.common.sea_retail import SEA_RETAIL_SOURCES
except (ImportError, AttributeError):
    resolve_monitoring_date = None
    SEA_RETAIL_SOURCES = {}


SEA_DUPLICATE_SECTION_BY_PRODUCT = {
    'ref': 'sea_ref_retail',
    'ldy': 'sea_ldy_retail',
}
SEA_DUPLICATE_PRODUCT_BY_SECTION = {
    section_code: product_key
    for product_key, section_code in SEA_DUPLICATE_SECTION_BY_PRODUCT.items()
}


# table 파라미터 화이트리스트
VALID_TABLES_ANOMALY = {
    'tv_retail', 'youtube_videos',
    'market_trend', 'market_product', 'market_event',
} | {
    section_code
    for product_key, section_code in SEA_DUPLICATE_SECTION_BY_PRODUCT.items()
    if SEA_RETAIL_SOURCES.get(product_key)
} | {
    source['section_code'] for source in TSE_SOURCE_CONFIG.values()
}
_YOUTUBE_VIDEO_DUP_KEYS = (
    'video_id', 'keyword', 'collection_country', 'collection_batch_id'
)

# 테이블별 중복 키 / 날짜 컬럼 / 오전오후 구분 매핑
_DUP_TABLE_CONFIG = {
    'tv_retail': {
        'actual': 'tv_retail_com',
        'dup_keys': 'item, account_name',
        'date_col': 'crawl_datetime',
        'use_period': True,
        'retailer_col': 'account_name',
    },
    'youtube_videos': {
        'actual': 'youtube_videos',
        'dup_keys': ', '.join(_YOUTUBE_VIDEO_DUP_KEYS),
        'date_col': 'created_at',
        'use_period': False,
        'retailer_col': None,
    },
    'market_trend': {
        'actual': 'market_trend',
        'dup_keys': 'keyword',
        'date_col': 'crawl_at_local_time',
        'use_period': False,
        'retailer_col': None,
    },
    'market_product': {
        'actual': 'market_comp_product',
        'dup_keys': 'batch_id, samsung_series_name, comp_brand, comp_series_name',
        'date_col': 'created_at',
        'use_period': False,
        'retailer_col': None,
    },
    'market_event': {
        'actual': 'market_comp_event',
        'dup_keys': 'batch_id, comp_brand, comp_sku_name',
        'date_col': 'created_at',
        'use_period': False,
        'retailer_col': None,
    },
}

for _sea_product_key, _sea_section_code in (
        SEA_DUPLICATE_SECTION_BY_PRODUCT.items()):
    _sea_source = SEA_RETAIL_SOURCES.get(_sea_product_key)
    if not _sea_source:
        continue
    _DUP_TABLE_CONFIG[_sea_section_code] = {
        'actual': _sea_source['table_name'],
        'dup_keys': 'page_type, item',
        'date_col': _sea_source['date_column'],
        'use_period': False,
        'retailer_col': 'account_name',
        'sea_product_key': _sea_product_key,
        'backup_table': _sea_source['backup_table'],
    }

# 직접 상세조회·중복삭제 API도 중단 원본 테이블에 접근하지 못하게 한다.
for _table_key, _table_config in tuple(_DUP_TABLE_CONFIG.items()):
    if _table_config['actual'] in DISABLED_SOURCE_TABLES:
        VALID_TABLES_ANOMALY.discard(_table_key)
        _DUP_TABLE_CONFIG.pop(_table_key)


def _sea_duplicate_product_key(table):
    value = str(table or '').strip().lower()
    if value in SEA_DUPLICATE_PRODUCT_BY_SECTION:
        return SEA_DUPLICATE_PRODUCT_BY_SECTION[value]
    for product_key, source in SEA_RETAIL_SOURCES.items():
        if product_key not in SEA_DUPLICATE_SECTION_BY_PRODUCT:
            continue
        table_name = str(source.get('table_name') or '').strip().lower()
        if value in {
            product_key,
            str(source.get('key') or '').strip().lower(),
            table_name,
            table_name.split('.')[-1],
        }:
            return product_key
    return None


def _resolve_sea_duplicate_retailer(source, retailer):
    retailer_key = str(retailer or '').strip().casefold()
    for configured in source.get('retailers', ()):
        if retailer_key == str(configured).strip().casefold():
            return configured
    return None


def _fetch_sea_duplicate_rows(cursor, source_date, source, retailer_value):
    """Fetch one retailer's latest MAIN-anchored SEA appliance batch."""
    canonical_table = source['table_name']
    date_column = source['date_column']
    source_date_sql = (
        f"LEFT(TRIM(CAST(source.{date_column} AS TEXT)), 10)"
    )
    select_columns = [
        'id', 'batch_id', 'country', 'account_name', 'page_type', 'item',
        'sku', 'retailer_sku_name', 'final_sku_price', date_column,
        'product_url',
    ]
    cursor.execute(f"""
        WITH latest_batch AS (
            SELECT source.batch_id
            FROM {canonical_table} source
            WHERE {source_date_sql} = %s
              AND LOWER(TRIM(source.account_name)) = LOWER(TRIM(%s))
              AND UPPER(TRIM(COALESCE(source.page_type, ''))) = 'MAIN'
            ORDER BY source.id DESC
            LIMIT 1
        )
        SELECT {', '.join('source.' + column for column in select_columns)}
        FROM {canonical_table} source
        CROSS JOIN latest_batch
        WHERE {source_date_sql} = %s
          AND (
              LOWER(TRIM(source.account_name)) = LOWER(TRIM(%s))
              OR source.account_name IS NULL
              OR TRIM(CAST(source.account_name AS TEXT)) = ''
          )
          AND (
              UPPER(TRIM(COALESCE(source.country, ''))) = 'SEA'
              OR source.country IS NULL
              OR TRIM(CAST(source.country AS TEXT)) = ''
          )
          AND source.batch_id IS NOT DISTINCT FROM latest_batch.batch_id
          AND UPPER(TRIM(COALESCE(source.page_type, '')))
              IN ('MAIN', 'BSR')
        ORDER BY UPPER(TRIM(source.page_type)), source.item, source.id
    """, (
        str(source_date), retailer_value,
        str(source_date), retailer_value,
    ))
    return [
        dict(zip(select_columns, row))
        for row in cursor.fetchall()
    ]


def _serialize_sea_duplicate_row(row):
    return {
        key: (str(value) if value is not None and key != 'id' else value)
        for key, value in row.items()
    }


def build_sea_duplicate_groups(rows):
    """Group duplicate page_type+item rows and classify mapping conflicts."""
    grouped = {}
    for row in rows:
        page_type_key = _duplicate_key(row.get('page_type'))
        item_key = _duplicate_key(row.get('item'))
        if not page_type_key or not item_key:
            continue
        grouped.setdefault((page_type_key, item_key), []).append(row)

    groups = []
    for duplicate_rows in grouped.values():
        if len(duplicate_rows) <= 1:
            continue
        first = duplicate_rows[0]
        sku_values = {
            _duplicate_key(row.get('sku')) or ''
            for row in duplicate_rows
        }
        name_values = {
            _duplicate_key(row.get('retailer_sku_name')) or ''
            for row in duplicate_rows
        }
        is_mapping_conflict = len(sku_values) > 1 or len(name_values) > 1
        duplicate_type = (
            '상품 매핑 충돌' if is_mapping_conflict else '완전 중복'
        )
        page_type = _duplicate_text(first.get('page_type')).upper()
        item = _duplicate_text(first.get('item'))
        groups.append({
            'duplicate_type': duplicate_type,
            'page_type': page_type,
            'item': item,
            'retailer_sku_name': ', '.join(sorted({
                _duplicate_text(row.get('retailer_sku_name'))
                for row in duplicate_rows
                if _duplicate_text(row.get('retailer_sku_name'))
            })),
            'dup_count': len(duplicate_rows),
            'reason': (
                f'{page_type}의 동일 item에 서로 다른 SKU/상품명이 '
                f'{len(duplicate_rows)}건 연결됨'
                if is_mapping_conflict else
                f'{page_type}의 동일 item이 최신 배치에 '
                f'{len(duplicate_rows)}건 수집됨'
            ),
            'records': [
                _serialize_sea_duplicate_row(row) for row in duplicate_rows
            ],
        })
    groups.sort(key=lambda group: (
        group['page_type'], group['item'], group['duplicate_type']
    ))
    return groups


def _get_sea_anomaly_detail(
        cursor, target_date, table, retailer, page, page_size):
    product_key = _sea_duplicate_product_key(table)
    source = SEA_RETAIL_SOURCES.get(product_key)
    retailer_value = (
        _resolve_sea_duplicate_retailer(source, retailer) if source else None
    )
    if not source or not retailer_value or not resolve_monitoring_date:
        return {
            'date': str(target_date), 'table': table, 'retailer': retailer,
            'select_cols': {'group': [], 'record': []},
            'editable_cols': [], 'actual_table': '', 'readonly': True,
            'results': {
                'duplicates': [], 'total_groups': 0, 'page': page,
                'page_size': page_size, 'total_pages': 0,
            },
        }

    date_mapping = resolve_monitoring_date(
        target_date, 'SEA', source['source_key']
    )
    source_date = date.fromisoformat(date_mapping['source_date'])
    rows = _fetch_sea_duplicate_rows(
        cursor, source_date, source, retailer_value
    )
    groups = build_sea_duplicate_groups(rows)
    total_groups = len(groups)
    total_pages = (
        (total_groups + page_size - 1) // page_size if total_groups else 0
    )
    offset = (page - 1) * page_size
    return {
        'date': date_mapping['inspection_date'],
        'inspection_date': date_mapping['inspection_date'],
        'source_date': date_mapping['source_date'],
        'offset_days': date_mapping['offset_days'],
        'date_column': source['date_column'],
        'table': table,
        'retailer': retailer_value,
        'select_cols': {
            'group': [
                'duplicate_type', 'page_type', 'item',
                'retailer_sku_name', 'dup_count', 'reason',
            ],
            'record': [
                'id', 'sku', 'retailer_sku_name', 'final_sku_price',
                source['date_column'], 'product_url',
            ],
        },
        'editable_cols': [],
        'actual_table': source['table_name'],
        'backup_table': source['backup_table'],
        'readonly': False,
        'results': {
            'duplicates': groups[offset:offset + page_size],
            'total_groups': total_groups,
            'page': page,
            'page_size': page_size,
            'total_pages': total_pages,
        },
    }


def _append_sea_anomaly_stats(cursor, target_date, validation):
    if not resolve_monitoring_date:
        return 0
    savepoint = 'layer2_sea_duplicate_stats'
    cursor.execute(f'SAVEPOINT {savepoint}')
    total_issues = 0
    try:
        for product_key, section_code in (
                SEA_DUPLICATE_SECTION_BY_PRODUCT.items()):
            source = SEA_RETAIL_SOURCES.get(product_key)
            if not source:
                continue
            date_mapping = resolve_monitoring_date(
                target_date, 'SEA', source['source_key']
            )
            source_date = date.fromisoformat(date_mapping['source_date'])
            retailer_rows = []
            table_records = 0
            table_issues = 0
            for retailer_value in source.get('retailers', ()):
                rows = _fetch_sea_duplicate_rows(
                    cursor, source_date, source, retailer_value
                )
                duplicate_count = len(build_sea_duplicate_groups(rows))
                retailer_rows.append({
                    'retailer': retailer_value,
                    'total': len(rows),
                    'duplicate_groups': duplicate_count,
                    'duplicate_keys': ['page_type + item'],
                    'status': get_status(duplicate_count),
                })
                table_records += len(rows)
                table_issues += duplicate_count
            validation['tables'].append({
                'table': section_code,
                'table_name': f"SEA {source['category']}",
                'total_records': table_records,
                'total_issues': table_issues,
                'duplicate_groups': table_issues,
                'duplicate_keys': ['page_type + item'],
                'status': get_status(table_issues),
                'retailers': retailer_rows,
                'inspection_date': date_mapping['inspection_date'],
                'source_date': date_mapping['source_date'],
                'offset_days': date_mapping['offset_days'],
            })
            total_issues += table_issues
    except Exception as exc:
        cursor.execute(f'ROLLBACK TO SAVEPOINT {savepoint}')
        cursor.execute(f'RELEASE SAVEPOINT {savepoint}')
        print(f'[WARN] layer2_sea_duplicate_stats: {exc}')
        return 0
    cursor.execute(f'RELEASE SAVEPOINT {savepoint}')
    return total_issues


def _tse_duplicate_product_line(table):
    value = str(table or '').strip().lower()
    for product_line, source in TSE_SOURCE_CONFIG.items():
        if value in (product_line, source['section_code'].lower()):
            return product_line
    return None


def _resolve_tse_duplicate_retailer(product_line, retailer):
    if not get_tse_retailer_columns:
        return None
    configs = get_tse_retailer_columns(product_line)
    retailer_key = str(retailer or '').strip().casefold()
    if not retailer_key:
        unassigned_configs = [
            (display_name, config)
            for display_name, config in configs.items()
            if tse_retailer_include_unassigned(
                config.get('retailer') or display_name
            )
        ]
        if len(unassigned_configs) == 1:
            return unassigned_configs[0]
    for display_name, config in configs.items():
        if retailer_key in {
            str(display_name).strip().casefold(),
            str(config.get('retailer') or '').strip().casefold(),
        }:
            return display_name, config
    return None


def _fetch_tse_duplicate_rows(
        cursor, target_date, source, retailer_value,
        include_unassigned=False):
    canonical_table = source['table_name']
    account_scope = 'LOWER(source.account_name) = LOWER(%s)'
    if include_unassigned:
        account_scope = f"""(
            {account_scope}
            OR source.account_name IS NULL
            OR TRIM(CAST(source.account_name AS TEXT)) = ''
        )"""
    country_scope = """(
        source.country = %s
        OR source.country IS NULL
        OR TRIM(CAST(source.country AS TEXT)) = ''
    )"""
    select_columns = [
        'id', 'batch_id', 'country', 'account_name', 'item', 'sku',
        'retailer_sku_name', 'final_sku_price', 'crawl_datetime',
        'product_url',
    ]
    cursor.execute(f"""
        WITH latest_batch AS (
            SELECT source.batch_id
            FROM {canonical_table} source
            WHERE LEFT(TRIM(source.crawl_datetime), 10) = %s
              AND LOWER(source.account_name) = LOWER(%s)
              AND {country_scope}
            ORDER BY source.id DESC
            LIMIT 1
        )
        SELECT {', '.join('source.' + column for column in select_columns)}
        FROM {canonical_table} source
        WHERE LEFT(TRIM(source.crawl_datetime), 10) = %s
          AND {account_scope}
          AND {country_scope}
          AND source.batch_id IS NOT DISTINCT FROM
              (SELECT batch_id FROM latest_batch)
          AND EXISTS (SELECT 1 FROM latest_batch)
        ORDER BY source.item, source.retailer_sku_name, source.id
    """, (
        str(target_date), retailer_value, TSE_COUNTRY,
        str(target_date), retailer_value, TSE_COUNTRY,
    ))
    return [
        dict(zip(select_columns, row))
        for row in cursor.fetchall()
    ]


def _duplicate_text(value):
    return str(value or '').strip()


def _duplicate_key(value):
    text = _duplicate_text(value)
    return text.casefold() if text else None


def _serialize_tse_duplicate_row(row):
    return {
        key: (str(value) if value is not None and key != 'id' else value)
        for key, value in row.items()
    }


def build_tse_duplicate_groups(rows):
    """Build exact duplicates and item-to-retailer-SKU mapping conflicts."""
    exact = {}
    by_item = {}
    for row in rows:
        item_key = _duplicate_key(row.get('item'))
        retailer_sku_key = _duplicate_key(row.get('retailer_sku_name'))
        if item_key:
            by_item.setdefault(item_key, []).append(row)
        if item_key and retailer_sku_key:
            exact.setdefault((item_key, retailer_sku_key), []).append(row)

    groups = []
    for duplicate_rows in exact.values():
        if len(duplicate_rows) <= 1:
            continue
        first = duplicate_rows[0]
        groups.append({
            'duplicate_type': '완전 중복',
            'item': _duplicate_text(first.get('item')),
            'retailer_sku_name': _duplicate_text(
                first.get('retailer_sku_name')
            ),
            'dup_count': len(duplicate_rows),
            'reason': '동일 item + retailer_sku_name이 최신 배치에 2건 이상 있습니다.',
            'records': [
                _serialize_tse_duplicate_row(row) for row in duplicate_rows
            ],
        })

    for duplicate_rows in by_item.values():
        retailer_skus = {
            _duplicate_key(row.get('retailer_sku_name'))
            for row in duplicate_rows
            if _duplicate_key(row.get('retailer_sku_name'))
        }
        if len(retailer_skus) <= 1:
            continue
        first = duplicate_rows[0]
        display_values = sorted({
            _duplicate_text(row.get('retailer_sku_name'))
            for row in duplicate_rows
            if _duplicate_text(row.get('retailer_sku_name'))
        })
        groups.append({
            'duplicate_type': 'Item 매핑 충돌',
            'item': _duplicate_text(first.get('item')),
            'retailer_sku_name': ', '.join(display_values),
            'dup_count': len(duplicate_rows),
            'reason': '동일 item에 서로 다른 retailer_sku_name이 연결되어 있습니다.',
            'records': [
                _serialize_tse_duplicate_row(row) for row in duplicate_rows
            ],
        })

    groups.sort(key=lambda group: (
        group['duplicate_type'], group['item'], group['retailer_sku_name']
    ))
    return groups


def _get_tse_anomaly_detail(
        cursor, target_date, table, retailer, page, page_size):
    product_line = _tse_duplicate_product_line(table)
    source = TSE_SOURCE_CONFIG.get(product_line)
    resolved = (
        _resolve_tse_duplicate_retailer(product_line, retailer)
        if source else None
    )
    if not source or not resolved:
        return {
            'date': str(target_date), 'table': table, 'retailer': retailer,
            'select_cols': {'group': [], 'record': []},
            'editable_cols': [], 'actual_table': '', 'readonly': True,
            'results': {
                'duplicates': [], 'total_groups': 0, 'page': page,
                'page_size': page_size, 'total_pages': 0,
            },
        }

    display_name, retailer_config = resolved
    rows = _fetch_tse_duplicate_rows(
        cursor, target_date, source, retailer_config['retailer'],
        tse_retailer_include_unassigned(retailer_config['retailer']),
    )
    groups = build_tse_duplicate_groups(rows)
    total_groups = len(groups)
    total_pages = (
        (total_groups + page_size - 1) // page_size if total_groups else 0
    )
    offset = (page - 1) * page_size
    return {
        'date': str(target_date),
        'table': table,
        'retailer': display_name,
        'select_cols': {
            'group': [
                'duplicate_type', 'item', 'retailer_sku_name',
                'dup_count', 'reason',
            ],
            'record': [
                'id', 'sku', 'retailer_sku_name', 'final_sku_price',
                'crawl_datetime', 'product_url',
            ],
        },
        'editable_cols': [],
        'actual_table': source['table_name'],
        'readonly': True,
        'results': {
            'duplicates': groups[offset:offset + page_size],
            'total_groups': total_groups,
            'page': page,
            'page_size': page_size,
            'total_pages': total_pages,
        },
    }


def _append_tse_anomaly_stats(cursor, target_date, validation):
    if not TSE_SOURCE_CONFIG or not get_tse_retailer_columns:
        return 0
    savepoint = 'layer2_tse_duplicate_stats'
    cursor.execute(f'SAVEPOINT {savepoint}')
    total_issues = 0
    try:
        for product_line, source in TSE_SOURCE_CONFIG.items():
            configs = get_tse_retailer_columns(product_line)
            retailer_rows = []
            table_records = 0
            table_issues = 0
            for display_name, retailer_config in configs.items():
                rows = _fetch_tse_duplicate_rows(
                    cursor, target_date, source,
                    retailer_config['retailer'],
                    tse_retailer_include_unassigned(
                        retailer_config['retailer']
                    ),
                )
                duplicate_count = len(build_tse_duplicate_groups(rows))
                retailer_rows.append({
                    'retailer': display_name,
                    'total': len(rows),
                    'duplicate_groups': duplicate_count,
                    'duplicate_keys': [
                        'item + retailer_sku_name',
                        'item → retailer_sku_name',
                    ],
                    'status': get_status(duplicate_count),
                })
                table_records += len(rows)
                table_issues += duplicate_count
            if retailer_rows:
                validation['tables'].append({
                    'table': source['section_code'],
                    'table_name': source['display_name'],
                    'total_records': table_records,
                    'total_issues': table_issues,
                    'duplicate_groups': table_issues,
                    'status': get_status(table_issues),
                    'retailers': retailer_rows,
                })
                total_issues += table_issues
    except Exception as exc:
        cursor.execute(f'ROLLBACK TO SAVEPOINT {savepoint}')
        cursor.execute(f'RELEASE SAVEPOINT {savepoint}')
        print(f'[WARN] layer2_tse_duplicate_stats: {exc}')
        return 0
    cursor.execute(f'RELEASE SAVEPOINT {savepoint}')
    return total_issues


def _build_dup_delete_query(table, retailer=''):
    """
    중복 그룹에서 최신 1건만 남기고 삭제할 대상의 id + row_to_json 을 조회하는 쿼리를 생성.
    반환: (sql, params)  — sql에는 %s 플레이스홀더, params는 (target_date,) 기준으로 외부에서 결합
    """
    cfg = _DUP_TABLE_CONFIG.get(table)
    if not cfg:
        return None, None

    actual = cfg['actual']
    date_col = cfg['date_col']
    dup_keys = cfg['dup_keys']
    use_period = cfg['use_period']
    retailer_col = cfg['retailer_col']

    # 오전/오후 구분이 필요한 경우
    period_expr = ''
    partition_extra = ''
    if use_period:
        period_expr = f"CASE WHEN EXTRACT(HOUR FROM {date_col}::timestamp) < 12 THEN 'AM' ELSE 'PM' END"
        partition_extra = f', {period_expr}'

    # 리테일러 필터
    retailer_where = ''
    if retailer_col and retailer:
        retailer_where = f"AND {retailer_col} = %s"
    validation_where = ''
    if actual == 'tv_retail_com':
        validation_where = f"AND {get_tv_validation_condition('t')}"

    sql = f"""
        SELECT sub.id, sub.record_data FROM (
            SELECT t.id, row_to_json(t.*) as record_data,
                   ROW_NUMBER() OVER (
                       PARTITION BY {dup_keys}{partition_extra}
                       ORDER BY {date_col} DESC
                   ) as rn
            FROM {actual} t
            WHERE DATE({date_col}::timestamp) = %s
              {validation_where}
              {retailer_where}
        ) sub
        WHERE sub.rn > 1
    """
    return sql, retailer_where


def get_anomaly_detail(cursor, target_date, table, retailer, days, page, page_size):
    """중복 검증 상세 조회 — plain dict 반환"""
    if _sea_duplicate_product_key(table):
        return _get_sea_anomaly_detail(
            cursor, target_date, table, retailer, page, page_size
        )
    if _tse_duplicate_product_line(table):
        return _get_tse_anomaly_detail(
            cursor, target_date, table, retailer, page, page_size
        )

    offset = (page - 1) * page_size
    if table == 'hhp_retail':
        return {
            'date': str(target_date),
            'table': table,
            'retailer': retailer,
            'select_cols': {'group': [], 'record': []},
            'editable_cols': [],
            'actual_table': '',
            'results': {
                'duplicates': [],
                'total_groups': 0,
                'page': page,
                'page_size': page_size,
                'total_pages': 0
            }
        }

    duplicates = []
    total_groups = 0
    select_cols = {'group': [], 'record': []}

    if table == 'tv_retail':
        select_cols = {'group': ['item', 'retailer', 'period', 'dup_count', 'reason'], 'record': ['id', 'product_url', 'crawl_datetime', 'page_type', 'main_rank', 'bsr_rank']}
        # 전체 그룹 수
        cursor.execute(f"""
            SELECT COUNT(*) FROM (
                SELECT item, account_name,
                       CASE WHEN EXTRACT(HOUR FROM crawl_datetime::timestamp) < 12 THEN '오전' ELSE '오후' END as period
                FROM tv_retail_com
                WHERE DATE(crawl_datetime::timestamp) = %s
                  AND {get_tv_validation_condition()}
                  AND (%s = '' OR account_name = %s)
                GROUP BY item, account_name, period
                HAVING COUNT(*) > 1
            ) sub
        """, (target_date, retailer, retailer))
        total_groups = cursor.fetchone()[0]

        # 중복 그룹 찾기: item + 시간대 (오전/오후 각각 1건만 있어야 정상)
        # page_type은 무시 - main과 bsr에서 같은 item이 수집되는 건 정상
        cursor.execute(f"""
            WITH duplicate_groups AS (
                SELECT item, account_name,
                       CASE WHEN EXTRACT(HOUR FROM crawl_datetime::timestamp) < 12 THEN '오전' ELSE '오후' END as period,
                       COUNT(*) as dup_count
                FROM tv_retail_com
                WHERE DATE(crawl_datetime::timestamp) = %s
                  AND {get_tv_validation_condition()}
                  AND (%s = '' OR account_name = %s)
                GROUP BY item, account_name, period
                HAVING COUNT(*) > 1
                ORDER BY COUNT(*) DESC, item, period
                LIMIT %s OFFSET %s
            )
            SELECT d.item, d.account_name, d.period, d.dup_count,
                   t.id, t.product_url, t.crawl_datetime, t.page_type, t.main_rank, t.bsr_rank
            FROM duplicate_groups d
            JOIN tv_retail_com t ON t.item IS NOT DISTINCT FROM d.item
                AND t.account_name = d.account_name
                AND DATE(t.crawl_datetime::timestamp) = %s
                AND {get_tv_validation_condition('t')}
                AND CASE WHEN EXTRACT(HOUR FROM t.crawl_datetime::timestamp) < 12 THEN '오전' ELSE '오후' END = d.period
            ORDER BY d.dup_count DESC, d.item, d.period, t.crawl_datetime
        """, (target_date, retailer, retailer, page_size, offset, target_date))

        rows = cursor.fetchall()

        # 중복 그룹별로 묶기
        dup_groups = {}
        for row in rows:
            key = (row[0], row[1], row[2])  # item, account_name, period
            if key not in dup_groups:
                dup_groups[key] = {
                    'item': row[0],
                    'retailer': row[1],
                    'period': row[2],
                    'dup_count': row[3],
                    'reason': f'동일 item이 {row[2]}에 {row[3]}건 수집됨',
                    'records': []
                }
            dup_groups[key]['records'].append({
                'id': row[4],
                'product_url': row[5],
                'crawl_datetime': str(row[6]) if row[6] else None,
                'page_type': row[7],
                'main_rank': row[8],
                'bsr_rank': row[9]
            })

        duplicates = list(dup_groups.values())

    elif table == 'hhp_retail':
        select_cols = {'group': ['item', 'retailer', 'period', 'dup_count', 'reason'], 'record': ['id', 'product_url', 'crawl_datetime', 'page_type', 'rank']}
        cursor.execute("""
            SELECT COUNT(*) FROM (
                SELECT item, account_name,
                       CASE WHEN EXTRACT(HOUR FROM crawl_strdatetime::timestamp) < 12 THEN '오전' ELSE '오후' END as period
                FROM hhp_retail_com
                WHERE DATE(crawl_strdatetime::timestamp) = %s
                  AND (%s = '' OR account_name = %s)
                GROUP BY item, account_name, period
                HAVING COUNT(*) > 1
            ) sub
        """, (target_date, retailer, retailer))
        total_groups = cursor.fetchone()[0]

        # 중복 그룹 찾기: item + 시간대 (오전/오후 각각 1건만 있어야 정상)
        # trend_rank는 Bestbuy만 있음
        cursor.execute("""
            WITH duplicate_groups AS (
                SELECT item, account_name,
                       CASE WHEN EXTRACT(HOUR FROM crawl_strdatetime::timestamp) < 12 THEN '오전' ELSE '오후' END as period,
                       COUNT(*) as dup_count
                FROM hhp_retail_com
                WHERE DATE(crawl_strdatetime::timestamp) = %s
                  AND (%s = '' OR account_name = %s)
                GROUP BY item, account_name, period
                HAVING COUNT(*) > 1
                ORDER BY COUNT(*) DESC, item, period
                LIMIT %s OFFSET %s
            )
            SELECT d.item, d.account_name, d.period, d.dup_count,
                   h.id, h.product_url, h.crawl_strdatetime, h.page_type, h.main_rank, h.bsr_rank, h.trend_rank
            FROM duplicate_groups d
            JOIN hhp_retail_com h ON h.item IS NOT DISTINCT FROM d.item
                AND h.account_name = d.account_name
                AND DATE(h.crawl_strdatetime::timestamp) = %s
                AND CASE WHEN EXTRACT(HOUR FROM h.crawl_strdatetime::timestamp) < 12 THEN '오전' ELSE '오후' END = d.period
            ORDER BY d.dup_count DESC, d.item, d.period, h.crawl_strdatetime
        """, (target_date, retailer, retailer, page_size, offset, target_date))

        rows = cursor.fetchall()

        dup_groups = {}
        for row in rows:
            key = (row[0], row[1], row[2])  # item, account_name, period
            if key not in dup_groups:
                dup_groups[key] = {
                    'item': row[0],
                    'retailer': row[1],
                    'period': row[2],
                    'dup_count': row[3],
                    'reason': f'동일 item이 {row[2]}에 {row[3]}건 수집됨',
                    'records': []
                }
            page_type = row[7]
            # page_type에 따라 해당 rank 선택
            if page_type == 'trend':
                rank = row[10]  # trend_rank (Bestbuy만)
            elif page_type == 'main':
                rank = row[8]   # main_rank
            elif page_type == 'bsr':
                rank = row[9]   # bsr_rank
            else:
                rank = row[8] or row[9]  # fallback
            dup_groups[key]['records'].append({
                'id': row[4],
                'product_url': row[5],
                'crawl_datetime': str(row[6]) if row[6] else None,
                'page_type': page_type,
                'rank': rank
            })

        duplicates = list(dup_groups.values())

    elif table == 'youtube_videos':
        select_cols = {
            'group': [
                'video_id', 'keyword', 'dup_count', 'reason'
            ],
            'record': ['id', 'title', 'created_at']
        }
        cursor.execute("""
            SELECT COUNT(*) FROM (
                SELECT
                    v.collection_country,
                    v.collection_batch_id,
                    v.video_id,
                    v.keyword
                FROM youtube_videos v
                WHERE v.category = 'HHP'
                  AND EXISTS (
                      SELECT 1
                      FROM youtube_country_collection_runs r
                      WHERE r.collection_date = %s
                        AND r.collection_country = v.collection_country
                        AND r.batch_id = v.collection_batch_id
                  )
                GROUP BY
                    v.collection_country,
                    v.collection_batch_id,
                    v.video_id,
                    v.keyword
                HAVING COUNT(*) > 1
            ) sub
        """, (target_date,))
        total_groups = cursor.fetchone()[0]

        # 동일 국가·배치 안에서 같은 video_id+keyword가 반복된 경우만 중복이다.
        cursor.execute("""
            WITH duplicate_groups AS (
                SELECT
                    v.collection_country,
                    v.collection_batch_id,
                    v.video_id,
                    v.keyword,
                    COUNT(*) AS dup_count
                FROM youtube_videos v
                WHERE v.category = 'HHP'
                  AND EXISTS (
                      SELECT 1
                      FROM youtube_country_collection_runs r
                      WHERE r.collection_date = %s
                        AND r.collection_country = v.collection_country
                        AND r.batch_id = v.collection_batch_id
                  )
                GROUP BY
                    v.collection_country,
                    v.collection_batch_id,
                    v.video_id,
                    v.keyword
                HAVING COUNT(*) > 1
                ORDER BY
                    COUNT(*) DESC,
                    v.collection_country,
                    v.collection_batch_id,
                    v.video_id,
                    v.keyword
                LIMIT %s OFFSET %s
            )
            SELECT
                d.collection_country,
                d.collection_batch_id,
                d.video_id,
                d.keyword,
                d.dup_count,
                y.id,
                y.title,
                y.created_at
            FROM duplicate_groups d
            JOIN youtube_videos y
              ON y.collection_country = d.collection_country
             AND y.collection_batch_id = d.collection_batch_id
             AND y.video_id = d.video_id
             AND y.keyword = d.keyword
             AND y.category = 'HHP'
            ORDER BY
                d.dup_count DESC,
                d.collection_country,
                d.collection_batch_id,
                d.video_id,
                d.keyword,
                y.created_at
        """, (target_date, page_size, offset))

        rows = cursor.fetchall()

        dup_groups = {}
        for row in rows:
            key = (row[0], row[1], row[2], row[3])
            if key not in dup_groups:
                dup_groups[key] = {
                    'collection_country': row[0],
                    'collection_batch_id': str(row[1]) if row[1] else None,
                    'video_id': row[2],
                    'keyword': row[3],
                    'dup_count': row[4],
                    'reason': (
                        f'동일 국가·배치의 video_id+keyword가 '
                        f'{row[4]}건 수집됨'
                    ),
                    'records': []
                }
            # 제목 50자 제한
            title = row[6][:50] + '...' if row[6] and len(row[6]) > 50 else row[6]
            dup_groups[key]['records'].append({
                'id': row[5],
                'title': title,
                'created_at': str(row[7]) if row[7] else None
            })

        duplicates = list(dup_groups.values())

    elif table == 'market_trend':
        select_cols = {'group': ['keyword', 'dup_count', 'reason'], 'record': ['id', 'total_article_number', 'created_at']}
        cursor.execute("""
            SELECT COUNT(*) FROM (
                SELECT keyword
                FROM market_trend
                WHERE DATE(crawl_at_local_time) = %s
                GROUP BY keyword
                HAVING COUNT(*) > 1
            ) sub
        """, (target_date,))
        total_groups = cursor.fetchone()[0]

        # Market Trend 중복: 같은 날짜에 keyword 중복
        cursor.execute("""
            WITH duplicate_groups AS (
                SELECT keyword, COUNT(*) as dup_count
                FROM market_trend
                WHERE DATE(crawl_at_local_time) = %s
                GROUP BY keyword
                HAVING COUNT(*) > 1
                ORDER BY COUNT(*) DESC, keyword
                LIMIT %s OFFSET %s
            )
            SELECT d.keyword, d.dup_count,
                   m.id, m.total_article_number, m.crawl_at_local_time
            FROM duplicate_groups d
            JOIN market_trend m ON m.keyword = d.keyword
                AND DATE(m.crawl_at_local_time) = %s
            ORDER BY d.dup_count DESC, d.keyword, m.crawl_at_local_time
        """, (target_date, page_size, offset, target_date))

        rows = cursor.fetchall()

        dup_groups = {}
        for row in rows:
            key = row[0]  # keyword
            if key not in dup_groups:
                dup_groups[key] = {
                    'keyword': row[0],
                    'dup_count': row[1],
                    'reason': f'동일 keyword가 {row[1]}건 수집됨',
                    'records': []
                }
            dup_groups[key]['records'].append({
                'id': row[2],
                'total_article_number': row[3],
                'created_at': str(row[4]) if row[4] else None
            })

        duplicates = list(dup_groups.values())

    elif table == 'market_product':
        select_cols = {'group': ['batch_id', 'samsung_series_name', 'comp_brand', 'comp_series_name', 'dup_count', 'reason'], 'record': ['id', 'created_at']}
        cursor.execute("""
            SELECT COUNT(*) FROM (
                SELECT batch_id, samsung_series_name, comp_brand, comp_series_name
                FROM market_comp_product
                WHERE DATE(created_at) = %s
                GROUP BY batch_id, samsung_series_name, comp_brand, comp_series_name
                HAVING COUNT(*) > 1
            ) sub
        """, (target_date,))
        total_groups = cursor.fetchone()[0]

        # Market Product 중복: batch_id + samsung_series_name + comp_brand + comp_series_name
        cursor.execute("""
            WITH duplicate_groups AS (
                SELECT batch_id, samsung_series_name, comp_brand, comp_series_name, COUNT(*) as dup_count
                FROM market_comp_product
                WHERE DATE(created_at) = %s
                GROUP BY batch_id, samsung_series_name, comp_brand, comp_series_name
                HAVING COUNT(*) > 1
                ORDER BY COUNT(*) DESC, batch_id, samsung_series_name
                LIMIT %s OFFSET %s
            )
            SELECT d.batch_id, d.samsung_series_name, d.comp_brand, d.comp_series_name, d.dup_count,
                   m.id, m.created_at
            FROM duplicate_groups d
            JOIN market_comp_product m ON m.batch_id = d.batch_id
                AND m.samsung_series_name = d.samsung_series_name
                AND m.comp_brand = d.comp_brand
                AND m.comp_series_name = d.comp_series_name
                AND DATE(m.created_at) = %s
            ORDER BY d.dup_count DESC, d.batch_id, d.samsung_series_name, m.created_at
        """, (target_date, page_size, offset, target_date))

        rows = cursor.fetchall()

        dup_groups = {}
        for row in rows:
            key = (row[0], row[1], row[2], row[3])  # batch_id, samsung_series_name, comp_brand, comp_series_name
            if key not in dup_groups:
                dup_groups[key] = {
                    'batch_id': row[0],
                    'samsung_series_name': row[1],
                    'comp_brand': row[2],
                    'comp_series_name': row[3],
                    'dup_count': row[4],
                    'reason': f'동일 조합이 {row[4]}건 수집됨',
                    'records': []
                }
            dup_groups[key]['records'].append({
                'id': row[5],
                'created_at': str(row[6]) if row[6] else None
            })

        duplicates = list(dup_groups.values())

    elif table == 'market_event':
        select_cols = {'group': ['batch_id', 'comp_brand', 'comp_sku_name', 'dup_count', 'reason'], 'record': ['id', 'created_at']}
        cursor.execute("""
            SELECT COUNT(*) FROM (
                SELECT batch_id, comp_brand, comp_sku_name
                FROM market_comp_event
                WHERE DATE(created_at) = %s
                GROUP BY batch_id, comp_brand, comp_sku_name
                HAVING COUNT(*) > 1
            ) sub
        """, (target_date,))
        total_groups = cursor.fetchone()[0]

        # Market Event 중복: batch_id + comp_brand + comp_sku_name
        cursor.execute("""
            WITH duplicate_groups AS (
                SELECT batch_id, comp_brand, comp_sku_name, COUNT(*) as dup_count
                FROM market_comp_event
                WHERE DATE(created_at) = %s
                GROUP BY batch_id, comp_brand, comp_sku_name
                HAVING COUNT(*) > 1
                ORDER BY COUNT(*) DESC, batch_id, comp_brand
                LIMIT %s OFFSET %s
            )
            SELECT d.batch_id, d.comp_brand, d.comp_sku_name, d.dup_count,
                   m.id, m.created_at
            FROM duplicate_groups d
            JOIN market_comp_event m ON m.batch_id = d.batch_id
                AND m.comp_brand = d.comp_brand
                AND m.comp_sku_name = d.comp_sku_name
                AND DATE(m.created_at) = %s
            ORDER BY d.dup_count DESC, d.batch_id, d.comp_brand, m.created_at
        """, (target_date, page_size, offset, target_date))

        rows = cursor.fetchall()

        dup_groups = {}
        for row in rows:
            key = (row[0], row[1], row[2])  # batch_id, comp_brand, comp_sku_name
            if key not in dup_groups:
                dup_groups[key] = {
                    'batch_id': row[0],
                    'comp_brand': row[1],
                    'comp_sku_name': row[2],
                    'dup_count': row[3],
                    'reason': f'동일 조합이 {row[3]}건 수집됨',
                    'records': []
                }
            dup_groups[key]['records'].append({
                'id': row[4],
                'created_at': str(row[5]) if row[5] else None
            })

        duplicates = list(dup_groups.values())

    # 수정 가능 컬럼
    editable_cols = []
    actual_table = ''
    if table in ('tv_retail', 'hhp_retail') and retailer:
        product_line = 'tv' if table == 'tv_retail' else 'hhp'
        actual_table = 'tv_retail_com' if table == 'tv_retail' else 'hhp_retail_com'
        editable_cols = get_editable_columns(product_line, retailer)

    total_pages = (total_groups + page_size - 1) // page_size if total_groups > 0 else 0

    return {
        'date': str(target_date),
        'table': table,
        'retailer': retailer,
        'select_cols': select_cols,
        'editable_cols': editable_cols,
        'actual_table': actual_table,
        'results': {
            'duplicates': duplicates,
            'total_groups': total_groups,
            'page': page,
            'page_size': page_size,
            'total_pages': total_pages
        }
    }


def cleanup_duplicates(cursor, conn, table, ids, target_date, username):
    """
    중복 데이터 정리 — 백업 후 삭제.
    cursor/conn 을 받아 plain dict 를 반환한다.
    conn.commit() 는 이 함수 내에서 호출하지 않는다 (api 에서 처리).
    """
    import json as json_mod
    from datetime import datetime

    cfg = _DUP_TABLE_CONFIG[table]
    actual_table = cfg['actual']
    dup_keys = cfg['dup_keys'] or 'keyword_id'
    use_period = cfg.get('use_period', False)
    date_col = cfg.get('date_col', '')
    backup_table = 'monitoring_duplicate_deletes'
    sea_product_key = cfg.get('sea_product_key')
    sea_source = SEA_RETAIL_SOURCES.get(sea_product_key)

    now = datetime.now()

    # 1. 삭제 대상 전체 행 조회 (백업용)
    id_placeholders = ', '.join(['%s'] * len(ids))
    validation_where = ''
    if actual_table == 'tv_retail_com':
        validation_where = f" AND {get_tv_validation_condition('t')}"
    if sea_source:
        if not resolve_monitoring_date or not target_date:
            return {
                'success': False,
                'error': 'SEA 중복 삭제에는 검수일이 필요합니다.',
                'status': 400,
            }
        try:
            date_mapping = resolve_monitoring_date(
                target_date, 'SEA', sea_source['source_key']
            )
        except (TypeError, ValueError) as exc:
            return {
                'success': False,
                'error': f'검수일이 올바르지 않습니다: {exc}',
                'status': 400,
            }
        source_date = date_mapping['source_date']
        date_column = sea_source['date_column']
        retailers = tuple(sea_source.get('retailers', ()))
        retailer_placeholders = ', '.join(['%s'] * len(retailers))
        cursor.execute(f"""
            WITH latest_batches AS (
                SELECT DISTINCT ON (LOWER(TRIM(anchor.account_name)))
                       LOWER(TRIM(anchor.account_name)) AS retailer_key,
                       anchor.batch_id,
                       anchor.id
                FROM {actual_table} anchor
                WHERE LEFT(
                          TRIM(CAST(anchor.{date_column} AS TEXT)), 10
                      ) = %s
                  AND LOWER(TRIM(anchor.account_name)) IN (
                      {retailer_placeholders}
                  )
                  AND UPPER(TRIM(COALESCE(anchor.page_type, ''))) = 'MAIN'
                ORDER BY retailer_key, anchor.id DESC
            )
            SELECT DISTINCT ON (t.id)
                   t.id, row_to_json(t.*) AS record_data
            FROM {actual_table} t
            JOIN latest_batches latest
              ON t.batch_id IS NOT DISTINCT FROM latest.batch_id
             AND (
                 LOWER(TRIM(t.account_name)) = latest.retailer_key
                 OR t.account_name IS NULL
                 OR TRIM(CAST(t.account_name AS TEXT)) = ''
             )
            WHERE t.id IN ({id_placeholders})
              AND LEFT(TRIM(CAST(t.{date_column} AS TEXT)), 10) = %s
              AND UPPER(TRIM(COALESCE(t.page_type, '')))
                  IN ('MAIN', 'BSR')
            ORDER BY t.id
        """, (
            source_date,
            *[retailer.lower() for retailer in retailers],
            *ids,
            source_date,
        ))
    else:
        cursor.execute(
            f"SELECT id, row_to_json(t.*) as record_data "
            f"FROM {actual_table} t "
            f"WHERE id IN ({id_placeholders}){validation_where}",
            ids
        )
    rows = cursor.fetchall()

    if not rows:
        return {'success': True, 'deleted_count': 0, 'message': '해당 레코드가 존재하지 않습니다.'}

    # 2. SEA 원본 백업 + 삭제 감사 백업 + corrections 이력 저장
    if sea_source:
        fetched_ids = [row[0] for row in rows]
        fetched_placeholders = ', '.join(['%s'] * len(fetched_ids))
        cursor.execute(f"""
            INSERT INTO {sea_source['backup_table']}
            SELECT source.*
            FROM {actual_table} source
            WHERE source.id IN ({fetched_placeholders})
            ON CONFLICT DO NOTHING
        """, fetched_ids)

    for row in rows:
        record_id = row[0]
        record_data = row[1]

        if isinstance(record_data, str):
            record_json = record_data
            record_dict = json_mod.loads(record_data)
        else:
            record_json = json_mod.dumps(record_data, default=str)
            record_dict = record_data

        # 백업 (dup_group_key: 중복 판별 기준 컬럼명 + period 실제값)
        if use_period:
            date_val = str(record_dict.get(date_col, ''))
            try:
                hour = int(date_val[11:13])
                period_label = '오전' if hour < 12 else '오후'
            except (ValueError, IndexError):
                period_label = ''
            group_key_meta = dup_keys + ', period(' + period_label + ')'
        else:
            group_key_meta = dup_keys
        cursor.execute(f"""
            INSERT INTO {backup_table}
                (source_table, record_id, record_data, dup_group_key, crawl_date, deleted_by, deleted_at)
            VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s)
        """, (
            actual_table, record_id, record_json,
            group_key_meta, target_date, username, now
        ))

        # corrections 이력
        item_col_name = (
            'item' if sea_source
            else dup_keys.split(',')[0].strip() if dup_keys else None
        )
        item_value = str(record_dict.get(item_col_name, '')) if item_col_name else ''
        retailer_col = cfg.get('retailer_col')
        retailer_value = str(record_dict.get(retailer_col, '')) if retailer_col else ''
        cursor.execute("""
            INSERT INTO monitoring_corrections
                (layer, correction_type, column_name, table_name, record_id,
                 crawl_date, created_id, created_at, status, memo, retailer, item)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            2, 'duplicate_check', 'item', actual_table, record_id,
            target_date, username, now, 'corrected', '중복 삭제', retailer_value,
            item_value or None
        ))

    # 3. DELETE
    fetched_ids = [row[0] for row in rows]
    del_placeholders = ', '.join(['%s'] * len(fetched_ids))
    cursor.execute(f"DELETE FROM {actual_table} WHERE id IN ({del_placeholders})", fetched_ids)

    deleted_count = cursor.rowcount

    return {
        'success': True,
        'deleted_count': deleted_count,
        'backup_table': (
            sea_source['backup_table'] if sea_source else backup_table
        ),
        'audit_backup_table': backup_table,
    }


def get_duplicate_count(cursor, table_name, date_col, dup_keys, target_date, use_period=False, group_by_col=None):
    """스케줄 기반 중복 검증 쿼리 실행"""
    dup_keys_sql = ', '.join(dup_keys)
    validation_where = ''
    if table_name == 'tv_retail_com':
        validation_where = f"AND {get_tv_validation_condition()}"

    if use_period:
        period_expr = f"CASE WHEN EXTRACT(HOUR FROM {date_col}::timestamp) < 12 THEN '오전' ELSE '오후' END as period"
        if group_by_col:
            cursor.execute(f"""
                SELECT {group_by_col}, COUNT(*) as dup_groups FROM (
                    SELECT {dup_keys_sql}, {period_expr}
                    FROM {table_name}
                    WHERE DATE({date_col}::timestamp) = %s
                    {validation_where}
                    GROUP BY {dup_keys_sql}, period
                    HAVING COUNT(*) > 1
                ) sub
                GROUP BY {group_by_col}
                ORDER BY {group_by_col}
            """, (target_date,))
            return {row[0]: row[1] for row in cursor.fetchall()}
        else:
            cursor.execute(f"""
                SELECT COUNT(*) FROM (
                    SELECT {dup_keys_sql}, {period_expr}
                    FROM {table_name}
                    WHERE DATE({date_col}::timestamp) = %s
                    {validation_where}
                    GROUP BY {dup_keys_sql}, period
                    HAVING COUNT(*) > 1
                ) sub
            """, (target_date,))
            return cursor.fetchone()[0] or 0
    else:
        cursor.execute(f"""
            SELECT COUNT(*) FROM (
                SELECT {dup_keys_sql}
                FROM {table_name}
                WHERE DATE({date_col}) = %s
                {validation_where}
                GROUP BY {dup_keys_sql}
                HAVING COUNT(*) > 1
            ) sub
        """, (target_date,))
        return cursor.fetchone()[0] or 0


def _get_youtube_video_duplicate_stats(cursor, target_date):
    """신규 국가·배치에 연결된 HHP 영상만 대상으로 중복 통계를 구한다."""
    scope_sql = """
        FROM youtube_videos v
        WHERE v.category = 'HHP'
          AND EXISTS (
              SELECT 1
              FROM youtube_country_collection_runs r
              WHERE r.collection_date = %s
                AND r.collection_country = v.collection_country
                AND r.batch_id = v.collection_batch_id
          )
    """
    params = (target_date,)

    cursor.execute(f"SELECT COUNT(*) {scope_sql}", params)
    total_records = cursor.fetchone()[0] or 0

    cursor.execute(f"""
        SELECT COUNT(*) FROM (
            SELECT {', '.join('v.' + key for key in _YOUTUBE_VIDEO_DUP_KEYS)}
            {scope_sql}
            GROUP BY {', '.join('v.' + key for key in _YOUTUBE_VIDEO_DUP_KEYS)}
            HAVING COUNT(*) > 1
        ) duplicate_groups
    """, params)
    duplicate_groups = cursor.fetchone()[0] or 0

    return {
        'total_records': total_records,
        'duplicate_groups': duplicate_groups,
        'duplicate_keys': list(_YOUTUBE_VIDEO_DUP_KEYS),
    }


def _get_market_duplicate_stats(
    cursor, target_date, table_name, fallback_date_col, fallback_dup_keys
):
    """Return duplicate stats without touching a stopped Market source."""
    if table_name in DISABLED_SOURCE_TABLES:
        return None

    dup_info = get_duplicate_key_columns(table_name)
    date_col = dup_info['date_column'] if dup_info else fallback_date_col
    dup_keys = dup_info['duplicate_keys'] if dup_info else fallback_dup_keys

    cursor.execute(
        f"SELECT COUNT(*) FROM {table_name} WHERE DATE({date_col}) = %s",
        (target_date,),
    )
    total_records = cursor.fetchone()[0] or 0
    duplicate_groups = get_duplicate_count(
        cursor, table_name, date_col, dup_keys, target_date
    )
    return {
        'total_records': total_records,
        'duplicate_groups': duplicate_groups,
        'duplicate_keys': dup_keys,
    }


def get_anomaly_stats(cursor, target_date, include_youtube=True):
    """중복 검증 통계 — 대시보드용"""
    total_anomaly_issues = 0
    anomaly_validation = {
        'type': 'duplicate',
        'type_name': '중복 검증',
        'type_name_en': 'Duplicate Validation',
        'description': '동일 시간대 동일 상품 중복 수집 탐지',
        'icon': '🔄',
        'tables': []
    }

    # TV Retail 중복 검증
    tv_dup_keys = get_retail_duplicate_keys('tv')
    if not tv_dup_keys:
        tv_dup_keys = ['item', 'account_name']
    tv_date_col = 'crawl_datetime'

    cursor.execute(
        f"SELECT COUNT(*) FROM tv_retail_com "
        f"WHERE DATE({tv_date_col}::timestamp) = %s "
        f"AND {get_tv_validation_condition()}",
        (target_date,),
    )
    tv_total_records = cursor.fetchone()[0] or 0

    retailer_list = get_retailer_list()
    tv_dup_dict = get_duplicate_count(cursor, 'tv_retail_com', tv_date_col, tv_dup_keys, target_date, use_period=True, group_by_col='account_name')

    # 정상처리 차감
    tv_dup_normal = {}
    try:
        cursor.execute("""
            SELECT retailer, COUNT(*) FROM monitoring_corrections
            WHERE table_name = 'tv_retail_com' AND crawl_date = %s
              AND correction_type = 'duplicate_check' AND status = 'normal'
            GROUP BY retailer
        """, (str(target_date),))
        for nr in cursor.fetchall():
            tv_dup_normal[nr[0]] = nr[1]
    except Exception:
        pass

    tv_dup_retailers = []
    tv_dup_total = 0
    for retailer_name in retailer_list:
        dup_count = max(0, tv_dup_dict.get(retailer_name, 0) - tv_dup_normal.get(retailer_name, 0))
        tv_dup_retailers.append({
            'retailer': retailer_name,
            'duplicate_groups': dup_count,
            'status': get_status(dup_count)
        })
        tv_dup_total += dup_count

    # TV Retail 가격 이상
    cursor.execute(f"""
        SELECT COUNT(*) FROM tv_retail_com
        WHERE DATE(crawl_datetime::timestamp) = %s
        AND {get_tv_validation_condition()}
        AND final_sku_price ~ '^\\$[\\d,]+\\.?\\d*$'
        AND (
            CAST(REPLACE(REPLACE(final_sku_price, '$', ''), ',', '') AS DECIMAL) < 0
            OR CAST(REPLACE(REPLACE(final_sku_price, '$', ''), ',', '') AS DECIMAL) > 50000
        )
    """, (target_date,))
    tv_price_anomaly = cursor.fetchone()[0] or 0

    anomaly_validation['tables'].append({
        'table': 'tv_retail',
        'table_name': 'TV Retail',
        'total_records': tv_total_records,
        'total_issues': tv_dup_total,
        'duplicate_groups': tv_dup_total,
        'duplicate_keys': tv_dup_keys,
        'status': get_status(tv_dup_total),
        'retailers': tv_dup_retailers
    })
    total_anomaly_issues += tv_dup_total

    # HHP Retail 중복 검증
    hhp_dup_keys = get_retail_duplicate_keys('hhp')
    if not hhp_dup_keys:
        hhp_dup_keys = ['item', 'account_name']
    hhp_date_col = 'crawl_strdatetime'

    hhp_total_records = 0

    hhp_dup_dict = {}

    hhp_dup_normal = {}
    try:
        if False:
            cursor.execute("""
            SELECT retailer, COUNT(*) FROM monitoring_corrections
            WHERE table_name = 'hhp_retail_com' AND crawl_date = %s
              AND correction_type = 'duplicate_check' AND status = 'normal'
            GROUP BY retailer
            """, (str(target_date),))
            for nr in cursor.fetchall():
                hhp_dup_normal[nr[0]] = nr[1]
    except Exception:
        pass

    hhp_dup_retailers = []
    hhp_dup_total = 0
    for retailer_name in retailer_list:
        dup_count = max(0, hhp_dup_dict.get(retailer_name, 0) - hhp_dup_normal.get(retailer_name, 0))
        hhp_dup_retailers.append({
            'retailer': retailer_name,
            'duplicate_groups': dup_count,
            'status': get_status(dup_count)
        })
        hhp_dup_total += dup_count

    anomaly_validation['tables'].append({
        'table': 'hhp_retail',
        'table_name': 'HHP Retail',
        'total_records': hhp_total_records,
        'total_issues': hhp_dup_total,
        'duplicate_groups': hhp_dup_total,
        'duplicate_keys': hhp_dup_keys,
        'status': get_status(hhp_dup_total),
        'retailers': hhp_dup_retailers
    })
    total_anomaly_issues += hhp_dup_total
    anomaly_validation['tables'] = [t for t in anomaly_validation['tables'] if t.get('table') != 'hhp_retail']
    total_anomaly_issues -= hhp_dup_total

    if include_youtube:
        # 타 국가·타 배치는 서로 다른 정상 수집이므로 동일 범위만 비교한다.
        youtube_dup_stats = _get_youtube_video_duplicate_stats(
            cursor, target_date
        )
        ytv_dup_keys = youtube_dup_stats['duplicate_keys']
        ytv_total_records = youtube_dup_stats['total_records']
        ytv_dup_total = youtube_dup_stats['duplicate_groups']

        yt_total_issues = ytv_dup_total
        anomaly_validation['tables'].append({
            'table': 'youtube',
            'table_name': 'YouTube',
            'total_records': ytv_total_records,
            'total_issues': yt_total_issues,
            'duplicate_groups': yt_total_issues,
            'status': get_status(yt_total_issues),
            'retailers': [
                {
                    'retailer': 'Videos',
                    'total': ytv_total_records,
                    'duplicate_groups': ytv_dup_total,
                    'duplicate_keys': ytv_dup_keys,
                    'status': get_status(ytv_dup_total)
                }
            ]
        })
        total_anomaly_issues += yt_total_issues

    # Market 중복
    # 중단된 Market 원본은 통계에서도 조회하지 않는다.
    market_sources = (
        ('market_trend', 'Trend', 'crawl_at_local_time', ['keyword']),
        (
            'market_comp_product', 'Product', 'created_at',
            ['batch_id', 'samsung_series_name', 'comp_brand', 'comp_series_name'],
        ),
        (
            'market_comp_event', 'Event', 'created_at',
            ['batch_id', 'comp_brand', 'comp_sku_name'],
        ),
    )
    market_retailers = []
    market_total_records = 0
    market_total_dup = 0
    for table_name, display_name, date_col, duplicate_keys in market_sources:
        source_stats = _get_market_duplicate_stats(
            cursor, target_date, table_name, date_col, duplicate_keys
        )
        if source_stats is None:
            continue
        market_total_records += source_stats['total_records']
        market_total_dup += source_stats['duplicate_groups']
        market_retailers.append({
            'retailer': display_name,
            'total': source_stats['total_records'],
            'duplicate_groups': source_stats['duplicate_groups'],
            'duplicate_keys': source_stats['duplicate_keys'],
            'status': get_status(source_stats['duplicate_groups'])
        })

    if market_retailers:
        anomaly_validation['tables'].append({
            'table': 'market',
            'table_name': 'Market',
            'total_records': market_total_records,
            'total_issues': market_total_dup,
            'duplicate_groups': market_total_dup,
            'status': get_status(market_total_dup),
            'retailers': market_retailers
        })
        total_anomaly_issues += market_total_dup

    total_anomaly_issues += _append_sea_anomaly_stats(
        cursor, target_date, anomaly_validation
    )

    total_anomaly_issues += _append_tse_anomaly_stats(
        cursor, target_date, anomaly_validation
    )

    anomaly_validation['total_issues'] = total_anomaly_issues
    anomaly_validation['status'] = get_status(total_anomaly_issues)

    return anomaly_validation, total_anomaly_issues
