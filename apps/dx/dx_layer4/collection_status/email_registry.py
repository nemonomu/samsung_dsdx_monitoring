"""Static, email-only collection source registry.

The values in this module are the reviewed collection matrices used by
Layer 4 > Collection status > Email report.  Runtime code must never read the
desktop Excel/CSV evidence files.  SQL identifiers are accepted only from
this registry and are validated when the module is imported.
"""

import re


_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")
_TABLE_IDENTIFIER = re.compile(
    r"^(?:[a-z_][a-z0-9_]*\.)?[a-z_][a-z0-9_]*$"
)


SEA_TV_COLUMNS = {
    'Amazon': (
        'item', 'screen_size', 'retailer_sku_name', 'final_sku_price',
        'detailed_review_content', 'main_rank', 'bsr_rank', 'model_year',
        'available_quantity_for_purchase', 'sku_popularity', 'discount_type',
        'summarized_review_content', 'number_of_units_purchased_past_month',
        'star_rating', 'count_of_star_ratings', 'original_sku_price',
        'calendar_week', 'crawl_datetime', 'product_url', 'page_type',
        'account_name', 'fastest_delivery',
    ),
    'Bestbuy': (
        'item', 'screen_size', 'retailer_sku_name', 'final_sku_price',
        'detailed_review_content', 'main_rank', 'bsr_rank', 'savings', 'offer',
        'pick_up_availability', 'fastest_delivery', 'delivery_availability',
        'estimated_annual_electricity_use', 'recommendation_intent',
        'promotion_type', 'model_year', 'retailer_sku_name_similar',
        'count_of_reviews', 'star_rating', 'count_of_star_ratings',
        'original_sku_price', 'calendar_week', 'crawl_datetime', 'product_url',
        'page_type', 'account_name', 'promotion_position', 'trend_rank',
    ),
    'Walmart': (
        'item', 'screen_size', 'retailer_sku_name', 'final_sku_price',
        'detailed_review_content', 'main_rank', 'bsr_rank', 'savings',
        'pick_up_availability', 'fastest_delivery', 'delivery_availability',
        'sku_status', 'inventory_status', 'number_of_ppl_purchased_yesterday',
        'number_of_ppl_added_to_carts', 'model_year',
        'available_quantity_for_purchase', 'sku_popularity', 'discount_type',
        'retailer_sku_name_similar', 'count_of_reviews', 'star_rating',
        'count_of_star_ratings', 'original_sku_price', 'calendar_week',
        'crawl_datetime', 'product_url', 'page_type', 'account_name',
    ),
}


SEA_REF_COLUMNS = {
    'Bestbuy': (
        'retailer_sku_name', 'final_sku_price', 'savings', 'offer',
        'pick_up_availability', 'delivery_availability', 'sku_status',
        'star_rating', 'count_of_reviews', 'count_of_star_ratings',
        'ref_capacity', 'ref_refrigerator_type', 'sku',
        'retailer_sku_name_similar', 'recommendation_intent',
        'detailed_review_content', 'bsr_rank',
    ),
    'Lowes': (
        'retailer_sku_name', 'final_sku_price', 'original_sku_price', 'savings',
        'star_rating', 'count_of_reviews', 'count_of_star_ratings',
        'discount_type', 'sku_popularity', 'sku_status', 'sku',
        'number_of_units_purchased_past_week', 'pick_up_availability',
        'delivery_availability', 'fastest_delivery',
        'available_quantity_for_purchase_pickup',
        'available_quantity_for_purchase_delivery',
        'available_quantity_for_purchase_fastdelivery',
        'ref_refrigerator_type', 'ref_capacity', 'recommendation_intent',
        'summarized_review_content', 'detailed_review_content',
        'retailer_sku_name_similar', 'bsr_rank',
    ),
}


SEA_LDY_COLUMNS = {
    'Bestbuy': (
        'retailer_sku_name', 'final_sku_price', 'savings', 'offer',
        'pick_up_availability', 'delivery_availability', 'sku_status',
        'star_rating', 'count_of_reviews', 'count_of_star_ratings',
        'ldy_capacity', 'ldy_loading_type', 'sku',
        'retailer_sku_name_similar', 'recommendation_intent',
        'detailed_review_content', 'bsr_rank',
    ),
    'Lowes': (
        'retailer_sku_name', 'final_sku_price', 'original_sku_price', 'savings',
        'star_rating', 'count_of_reviews', 'count_of_star_ratings',
        'discount_type', 'sku_popularity', 'sku_status', 'sku',
        'number_of_units_purchased_past_week', 'pick_up_availability',
        'delivery_availability', 'fastest_delivery',
        'available_quantity_for_purchase_pickup',
        'available_quantity_for_purchase_delivery',
        'available_quantity_for_purchase_fastdelivery', 'ldy_loading_type',
        'ldy_capacity', 'recommendation_intent', 'summarized_review_content',
        'detailed_review_content', 'retailer_sku_name_similar', 'bsr_rank',
    ),
}


SEDA_COLUMNS = {
    'TV': {
        'Magalu': (
            'retailer_sku_name', 'original_sku_price', 'final_sku_price',
            'sku_status', 'discount_type', 'delivery_availability',
            'pick_up_availability', 'sku', 'screen_size',
            'estimated_annual_electricity_use', 'model_year',
            'summarized_review_content', 'retailer_sku_name_similar',
            'star_rating', 'count_of_star_ratings', 'count_of_reviews',
            'detailed_review_content', 'bsr_rank',
        ),
        'Casas Bahia': (
            'retailer_sku_name', 'original_sku_price', 'savings',
            'final_sku_price', 'discount_type', 'sku_status',
            'pick_up_availability', 'delivery_availability', 'screen_size',
            'estimated_annual_electricity_use', 'retailer_sku_name_similar',
            'star_rating', 'count_of_star_ratings', 'count_of_reviews',
            'recommendation_intent', 'summarized_review_content',
            'detailed_review_content', 'bsr_rank',
        ),
    },
    'REF': {
        'Magalu': (
            'retailer_sku_name', 'original_sku_price', 'final_sku_price',
            'discount_type', 'sku_status', 'delivery_availability', 'sku',
            'ref_refrigerator_type', 'ref_capacity',
            'summarized_review_content', 'retailer_sku_name_similar',
            'star_rating', 'count_of_star_ratings', 'count_of_reviews',
            'detailed_review_content', 'bsr_rank',
        ),
        'Casas Bahia': (
            'retailer_sku_name', 'original_sku_price', 'savings',
            'final_sku_price', 'sku_status', 'discount_type',
            'sku_short_version', 'pick_up_availability',
            'delivery_availability', 'ref_refrigerator_type', 'ref_capacity',
            'retailer_sku_name_similar', 'star_rating',
            'count_of_star_ratings', 'count_of_reviews',
            'recommendation_intent', 'summarized_review_content',
            'detailed_review_content', 'bsr_rank',
        ),
    },
    'LDY': {
        'Magalu': (
            'retailer_sku_name', 'original_sku_price', 'final_sku_price',
            'sku_status', 'discount_type', 'delivery_availability', 'sku',
            'ldy_capacity', 'ldy_loading_type', 'summarized_review_content',
            'retailer_sku_name_similar', 'star_rating',
            'count_of_star_ratings', 'count_of_reviews',
            'detailed_review_content', 'bsr_rank',
        ),
        'Casas Bahia': (
            'retailer_sku_name', 'original_sku_price', 'savings',
            'final_sku_price', 'sku_status', 'discount_type',
            'sku_short_version', 'pick_up_availability',
            'delivery_availability', 'ldy_capacity', 'ldy_loading_type',
            'ldy_color', 'retailer_sku_name_similar', 'star_rating',
            'count_of_star_ratings', 'count_of_reviews',
            'recommendation_intent', 'summarized_review_content',
            'detailed_review_content', 'bsr_rank', 'sku',
        ),
    },
}


SEG_COLUMNS = {
    'TV': {
        'MediaMarkt': (
            'retailer_sku_name', 'savings', 'original_sku_price',
            'final_sku_price', 'sku_status', 'discount_type',
            'delivery_availability', 'pick_up_availability',
            'retailer_sku_name_similar', 'screen_size', 'sku',
            'estimated_annual_electricity_use', 'model_year', 'star_rating',
            'count_of_star_ratings', 'count_of_reviews',
            'summarized_review_content', 'detailed_review_content', 'bsr_rank',
        ),
        'OTTO': (
            'retailer_sku_name', 'final_sku_price', 'original_sku_price',
            'savings', 'sku_popularity', 'sku_status', 'discount_type',
            'delivery_availability', 'sku', 'screen_size',
            'estimated_annual_electricity_use', 'retailer_sku_name_similar',
            'star_rating', 'count_of_star_ratings', 'count_of_reviews',
            'recommendation_intent', 'summarized_review_content',
            'detailed_review_content', 'bsr_rank',
        ),
        'Amazon': (
            'retailer_sku_name', 'final_sku_price', 'original_sku_price',
            'discount_type', 'sku_popularity',
            'number_of_units_purchased_past_month', 'sku_status',
            'available_quantity_for_purchase', 'delivery_availability',
            'fastest_delivery', 'inventory_status', 'screen_size', 'model_year',
            'sku', 'estimated_annual_electricity_use',
            'retailer_sku_name_similar', 'star_rating',
            'count_of_star_ratings', 'summarized_review_content',
            'detailed_review_content', 'bsr_rank',
        ),
    },
    'REF': {
        'MediaMarkt': (
            'retailer_sku_name', 'savings', 'original_sku_price',
            'final_sku_price', 'sku_status', 'discount_type',
            'delivery_availability', 'pick_up_availability',
            'retailer_sku_name_similar', 'ref_refrigerator_type',
            'ref_capacity', 'sku', 'star_rating', 'count_of_star_ratings',
            'count_of_reviews', 'summarized_review_content',
            'detailed_review_content', 'bsr_rank',
        ),
        'OTTO': (
            'retailer_sku_name', 'final_sku_price', 'original_sku_price',
            'savings', 'sku_popularity', 'sku_status', 'discount_type',
            'delivery_availability', 'ref_refrigerator_type', 'sku',
            'ref_capacity', 'retailer_sku_name_similar', 'star_rating',
            'count_of_star_ratings', 'count_of_reviews',
            'recommendation_intent', 'summarized_review_content',
            'detailed_review_content', 'bsr_rank',
        ),
        'Amazon': (
            'retailer_sku_name', 'final_sku_price', 'original_sku_price',
            'discount_type', 'sku_popularity',
            'number_of_units_purchased_past_month', 'sku_status',
            'available_quantity_for_purchase', 'delivery_availability',
            'fastest_delivery', 'inventory_status', 'ref_refrigerator_type',
            'ref_capacity', 'sku', 'retailer_sku_name_similar', 'star_rating',
            'count_of_star_ratings', 'summarized_review_content',
            'detailed_review_content', 'bsr_rank',
        ),
    },
    'LDY': {
        'MediaMarkt': (
            'retailer_sku_name', 'savings', 'original_sku_price',
            'final_sku_price', 'sku_status', 'discount_type',
            'delivery_availability', 'pick_up_availability',
            'retailer_sku_name_similar', 'ldy_capacity', 'ldy_loading_type',
            'sku', 'star_rating', 'count_of_star_ratings', 'count_of_reviews',
            'summarized_review_content', 'detailed_review_content', 'bsr_rank',
        ),
        'OTTO': (
            'retailer_sku_name', 'final_sku_price', 'original_sku_price',
            'savings', 'sku_popularity', 'sku_status', 'discount_type',
            'delivery_availability', 'ldy_loading_type', 'sku', 'ldy_capacity',
            'retailer_sku_name_similar', 'star_rating',
            'count_of_star_ratings', 'count_of_reviews',
            'recommendation_intent', 'summarized_review_content',
            'detailed_review_content', 'bsr_rank',
        ),
    },
}


# SIEL has no separate development workbook.  This matrix is intentionally
# kept in the same static registry and is populated from the reviewed CSV
# collection evidence (not read at runtime).
SIEL_COLUMNS = {
    'TV': {
        'Amazon': (
            'sku', 'retailer_sku_name', 'product_url', 'star_rating',
            'count_of_star_ratings', 'detailed_review_content',
            'retailer_sku_name_similar', 'final_sku_price',
            'original_sku_price', 'discount_type', 'delivery_availability',
            'sku_popularity', 'sku_status', 'screen_size', 'model_year',
            'estimated_annual_electricity_use', 'summarized_review_content',
            'fastest_delivery', 'inventory_status',
            'number_of_units_purchased_past_month',
        ),
        'Flipkart': (
            'sku', 'retailer_sku_name', 'product_url', 'star_rating',
            'count_of_star_ratings', 'count_of_reviews',
            'detailed_review_content', 'final_sku_price', 'original_sku_price',
            'savings', 'discount_type', 'delivery_availability',
            'available_quantity_for_purchase', 'sku_popularity', 'sku_status',
            'screen_size', 'model_year', 'estimated_annual_electricity_use',
        ),
    },
    'REF': {
        'Amazon': (
            'sku', 'retailer_sku_name', 'product_url', 'star_rating',
            'count_of_star_ratings', 'detailed_review_content',
            'retailer_sku_name_similar', 'final_sku_price',
            'original_sku_price', 'discount_type', 'delivery_availability',
            'sku_popularity', 'sku_status', 'ref_refrigerator_type',
            'ref_capacity', 'summarized_review_content', 'fastest_delivery',
            'inventory_status', 'sku_assurance',
            'number_of_units_purchased_past_month',
        ),
        'Flipkart': (
            'sku', 'retailer_sku_name', 'product_url', 'star_rating',
            'count_of_star_ratings', 'count_of_reviews',
            'detailed_review_content', 'final_sku_price', 'original_sku_price',
            'savings', 'discount_type', 'delivery_availability',
            'available_quantity_for_purchase', 'sku_popularity', 'sku_status',
            'ref_refrigerator_type', 'ref_capacity',
        ),
    },
    'LDY': {
        'Amazon': (
            'sku', 'retailer_sku_name', 'product_url', 'star_rating',
            'count_of_star_ratings', 'detailed_review_content',
            'retailer_sku_name_similar', 'final_sku_price',
            'original_sku_price', 'discount_type', 'delivery_availability',
            'sku_popularity', 'sku_status', 'ldy_loading_type', 'ldy_capacity',
            'summarized_review_content', 'fastest_delivery', 'inventory_status',
            'sku_assurance', 'number_of_units_purchased_past_month',
        ),
        'Flipkart': (
            'sku', 'retailer_sku_name', 'product_url', 'star_rating',
            'count_of_star_ratings', 'count_of_reviews',
            'detailed_review_content', 'final_sku_price', 'original_sku_price',
            'savings', 'discount_type', 'delivery_availability',
            'available_quantity_for_purchase', 'sku_popularity', 'sku_status',
            'ldy_loading_type', 'ldy_capacity',
        ),
    },
}


TSE_COLUMNS = {
    'TV': (
        'country', 'account_name', 'item', 'sku', 'product_url',
        'retailer_sku_name', 'count_of_reviews', 'star_rating',
        'count_of_star_ratings', 'final_sku_price', 'screen_size',
    ),
    'REF': (
        'country', 'account_name', 'item', 'sku', 'product_url',
        'retailer_sku_name', 'count_of_reviews', 'star_rating',
        'count_of_star_ratings', 'final_sku_price', 'ref_capacity',
    ),
    'LDY': (
        'country', 'account_name', 'item', 'sku', 'product_url',
        'retailer_sku_name', 'count_of_reviews', 'star_rating',
        'count_of_star_ratings', 'final_sku_price', 'ldy_capacity',
    ),
}


def _retailers(column_map, aliases=None, *, exclude_redirect=()):
    aliases = aliases or {}
    exclude_redirect = set(exclude_redirect)
    return tuple({
        'name': name,
        'aliases': tuple(aliases.get(name, (name,))),
        'columns': tuple(columns),
        'expected_count': 300,
        'exclude_redirect': name in exclude_redirect,
    } for name, columns in column_map.items())


def _source(key, country, product, table_name, date_column, date_mode,
            retailers):
    return {
        'key': key,
        'country': country,
        'product': product,
        'label': f'{country} {product} 수집 데이터',
        'table_name': table_name,
        'date_column': date_column,
        'date_mode': date_mode,
        'id_column': 'id',
        'batch_column': 'batch_id',
        'account_column': 'account_name',
        'has_page_type': country != 'TSE',
        'include_unassigned': country == 'TSE',
        'retailers': retailers,
    }


EMAIL_REPORT_SOURCES = (
    _source(
        'sea_tv', 'SEA', 'TV', 'tv_retail_com', 'crawl_datetime',
        'timestamp', _retailers(SEA_TV_COLUMNS, exclude_redirect=('Amazon',)),
    ),
    _source(
        'sea_ref', 'SEA', 'REF', 'ref_retail_com', 'crawl_strdatetime',
        'text', _retailers(
            SEA_REF_COLUMNS,
            aliases={
                'Bestbuy': ('Bestbuy', 'BestBuy'),
                'Lowes': ('Lowes', "Lowe's", 'Lowe’s'),
            },
        ),
    ),
    _source(
        'sea_ldy', 'SEA', 'LDY', 'ldy_retail_com', 'crawl_strdatetime',
        'text', _retailers(
            SEA_LDY_COLUMNS,
            aliases={
                'Bestbuy': ('Bestbuy', 'BestBuy'),
                'Lowes': ('Lowes', "Lowe's", 'Lowe’s'),
            },
        ),
    ),
    *(
        _source(
            f'seda_{product.lower()}', 'SEDA', product,
            f'dx_seda.dx_seda_{product.lower()}_retail_com',
            'crawl_strdatetime', 'text', _retailers(
                SEDA_COLUMNS[product],
                aliases={
                    'Casas Bahia': ('Casas Bahia', 'CasasBahia', 'casasbahia'),
                },
            ),
        )
        for product in ('TV', 'REF', 'LDY')
    ),
    *(
        _source(
            f'seg_{product.lower()}', 'SEG', product,
            f'dx_seg.dx_seg_{product.lower()}_retail_com',
            'crawl_strdatetime', 'text', _retailers(
                SEG_COLUMNS[product],
                aliases={
                    'MediaMarkt': ('MediaMarkt', 'Mediamarkt'),
                    'Amazon': ('Amazon', 'Amazon.de'),
                },
            ),
        )
        for product in ('TV', 'REF', 'LDY')
    ),
    *(
        _source(
            f'siel_{product.lower()}', 'SIEL', product,
            f'dx_siel.dx_siel_{product.lower()}_retail_com',
            'crawl_datetime', 'timestamp', _retailers(SIEL_COLUMNS[product]),
        )
        for product in ('TV', 'REF', 'LDY')
    ),
    *(
        _source(
            f'tse_{product.lower()}', 'TSE', product,
            f'dx_tse.dx_tse_{product.lower()}_retail_com',
            'crawl_datetime', 'text', _retailers({'Homepro': TSE_COLUMNS[product]}),
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
        if source['date_mode'] not in {'text', 'timestamp'}:
            raise ValueError(f"Unsafe date mode: {source['date_mode']}")
        identifiers = (
            source['date_column'], source['id_column'], source['batch_column'],
            source['account_column'],
        )
        for retailer in source['retailers']:
            identifiers += retailer['columns']
            if not retailer['aliases']:
                raise ValueError(f"Retailer aliases are required: {source['key']}")
        for identifier in identifiers:
            if not _IDENTIFIER.fullmatch(identifier):
                raise ValueError(f"Unsafe email identifier: {identifier}")


_validate_registry()
