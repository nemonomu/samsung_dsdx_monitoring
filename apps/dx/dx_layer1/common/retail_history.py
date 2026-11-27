"""Read recent positive history first, with an exact fallback for sparse feeds."""
from collections import Counter
from datetime import timedelta


def latest_positive_history(day, retailers, limit, read):
    # A busy feed normally has seven observations inside four weeks.
    start = (day - timedelta(days=28)).isoformat()
    recent = read(retailers, start, day.isoformat())
    counts = Counter(row['retailer'] for row in recent)
    sparse = [retailer for retailer in retailers if counts[retailer] < limit]
    if not sparse:
        return recent
    older = read(sparse, None, start)
    for row in older:
        retailer = row['retailer']
        if counts[retailer] < limit:
            recent.append(row)
            counts[retailer] += 1
    # The two queries already return latest-first order within each retailer.
    return sorted(recent, key=lambda row: row['retailer'])
