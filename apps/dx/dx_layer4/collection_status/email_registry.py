"""Allow-listed source metadata for the Layer 4 email report.

Collection columns normally do not live in application code.  Each source's
``product_line`` selects the active rows in
``public.monitoring_retail_columns`` at request time.  The one exception is an
explicit email-only allow-list for fields which remain excluded from shared
Layer 1-3 Missing checks (``skip_missing_check = TRUE``).
"""

import re


_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")
_TABLE_IDENTIFIER = re.compile(
    r"^(?:[a-z_][a-z0-9_]*\.)?[a-z_][a-z0-9_]*$"
)


def _retailer(name, *aliases, exclude_redirect=False,
              include_unassigned=None, unsupported_columns=(),
              conditional_columns=(), optional_if_unconfigured=False,
              email_redirect_metric=False,
              email_include_skipped_columns=()):
    retailer = {
        'name': name,
        'aliases': tuple(dict.fromkeys((name,) + aliases)),
        'exclude_redirect': exclude_redirect,
        'unsupported_columns': tuple(unsupported_columns),
        'conditional_columns': tuple(conditional_columns),
        'optional_if_unconfigured': bool(optional_if_unconfigured),
        'email_redirect_metric': bool(email_redirect_metric),
        'email_include_skipped_columns': tuple(
            email_include_skipped_columns
        ),
    }
    if include_unassigned is not None:
        retailer['include_unassigned'] = bool(include_unassigned)
    return retailer


def _source(key, country, product, table_name, date_column, date_mode,
            retailers, *, product_line=None, has_page_type=True,
            include_unassigned=False, latest_batch=True,
            collection_scope='main', special_rules=None,
            business_timezone=None, email_include_skipped_columns=()):
    return {
        'key': key,
        'product_line': product_line or key,
        'country': country,
        'product': product,
        'label': f'{country} {product} 수집 데이터',
        'table_name': table_name,
        'date_column': date_column,
        'date_mode': date_mode,
        'id_column': 'id',
        'batch_column': 'batch_id',
        'account_column': 'account_name',
        'has_page_type': has_page_type,
        'include_unassigned': include_unassigned,
        'latest_batch': latest_batch,
        'collection_scope': collection_scope,
        'special_rules': special_rules,
        'business_timezone': business_timezone,
        'email_include_skipped_columns': tuple(
            email_include_skipped_columns
        ),
        'retailers': tuple(retailers),
    }


_SEA_TV_RETAILERS = (
    _retailer(
        'Amazon', exclude_redirect=True,
        email_include_skipped_columns=('sku_popularity',),
    ),
    _retailer(
        'Bestbuy', 'BestBuy',
        email_include_skipped_columns=(
            'promotion_position', 'promotion_type', 'trend_rank',
        ),
    ),
    _retailer(
        'Walmart',
        email_include_skipped_columns=(
            'sku_popularity', 'number_of_ppl_purchased_yesterday',
            'number_of_ppl_added_to_carts',
        ),
    ),
)
_SEA_APPLIANCE_RETAILERS = (
    _retailer('Bestbuy', 'BestBuy'),
    _retailer('Lowes', "Lowe's", 'Lowe’s'),
)
_SEDA_RETAILERS = (
    _retailer('Magalu'),
    _retailer('Casas Bahia', 'CasasBahia', 'casasbahia'),
)
_SEG_THREE_RETAILERS = (
    _retailer('MediaMarkt', 'Mediamarkt'),
    _retailer('OTTO'),
    _retailer('Amazon', 'Amazon.de', email_redirect_metric=True),
)
_SEG_LDY_RETAILERS = _SEG_THREE_RETAILERS[:2]
_SIEL_RETAILERS = (
    _retailer('Amazon', email_redirect_metric=True),
    _retailer('Flipkart'),
)
def _tse_retailers(product):
    retailers = [
        _retailer('Homepro', include_unassigned=False),
        _retailer(
            'Lazada', include_unassigned=False,
            conditional_columns=('original_sku_price', 'savings'),
        ),
    ]
    if product == 'TV':
        retailers.append(_retailer(
            'PowerBuy', include_unassigned=False,
            conditional_columns=('original_sku_price', 'savings'),
        ))
    return tuple(retailers)


_TSE_EMAIL_SKIPPED_ALLOWLIST = {
    'TV': ('original_sku_price', 'savings'),
    'REF': (
        'original_sku_price', 'savings', 'ref_refrigerator_type',
    ),
    'LDY': (
        'original_sku_price', 'savings', 'ldy_loading_type',
    ),
}


EMAIL_REPORT_SOURCES = (
    # SEA TV keeps its established batch-date/all-row collection semantics.
    # Only the email's BSR field denominator changes to actual BSR rows.
    _source(
        'sea_tv', 'SEA', 'TV', 'public.tv_retail_com', 'batch_id', 'batch',
        _SEA_TV_RETAILERS, product_line='tv', latest_batch=False,
        collection_scope='all', special_rules='sea_tv',
    ),
    _source(
        'sea_ref', 'SEA', 'REF', 'public.ref_retail_com', 'crawl_strdatetime',
        'text', _SEA_APPLIANCE_RETAILERS,
    ),
    _source(
        'sea_ldy', 'SEA', 'LDY', 'public.ldy_retail_com', 'crawl_strdatetime',
        'text', _SEA_APPLIANCE_RETAILERS,
    ),
    *(
        _source(
            f'seda_{product.lower()}', 'SEDA', product,
            f'dx_seda.dx_seda_{product.lower()}_retail_com',
            'crawl_strdatetime', 'text', _SEDA_RETAILERS,
        )
        for product in ('TV', 'REF', 'LDY')
    ),
    *(
        _source(
            f'seg_{product.lower()}', 'SEG', product,
            f'dx_seg.dx_seg_{product.lower()}_retail_com',
            'crawl_strdatetime', 'text',
            _SEG_LDY_RETAILERS if product == 'LDY' else _SEG_THREE_RETAILERS,
        )
        for product in ('TV', 'REF', 'LDY')
    ),
    *(
        _source(
            f'siel_{product.lower()}', 'SIEL', product,
            f'dx_siel.dx_siel_{product.lower()}_retail_com',
            'crawl_datetime', 'timestamp', _SIEL_RETAILERS,
            business_timezone='Asia/Seoul',
        )
        for product in ('TV', 'REF', 'LDY')
    ),
    *(
        _source(
            f'tse_{product.lower()}', 'TSE', product,
            f'dx_tse.dx_tse_{product.lower()}_retail_com',
            'crawl_datetime', 'text', _tse_retailers(product),
            has_page_type=False, include_unassigned=False,
            collection_scope='all',
            email_include_skipped_columns=(
                _TSE_EMAIL_SKIPPED_ALLOWLIST[product]
            ),
        )
        for product in ('TV', 'REF', 'LDY')
    ),
)


def _validate_registry():
    keys = set()
    for source in EMAIL_REPORT_SOURCES:
        if source['key'] in keys:
            raise ValueError(f"Duplicate email source: {source['key']}")
        keys.add(source['key'])
        if not _TABLE_IDENTIFIER.fullmatch(source['table_name']):
            raise ValueError(f"Unsafe email table: {source['table_name']}")
        if '.' not in source['table_name']:
            raise ValueError(
                f"Email table must be schema-qualified: "
                f"{source['table_name']}"
            )
        if source['date_mode'] not in {'batch', 'text', 'timestamp'}:
            raise ValueError(f"Unsafe date mode: {source['date_mode']}")
        if source['business_timezone'] not in {None, 'Asia/Seoul'}:
            raise ValueError(
                f"Unsafe business timezone: {source['business_timezone']}"
            )
        if source['collection_scope'] not in {'all', 'main'}:
            raise ValueError(
                f"Unsafe collection scope: {source['collection_scope']}"
            )
        identifiers = (
            source['key'], source['product_line'], source['date_column'],
            source['id_column'], source['batch_column'],
            source['account_column'],
            *source['email_include_skipped_columns'],
        )
        for identifier in identifiers:
            if not _IDENTIFIER.fullmatch(identifier):
                raise ValueError(f"Unsafe email identifier: {identifier}")
        for retailer in source['retailers']:
            if not retailer['aliases']:
                raise ValueError(
                    f"Retailer aliases are required: {source['key']}"
                )
            if retailer.get('include_unassigned') not in {None, True, False}:
                raise ValueError(
                    f"Unsafe unassigned policy: {source['key']}"
                )
            if retailer.get('optional_if_unconfigured') not in {True, False}:
                raise ValueError(
                    f"Unsafe optional retailer policy: {source['key']}"
                )
            if retailer.get('email_redirect_metric') not in {True, False}:
                raise ValueError(
                    f"Unsafe email redirect policy: {source['key']}"
                )
            for identifier in (
                    *retailer.get('unsupported_columns', ()),
                    *retailer.get('conditional_columns', ()),
                    *retailer.get('email_include_skipped_columns', ())):
                if not _IDENTIFIER.fullmatch(identifier):
                    raise ValueError(
                        f"Unsafe retailer column: {source['key']}"
                    )


_validate_registry()
