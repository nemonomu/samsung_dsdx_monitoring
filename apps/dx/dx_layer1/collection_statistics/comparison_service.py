"""Recover live comparison bases from stored summaries, without source queries."""
from datetime import timedelta

from apps.dx.dx_layer1.models import CollectionDailySnapshot as Daily
from .calculations import compare_rows, comparison_rules, current_volume_decision, row_key


def live_comparison_rows(snapshots):
    rows_by_country = {
        snapshot.country: [current_volume_decision(row, snapshot.country) for row in snapshot.rows]
        for snapshot in snapshots
    }
    incomplete = {
        snapshot.country: [row for row in rows_by_country[snapshot.country]
                           if row.get('observation_state') == 'ready'
                           and len(comparison_rules(row, snapshot.country)) < 2]
        for snapshot in snapshots if not snapshot.refresh_error
    }
    targets = [snapshot for snapshot in snapshots if incomplete.get(snapshot.country)]
    if not targets:
        return rows_by_country

    # Older missing/pending snapshots did not save their BSR baseline. Bound
    # this repair to the same prior 28 source dates used by the collector.
    history = list(Daily.objects.filter(
        country__in=[snapshot.country for snapshot in targets], refresh_error=False,
        source_date__gte=min(snapshot.source_date for snapshot in targets) - timedelta(days=28),
        source_date__lt=max(snapshot.source_date for snapshot in targets),
    ).only('country', 'source_date', 'rows'))
    for snapshot in targets:
        prior = [{**row, 'source_date': str(old.source_date)}
                 for old in history if old.country == snapshot.country
                 and snapshot.source_date - timedelta(days=28) <= old.source_date < snapshot.source_date
                 for row in old.rows]
        rebuilt = {row_key(row): row for row in compare_rows(
            incomplete[snapshot.country], prior, country=snapshot.country)}
        rows_by_country[snapshot.country] = [
            current_volume_decision({**row, 'baselines': {
                **row.get('baselines', {}), **rebuilt[row_key(row)]['baselines'],
            }}, snapshot.country) if row_key(row) in rebuilt else row
            for row in rows_by_country[snapshot.country]
        ]
    return rows_by_country
