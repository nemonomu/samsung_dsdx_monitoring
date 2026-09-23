"""Shared price-field policy for retail validation detail editing."""

PRICE_COLUMNS = (
    'original_sku_price',
    'final_sku_price',
    'savings',
)
PRICE_EDITABLE_COLUMNS = frozenset(PRICE_COLUMNS)
