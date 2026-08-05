"""Temporarily disabled monitoring sources.

The source collectors for these Market datasets stopped on 2026-08-05.
Keep the implementations in place so monitoring can be restored by removing
the relevant entries below and running the related regression tests.
"""


DISABLED_CHECK_TYPES = frozenset({
    'market_trend',
    'market_demand',
    'market_promotion',
    'market_competitor',
    'market_competitor_event',
})

DISABLED_SOURCE_TABLES = frozenset({
    'market_trend',
    'openai_forecast_results',
    'openai_retailer_promotions',
    'market_comp_product',
    'market_comp_event',
})
