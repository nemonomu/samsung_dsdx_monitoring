"""Read-only database queries for allow-listed Amazon redirect sources."""


_ALLOWED_TABLES = frozenset({
    'public.tv_retail_com',
    'dx_siel.dx_siel_tv_retail_com',
    'dx_siel.dx_siel_ref_retail_com',
    'dx_siel.dx_siel_ldy_retail_com',
})


def _source_scope(source):
    table_name = source['table_name']
    if table_name not in _ALLOWED_TABLES:
        raise ValueError(f'허용되지 않은 redirect 조회 테이블: {table_name}')

    if source['date_mode'] == 'batch':
        date_where = (
            "substring(COALESCE(CAST(source.batch_id AS TEXT), '') "
            "from '([0-9]{8})') = %s"
        )
    elif source['date_mode'] == 'timestamp_kst':
        date_where = (
            "source.crawl_datetime >= "
            "(%s::date::timestamp AT TIME ZONE 'Asia/Seoul') "
            "AND source.crawl_datetime < "
            "((%s::date + 1)::timestamp AT TIME ZONE 'Asia/Seoul')"
        )
    else:
        raise ValueError(f"허용되지 않은 redirect 날짜 형식: {source['date_mode']}")

    return table_name, date_where


def _date_params(source, target_date):
    date_text = str(target_date)[:10]
    if source['date_mode'] == 'batch':
        return [date_text.replace('-', '')]
    return [date_text, date_text]


def get_redirect_count_db(cursor, source, target_date):
    table_name, date_where = _source_scope(source)
    cursor.execute(f"""
        SELECT COUNT(*)
        FROM {table_name} source
        WHERE LOWER(BTRIM(CAST(source.account_name AS TEXT))) = 'amazon'
          AND source.redirect IS TRUE
          AND {date_where}
    """, _date_params(source, target_date))
    row = cursor.fetchone()
    return (row[0] or 0) if row else 0


def get_redirect_page_db(cursor, source, columns, target_date, page_size, offset):
    table_name, date_where = _source_scope(source)
    select_columns = ', '.join(f'source."{column}"' for column in columns)
    params = [*_date_params(source, target_date), page_size, offset]
    cursor.execute(f"""
        SELECT {select_columns}
        FROM {table_name} source
        WHERE LOWER(BTRIM(CAST(source.account_name AS TEXT))) = 'amazon'
          AND source.redirect IS TRUE
          AND {date_where}
        ORDER BY source.id DESC
        LIMIT %s OFFSET %s
    """, params)
    return [dict(zip(columns, row)) for row in cursor.fetchall()]
