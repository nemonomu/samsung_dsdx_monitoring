"""SEM TV review counts from the existing Layer 2 and Layer 3 checks."""

from datetime import date

from apps.common.sem_retail import SEM_TV_OBSERVATION_RETAILERS, SEM_TV_OBSERVATION_START
from apps.dx.dx_layer2 import sem_validation
from apps.dx.dx_layer3.cross_field.sem_services import get_sem_cross_field_summary
from apps.dx.dx_layer3.field_missing.sea_services import field_missing_detection


_PRODUCT = 'sem_tv'


def review_snapshot(cursor, mapping):
    payload = {**mapping, 'read_only': True, 'retailers': [],
               'active_from': str(SEM_TV_OBSERVATION_START)}
    if mapping['source_date'] < payload['active_from']:
        return payload

    inspection_day = date.fromisoformat(mapping['inspection_date'])
    source_day = date.fromisoformat(mapping['source_date'])

    source = sem_validation.SEM_SOURCE_CONFIG[_PRODUCT]
    null_reviews = sem_validation._load_normal_reviews(cursor, inspection_day, _PRODUCT, 'null_check')
    format_reviews = sem_validation._load_normal_reviews(cursor, inspection_day, _PRODUCT, 'format_check')
    cross = get_sem_cross_field_summary(cursor, inspection_day, _PRODUCT)
    discount = next(rule['retailer_checks'] for rule in cross['rule_summary']
                    if rule['rule_key'] == 'mx_tv_savings_amount_match')

    for retailer in SEM_TV_OBSERVATION_RETAILERS:
        rows, _ = sem_validation._latest_rows(cursor, inspection_day, source, retailer)
        collected = len(rows)
        null_fields = sem_validation._validation_required_columns(_PRODUCT, retailer)
        null_count = sum(
            sem_validation._missing(row.get(field)) and f"{row.get('id')}_{field}" not in null_reviews
            for row in rows for field in null_fields
        )
        format_count = sum(
            f"{row.get('id')}_{field}" not in format_reviews
            for row in rows for field in sem_validation.evaluate_format(row, _PRODUCT, retailer)
        )
        check = discount.get(retailer, {})
        missing = field_missing_detection(cursor, source_day, _PRODUCT, retailer)['summary']
        checks = (
            ('null_check', 'NULL 검증', null_count if collected else None),
            ('format_check', '형식검증', format_count if collected else None),
            ('duplicate_check', '중복검증', len(sem_validation._duplicate_groups(rows)) if collected else None),
            ('cross_field', '크로스필드', check['failed'] if check.get('checked') else None),
            ('field_missing', '필드 누락', missing['total_missing_cases'] if missing['status'] != 'PENDING' else None),
        )
        payload['retailers'].append({
            'name': retailer, 'collected': collected,
            'checks': [{'type': key, 'label': title, 'pending': pending,
                        'normal': None, 'corrected': None} for key, title, pending in checks],
        })
    return payload
