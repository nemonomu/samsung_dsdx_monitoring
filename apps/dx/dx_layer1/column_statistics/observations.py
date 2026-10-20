from datetime import datetime
from apps.dx.dx_layer1.collection_issues.services import reconcile_day, coverage_start


def remember_comparison(data, target):
    start, basis = coverage_start(data['country'],data['product'],data['retailer'])
    data['monitoring_start'] = str(start) if start else None
    data['monitoring_start_basis'] = basis
    if start is None or target < start:
        for row in data['comparisons']:
            if row['status'] == 'uncollected':
                row['status'] = 'not_scheduled' if basis == 'registered' else 'unverified_start'
        return
    current = next(d for d in data['daily'] if d['date'] == str(target))
    reconcile_day(data, target, data['completion'], current['raw_total'],
                  now=datetime.fromisoformat(data['updated_at']))
