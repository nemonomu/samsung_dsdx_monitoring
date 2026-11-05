"""Fields intentionally outside format validation (raw collection is unchanged)."""


def excluded_format_retailers(table_name, column_name):
    if table_name == 'tv_retail_com' and column_name == 'summarized_review_content':
        return ('amazon',)
    return ()


def is_format_excluded(table_name, column_name, retailer):
    return str(retailer or '').strip().lower() in excluded_format_retailers(
        table_name, column_name,
    )
