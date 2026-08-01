"""Shared SQL scope for TV Retail validation queries."""

import re


TV_RETAIL_TABLE = 'tv_retail_com'
_SAFE_ALIAS = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def get_tv_validation_condition(alias=None):
    """Exclude Amazon redirect rows while keeping FALSE and NULL rows."""
    if alias:
        if not _SAFE_ALIAS.match(alias):
            raise ValueError('Invalid SQL alias')
        prefix = f'{alias}.'
    else:
        prefix = ''
    return (
        f"NOT ({prefix}account_name = 'Amazon' "
        f"AND {prefix}redirect IS TRUE)"
    )


def apply_tv_validation_scope(query, table_name):
    """Shadow tv_retail_com with a validation-only CTE.

    This works for both plain SELECT statements and existing WITH queries,
    including rules that read the TV table more than once.
    """
    if table_name != TV_RETAIL_TABLE:
        return query

    leading_length = len(query) - len(query.lstrip())
    leading = query[:leading_length]
    body = query[leading_length:]
    scope_cte = (
        f"{TV_RETAIL_TABLE} AS ("
        f"SELECT * FROM public.{TV_RETAIL_TABLE} "
        f"WHERE {get_tv_validation_condition()}"
        f")"
    )

    if re.match(r'^WITH\b', body, flags=re.IGNORECASE):
        body = re.sub(
            r'^WITH\b', f'WITH {scope_cte},', body,
            count=1, flags=re.IGNORECASE,
        )
        return leading + body

    return f'{leading}WITH {scope_cte}\n{body}'
