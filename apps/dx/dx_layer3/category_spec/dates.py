"""Category checks receive inspection dates; only SEA TV uses D-1 here."""
from datetime import date
from apps.common.inspection_dates import resolve_monitoring_date


def rule_date_mapping(inspection_date, table_name):
    if table_name == 'tv_retail_com':
        return resolve_monitoring_date(inspection_date, 'SEA', 'sea_tv')
    return {'inspection_date': str(inspection_date), 'source_date': str(inspection_date), 'offset_days': 0}


def rule_source_date(inspection_date, table_name):
    return date.fromisoformat(rule_date_mapping(inspection_date, table_name)['source_date'])
