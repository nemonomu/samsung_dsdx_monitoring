"""SEUK TV review counts from the existing Layer 2 and Layer 3 workflows."""

from datetime import date

from apps.dx.dx_layer1.seuk_retail.sources import TV_RETAILERS, TV_START
from apps.dx.dx_layer2 import seuk_duplicate_validation, seuk_null_validation
from apps.dx.dx_layer2.format_validation.services import get_format_stats
from apps.dx.dx_layer3.cross_field.seuk_services import get_seuk_cross_field_summary
from apps.dx.dx_layer4.corrections.services import saved_review_counts


PRODUCT_LINE = 'seuk_tv'
SECTION = 'seuk_tv_retail'
SOURCE_TABLE = seuk_null_validation.SEUK_SOURCE_CONFIG[PRODUCT_LINE]['table_name']
CHECK_LABELS = (
    ('null_check', 'NULL 검증'),
    ('format_check', '형식검증'),
    ('duplicate_check', '중복검증'),
    ('cross_field', '크로스필드'),
)


def _by_retailer(tables):
    return {row['retailer']: row for table in tables if table['table'] == SECTION
            for row in table['retailers']}


def review_snapshot(cursor, mapping):
    """Return one same-day snapshot, with empty results before launch."""
    payload = {**mapping, 'read_only': True, 'retailers': [], 'active_from': str(TV_START)}
    if mapping['source_date'] < str(TV_START):
        return payload

    inspection_date = mapping['inspection_date']
    inspection_day = date.fromisoformat(inspection_date)
    null_stats = {'tables': []}
    seuk_null_validation.append_null_stats(cursor, inspection_day, null_stats, SECTION)
    nulls = _by_retailer(null_stats['tables'])
    format_stats, _ = get_format_stats(cursor, inspection_day, category=SECTION)
    formats = _by_retailer(format_stats['tables'])
    duplicate_stats = {'tables': []}
    seuk_duplicate_validation.append_duplicate_stats(cursor, inspection_day, duplicate_stats, SECTION)
    duplicates = _by_retailer(duplicate_stats['tables'])
    cross = get_seuk_cross_field_summary(cursor, inspection_day, PRODUCT_LINE)
    crossfields = {row['retailer']: row for row in cross['retailers']}
    saved_counts = saved_review_counts(cursor, inspection_date, SOURCE_TABLE, TV_RETAILERS)

    for retailer in TV_RETAILERS:
        null = nulls.get(retailer, {})
        format_result = formats.get(retailer, {})
        format_reviews = format_result.get('format_review_counts')
        pending = {
            'null_check': null.get('total_null_count', 0),
            'format_check': max(0, format_result.get('issue_count', 0) - (format_reviews or {}).get('error', 0)),
            'duplicate_check': duplicates.get(retailer, {}).get('duplicate_groups', 0),
            'cross_field': crossfields.get(retailer, {}).get('total_errors'),
        }
        normal = {check: saved_counts.get((retailer.lower(), check, 'normal'), 0)
                  for check, _ in CHECK_LABELS}
        normal['null_check'] = null.get('reviewed_null_count', normal['null_check'])
        if format_reviews is not None:
            normal['format_check'] = format_reviews.get('registered_normal', 0) + format_reviews.get('legacy_normal', 0)
        payload['retailers'].append({
            'name': retailer, 'collected': null.get('total', 0),
            'checks': [{
                'type': check, 'label': label, 'pending': pending[check], 'normal': normal[check],
                'corrected': saved_counts.get((retailer.lower(), check, 'corrected'), 0),
            } for check, label in CHECK_LABELS],
        })
    return payload
