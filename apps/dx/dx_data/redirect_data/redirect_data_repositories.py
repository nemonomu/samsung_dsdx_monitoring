"""Read-only database queries for Amazon redirect rows."""


_BATCH_DATE_EXPR = "substring(COALESCE(batch_id, '') from '([0-9]{8})')"


def get_redirect_count_db(cursor, batch_date):
    cursor.execute(f"""
        SELECT COUNT(*)
        FROM tv_retail_com
        WHERE account_name = 'Amazon'
          AND redirect IS TRUE
          AND {_BATCH_DATE_EXPR} = %s
    """, (batch_date,))
    row = cursor.fetchone()
    return (row[0] or 0) if row else 0


def get_redirect_page_db(cursor, columns, batch_date, page_size, offset):
    select_columns = ', '.join(f'"{column}"' for column in columns)
    cursor.execute(f"""
        SELECT {select_columns}
        FROM tv_retail_com
        WHERE account_name = 'Amazon'
          AND redirect IS TRUE
          AND {_BATCH_DATE_EXPR} = %s
        ORDER BY id DESC
        LIMIT %s OFFSET %s
    """, (batch_date, page_size, offset))
    return [dict(zip(columns, row)) for row in cursor.fetchall()]
