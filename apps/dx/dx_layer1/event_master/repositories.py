"""Read final Prompt 2 results across all batches on the scheduled execution date."""


def country_counts(cursor, execution_date, end_date):
    cursor.execute('''
        SELECT country, country_code, COUNT(*), MAX(execution_date)
        FROM llm_event_master.openai_event_master
        WHERE execution_date BETWEEN %s AND %s
        GROUP BY country, country_code
        ORDER BY country, country_code
    ''', (execution_date, end_date))
    return cursor.fetchall()
