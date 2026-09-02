"""SIEL retail monitoring constants and identifier allowlists."""

from datetime import time


SIEL_CHECK_TYPE = 'siel_retail'
SIEL_COUNTRY = 'SIEL'
SIEL_EXPECTED_COUNT = 300
SIEL_OK_THRESHOLD = 200
SIEL_COLLECTION_END = time(9, 0)
SIEL_BUSINESS_TIMEZONE = 'Asia/Seoul'
SIEL_RETAILERS = ('Amazon', 'Flipkart')

SIEL_SOURCE_CONFIG = {
    'siel_tv': {
        'source_key': 'siel_tv',
        'category': 'TV',
        'table_name': 'dx_siel.dx_siel_tv_retail_com',
        'backup_table_name': 'dx_siel.dx_siel_tv_retail_com_backup',
        'date_column': 'crawl_datetime',
        'retailers': SIEL_RETAILERS,
    },
    'siel_ref': {
        'source_key': 'siel_ref',
        'category': 'REF',
        'table_name': 'dx_siel.dx_siel_ref_retail_com',
        'backup_table_name': 'dx_siel.dx_siel_ref_retail_com_backup',
        'date_column': 'crawl_datetime',
        'retailers': SIEL_RETAILERS,
    },
    'siel_ldy': {
        'source_key': 'siel_ldy',
        'category': 'LDY',
        'table_name': 'dx_siel.dx_siel_ldy_retail_com',
        'backup_table_name': 'dx_siel.dx_siel_ldy_retail_com_backup',
        'date_column': 'crawl_datetime',
        'retailers': SIEL_RETAILERS,
    },
}


def normalize_siel_product_line(value):
    """Return a known SIEL source key or raise ``ValueError``."""
    key = str(value or '').strip().lower()
    if key not in SIEL_SOURCE_CONFIG:
        raise ValueError(f'허용되지 않은 SIEL 제품군: {value}')
    return key


def get_siel_source(value):
    """Return a copy of one allow-listed SIEL source configuration."""
    return dict(SIEL_SOURCE_CONFIG[normalize_siel_product_line(value)])


def display_siel_retailer(value):
    """Return the canonical display name for a SIEL retailer."""
    normalized = str(value or '').strip().lower()
    for retailer in SIEL_RETAILERS:
        if retailer.lower() == normalized:
            return retailer
    return str(value or '').strip()


def get_siel_collection_phase(current_time):
    """Return the current-day phase using the confirmed KST completion time."""
    return (
        'collecting'
        if current_time <= SIEL_COLLECTION_END
        else 'complete'
    )


def get_siel_count_status(actual_count):
    """Classify one completed MAIN+BSR retailer count."""
    return (
        'ok'
        if int(actual_count or 0) >= SIEL_OK_THRESHOLD
        else 'critical'
    )
