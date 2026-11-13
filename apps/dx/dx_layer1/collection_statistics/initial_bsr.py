"""Read first-five-day BSR evidence from saved summaries, never source tables."""
from apps.common.dryer_onboarding import initial_bsr_policy, OPERATIONAL_FROM
from apps.dx.dx_layer1.models import CollectionDailySnapshot as Daily
from .calculations import MINIMUM_DAYS, row_key, remember_initial_bsr


def load_samples(country, rows, source_day):
    keys = {row_key(row) for row in rows if not row.get('preview_mode')
            and source_day > OPERATIONAL_FROM
            and initial_bsr_policy(country, row['product'], row['retailer'])}
    samples = {}
    if not keys:
        return samples
    query = Daily.objects.filter(country=country, refresh_error=False,
        source_date__gte=OPERATIONAL_FROM, source_date__lt=source_day).order_by('source_date')
    for snapshot in query.only('source_date', 'rows').iterator(chunk_size=50):
        remember_initial_bsr(samples, snapshot.rows, str(snapshot.source_date), country)
        if all(len(samples.get(key, {})) == MINIMUM_DAYS for key in keys):
            break
    return samples


def project_rows(country, rows, source_day):
    """Upgrade legacy waiting verdicts while their offline rebuild is pending."""
    targets = [row for row in rows if not row.get('preview_mode')
               and source_day > OPERATIONAL_FROM
               and initial_bsr_policy(country, row['product'], row['retailer'])
               and len(row.get('bsr_initial_samples', [])) < MINIMUM_DAYS
               and row.get('observation_state') == 'ready']
    if not targets:
        return rows
    samples = load_samples(country, targets, source_day)
    keys = {row_key(row) for row in targets}
    return [{**row, 'bsr_initial_samples': [{'date': day, 'value': value}
             for day, value in sorted(samples.get(row_key(row), {}).items())]}
            if row_key(row) in keys else row for row in rows]
