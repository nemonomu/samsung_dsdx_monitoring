"""Shared cross-field detail contract for every retail source.

Source adapters own dates, latest-batch selection and validation. Pass their
unfiltered source rows here: history must never be built from failures alone.
New country/retailer adapters must use this contract for their detail response.

Default to three days (one to thirty selectable), including the source day.
Return row_role and row_source_date; count and edit only target findings.
Populate source-specific derived display fields on normal history too, without
copying the current finding's error message onto those historical rows.
Run tests.unit.test_crossfield_history and tests/test_crossfield_history.js
when adding an adapter; the contract test includes unknown-country coverage.
"""

from datetime import date, datetime, timedelta


def build_detail_history(rows, findings, source_date, date_column, days=1,
                         date_of=None, comparison_rows=()):
    """Keep current findings and all prior rows for their retailer/item pairs.

History is read-only and does not contribute to issue counts. Normal review
markers are presentation metadata, never an exclusion condition for history.
    Missing items remain visible as targets but cannot safely identify history.
    Explicit evidence used by a comparison rule is retained even when older
    than the display window (for example, SEG's five-day decrease baseline).
"""
    end = date.fromisoformat(str(source_date)[:10])
    start = end - timedelta(days=min(30, max(1, int(days or 1))) - 1)

    def row_date(row):
        if date_of:
            return date_of(row, date_column)
        value = row.get(date_column)
        if isinstance(value, (date, datetime)):
            return value.isoformat()[:10]
        return str(value or '').strip()[:10]

    def item_key(row):
        retailer = str(row.get('account_name') or '').strip().casefold()
        item = str(row.get('item') or '').strip()
        return (retailer, item) if retailer and item else None

    targets = [row for row in findings if row_date(row) == str(end)]
    keys = {item_key(row) for row in targets} - {None}
    finding_by_id = {str(row.get('id')): row for row in findings}
    comparison_ids = {str(row.get('id')) for row in comparison_rows}
    result = []
    seen = set()
    for row in list(rows) + list(comparison_rows) + targets:
        day = row_date(row)
        identity = str(row.get('id'))
        target = finding_by_id.get(identity) if day == str(end) else None
        if target is None and not (
            day < str(end) and item_key(row) in keys
            and (str(start) <= day or identity in comparison_ids)
        ):
            continue
        if identity in seen:
            continue
        seen.add(identity)
        detail = dict(row)
        detail.update(finding_by_id.get(identity, {}))
        detail['row_source_date'] = day
        detail['row_role'] = 'target' if target is not None else 'comparison_history'
        result.append(detail)
    result.sort(key=lambda row: (
        item_key(row) or ('', ''), row['row_source_date'],
        str(row.get('id') or '').zfill(20),
    ))
    return result
