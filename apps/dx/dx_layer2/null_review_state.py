"""Apply immutable NULL review evidence to one current retail batch."""

from apps.common import null_review_evidence


def review_state(cursor, inspection_date, records, columns, manual_reviews,
                 *, table_name, country, product_line, retailer, is_null):
    """Return merged review metadata and counts for actual current NULL cells.

    History rows are intentionally not passed here: an approval for today's
    source batch must not change the status of a comparison row.
    """
    product_line = str(product_line or '').rsplit('_', 1)[-1].upper()
    context = dict(table_name=table_name, country=country,
                   product_line=product_line, retailer=retailer)
    reviews = dict(manual_reviews)
    enabled = null_review_evidence.uses_new_policy(inspection_date, country)
    evidence = null_review_evidence.load_evidence(
        cursor, inspection_date=inspection_date, records=records,
        columns=columns, **context,
    ) if enabled else []
    exact_evidence = {
        f"{entry.get('record_id')}_{entry.get('column_name')}"
        for entry in evidence
        if str(entry.get('inspection_date')) == str(inspection_date)
    }
    raw_fields = {column: 0 for column in columns}
    reviewed_fields = dict.fromkeys(columns, 0)
    manual_fields = dict.fromkeys(columns, 0)
    auto_fields = dict.fromkeys(columns, 0)
    manual_count = 0
    auto_count = 0
    auto_logs = []
    seen = set()
    for record in records:
        for column in columns:
            key = f"{record.get('id')}_{column}"
            if key in seen:
                continue
            if not is_null(record.get(column), column):
                # Related-field detail queries can retain the row after this
                # cell's NULL is resolved. Do not display its old NULL reason.
                if enabled:
                    reviews.pop(key, None)
                continue
            seen.add(key)
            raw_fields[column] += 1
            review = null_review_evidence.match_review(
                record, column, inspection_date, evidence, **context,
            ) if enabled else None
            # Same-day legacy approvals remain valid for their exact cell;
            # only captured evidence can authorize a subsequent day's cell.
            if review:
                reviews[key] = review
            else:
                if key in exact_evidence:
                    reviews.pop(key, None)
                review = reviews.get(key)
            if not review:
                continue
            reviewed_fields[column] += 1
            if review.get('auto_applied'):
                auto_count += 1
                auto_fields[column] += 1
                auto_logs.append({
                    **review,
                    'id': f'auto:{table_name}:{record.get("id")}:{column}:{inspection_date}',
                    'application_type': '자동확인',
                    'table_name': table_name,
                    'record_id': record.get('id'),
                    'column_name': column,
                    'retailer': retailer,
                    'country': country,
                    'product_line': product_line,
                    'item': record.get('item'),
                    'retailer_sku_name': record.get('retailer_sku_name'),
                    'crawl_date': str(inspection_date),
                    'applied_date': str(inspection_date),
                })
            else:
                manual_count += 1
                manual_fields[column] += 1
    stats = {
        'supports_null_auto_review': enabled,
        'raw_null_count': sum(raw_fields.values()),
        'manual_reviewed_count': manual_count,
        'auto_reviewed_count': auto_count,
        'reviewed_null_count': manual_count + auto_count,
        'raw_fields_detail': raw_fields,
        'reviewed_fields_detail': reviewed_fields,
        'manual_reviewed_fields_detail': manual_fields,
        'auto_reviewed_fields_detail': auto_fields,
    }
    return reviews, stats, auto_logs


def add_review_totals(target, children):
    """Expose review counts at the retailer, product, and validation levels."""
    if not any(child.get('supports_null_auto_review') for child in children):
        return
    target['supports_null_auto_review'] = True
    for name in ('raw_null_count', 'manual_reviewed_count',
                 'auto_reviewed_count', 'reviewed_null_count'):
        target[name] = sum(child.get(name, 0) for child in children)
