"""Unified inspection-date to source-date mapping.

This module is intentionally independent from Django and the database so every
monitoring layer can reuse the same date contract.
"""

import re
from datetime import date, datetime, timedelta


class MonitoringDateError(ValueError):
    """Raised when an inspection-date mapping request is not allow-listed."""


COUNTRY_ORDER = ('SEA', 'SEDA', 'SEG', 'SIEL', 'TSE')
PRODUCT_ORDER = ('TV', 'REF', 'LDY')
COUNTRY_OFFSETS = {
    'SEA': -1,
    'SEDA': -1,
    'SEG': 0,
    'SIEL': 0,
    'TSE': 0,
}

SOURCE_DEFINITIONS = tuple(
    (f'{country.lower()}_{product.lower()}', country, product)
    for country in COUNTRY_ORDER
    for product in PRODUCT_ORDER
)
SOURCE_COUNTRY_BY_KEY = {
    source_key: country
    for source_key, country, _product in SOURCE_DEFINITIONS
}
SOURCE_PRODUCT_BY_KEY = {
    source_key: product
    for source_key, _country, product in SOURCE_DEFINITIONS
}

_ISO_DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def _parse_inspection_date(value):
    if isinstance(value, datetime):
        raise MonitoringDateError(
            '검수일은 날짜만 입력해야 합니다. (YYYY-MM-DD)'
        )
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not _ISO_DATE.fullmatch(value):
        raise MonitoringDateError(
            '검수일은 YYYY-MM-DD 형식으로 입력해야 합니다.'
        )
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise MonitoringDateError(
            '존재하지 않는 검수일입니다.'
        ) from exc


def resolve_monitoring_date(inspection_date, country, source_key):
    """Return one allow-listed inspection/source date mapping.

    Returned dates are ISO strings so the contract can be passed directly to
    page APIs and logs without losing the distinction between the two dates.
    """

    parsed_date = _parse_inspection_date(inspection_date)

    if not isinstance(country, str) or country not in COUNTRY_OFFSETS:
        raise MonitoringDateError('허용되지 않은 국가입니다.')

    if not isinstance(source_key, str):
        raise MonitoringDateError('허용되지 않은 source key입니다.')
    source_country = SOURCE_COUNTRY_BY_KEY.get(source_key)
    if source_country is None:
        raise MonitoringDateError('허용되지 않은 source key입니다.')
    if source_country != country:
        raise MonitoringDateError(
            '국가와 source key가 일치하지 않습니다.'
        )

    offset_days = COUNTRY_OFFSETS[country]
    try:
        source_date = parsed_date + timedelta(days=offset_days)
    except OverflowError as exc:
        raise MonitoringDateError(
            '계산할 수 없는 검수일 범위입니다.'
        ) from exc
    return {
        'inspection_date': parsed_date.isoformat(),
        'source_date': source_date.isoformat(),
        'offset_days': offset_days,
        'country': country,
        'source_key': source_key,
    }


def resolve_monitoring_dates(inspection_date):
    """Return mappings for all five countries and fifteen product sources."""

    return [
        resolve_monitoring_date(inspection_date, country, source_key)
        for source_key, country, _product in SOURCE_DEFINITIONS
    ]


def resolve_youtube_monitoring_date(inspection_date):
    """Return the SEA D-1 date contract used by YouTube monitoring."""

    parsed_date = _parse_inspection_date(inspection_date)
    offset_days = COUNTRY_OFFSETS['SEA']
    try:
        source_date = parsed_date + timedelta(days=offset_days)
    except OverflowError as exc:
        raise MonitoringDateError(
            '계산할 수 없는 검수일 범위입니다.'
        ) from exc
    return {
        'inspection_date': parsed_date.isoformat(),
        'source_date': source_date.isoformat(),
        'offset_days': offset_days,
        'country': 'SEA',
        'source_key': 'sea_youtube',
    }
