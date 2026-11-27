"""SEM TV review counts from the existing Layer 2 and Layer 3 checks."""

from datetime import date

from apps.common.sem_retail import SEM_TV_OBSERVATION_RETAILERS, SEM_TV_OBSERVATION_START
from apps.dx.dx_layer2 import sem_validation
from apps.dx.dx_layer2.format_validation.services import get_format_stats
from apps.dx.dx_layer3.cross_field.sem_services import get_sem_cross_field_summary
from apps.dx.dx_layer3.field_missing.sea_services import field_missing_detection
from apps.dx.dx_layer4.corrections.services import saved_review_counts


_PRODUCT = 'sem_tv'
_SECTION = 'sem_tv_retail'


def _by_retailer(validation):
    return {row['retailer']: row for table in validation['tables'] if table['table'] == _SECTION
            for row in table['retailers']}


def review_snapshot(cursor, mapping):
    payload = {**mapping, 'read_only': True, 'retailers': [],
               'active_from': str(SEM_TV_OBSERVATION_START)}
    if mapping['source_date'] < payload['active_from']:
        return payload

    inspection_day = date.fromisoformat(mapping['inspection_date'])
    source_day = date.fromisoformat(mapping['source_date'])

    null_stats = {'tables': []}
    sem_validation.append_null_stats(cursor, inspection_day, null_stats, _SECTION)
    nulls = _by_retailer(null_stats)
    format_stats, _ = get_format_stats(cursor, inspection_day, category=_SECTION)
    formats = _by_retailer(format_stats)
    duplicate_stats = {'tables': []}
    sem_validation.append_duplicate_stats(cursor, inspection_day, duplicate_stats, _SECTION)
    duplicates = _by_retailer(duplicate_stats)
    cross_checks = get_sem_cross_field_summary(cursor, inspection_day, _PRODUCT)['retailer_checks']
    saved_counts = saved_review_counts(
        cursor, mapping['inspection_date'], sem_validation.SEM_SOURCE_CONFIG[_PRODUCT]['table_name'],
        SEM_TV_OBSERVATION_RETAILERS,
    )

    for retailer in SEM_TV_OBSERVATION_RETAILERS:
        null = nulls.get(retailer, {})
        format_result = formats.get(retailer, {})
        format_reviews = format_result.get('format_review_counts')
        collected = null.get('total', 0)
        cross_check = cross_checks.get(retailer, {})
        missing = field_missing_detection(cursor, source_day, _PRODUCT, retailer)['summary']
        format_pending = max(0, format_result.get('issue_count', 0) - (format_reviews or {}).get('error', 0))
        checks = (
            ('null_check', 'NULL 검증', null.get('total_null_count', 0) if collected else None),
            ('format_check', '형식검증', format_pending if collected else None),
            ('duplicate_check', '중복검증',
             duplicates.get(retailer, {}).get('duplicate_groups', 0) if collected else None),
            ('cross_field', '크로스필드',
             cross_check['failed'] + cross_check['review_count'] if cross_check.get('checked') else None),
            ('field_missing', '필드 누락', missing['total_missing_cases'] if missing['status'] != 'PENDING' else None),
        )
        seller_key = retailer.lower()
        normal = {check: saved_counts.get((seller_key, check, 'normal'), 0) for check, _, _ in checks}
        normal['null_check'] = null.get('reviewed_null_count', normal['null_check'])
        if format_reviews is not None:
            normal['format_check'] = format_reviews.get('registered_normal', 0) + format_reviews.get('legacy_normal', 0)
        payload['retailers'].append({
            'name': retailer, 'collected': collected,
            'checks': [{'type': key, 'label': title, 'pending': pending,
                        'normal': normal[key], 'corrected': saved_counts.get((seller_key, key, 'corrected'), 0),
                        **({'findings': {'failed': cross_check['failed'], 'review_count': cross_check['review_count']}}
                           if key == 'cross_field' and pending is not None else {})}
                       for key, title, pending in checks],
        })
    return payload
