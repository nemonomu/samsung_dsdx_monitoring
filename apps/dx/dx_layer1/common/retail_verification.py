"""Keep receipt of retail rows separate from completed volume verification.

The current sources expose counts and batch IDs, not final load acknowledgments.
Until such a source is connected, only the retailer's scheduled window can
release verification, except SEG, SEM and TSE which explicitly assess received rows
immediately through its per-retailer collection phase.
"""

PENDING = {'PENDING', 'COLLECTING', 'ANALYZING', 'VERIFYING'}
RETAIL_TYPES = {'retail', 'seda_retail', 'siel_retail', 'seg_retail', 'sem_retail', 'tse_retail'}


def has_collection(row):
    return (any((row.get(key) or 0) > 0 for key in
                ('raw_count', 'actual_count', 'actual', 'count', 'total', 'main_count', 'bsr_count'))
            or any((item.get('count') or 0) > 0 for item in row.get('items', [])))


def verification_state(check, slot, row):
    if row.get('status') == 'ERROR' or row.get('refresh_error'):
        return 'error'
    phase = row.get('collection_phase') or check.get('phase')
    if not row.get('collection_phase') and row.get('status') in PENDING and phase == 'complete':
        phase = 'collecting'
    if phase is None:
        phase = 'collecting' if row.get('status') in PENDING or slot.get('status') in PENDING else 'complete'
    if phase != 'complete':
        if has_collection(row):
            return 'waiting'
        return 'pending' if phase == 'pending' else 'collecting'
    return 'ready'


def apply_verification_status(check):
    """Annotate history eligibility without overriding the automatic verdict.

    A pending statistics refresh is not a collection or manual-review status.
    In particular, an existing OK result must remain OK on the dashboard.
    """
    if check.get('check_type') not in RETAIL_TYPES:
        return
    for category in check.get('categories', []):
        for slot in category.get('time_slots') or [{'retailers': category.get('retailers', [])}]:
            for row in slot.get('retailers', []):
                row['verification_state'] = verification_state(check, slot, row)
