"""Immutable evidence for manually accepted retail NULL findings.

Only evidence captured at confirmation time can be carried forward.  Legacy
monitoring_corrections rows are deliberately never converted into evidence.
This module owns no database connection and never commits its caller's work.
"""

import hashlib
import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo


POLICY_START = date(2026, 9, 12)
POLICY_VERSION = 1
COUNTRIES = frozenset({'SEA', 'SEM', 'SIEL', 'TSE', 'SEG'})
PRODUCT_LINES = frozenset({'TV', 'REF', 'LDY'})
KOREA = ZoneInfo('Asia/Seoul')
EVIDENCE_TABLE = 'public.monitoring_null_review_evidence'
ELIGIBLE_REASONS = frozenset({
    '수집 대상 제품 아님',
    '상품페이지 내 항목 부재',
    '해당값 정상 확인',
})
_NORMAL_REASON_ALIASES = frozenset({
    '해당값정상 확인', '해당 값 정상 확인', '해당값 정상 확인',
})
_EVIDENCE_COLUMNS = (
    'id', 'correction_id', 'policy_version', 'table_name', 'country',
    'product_line', 'retailer', 'record_id', 'item', 'product_name',
    'column_name', 'subject_key', 'value_snapshot', 'inspection_date',
    'reviewed_at', 'auto_apply_from', 'reason', 'reviewer', 'memo',
    'revoked_at', 'revoked_by', 'revoke_memo',
)


class _EvidenceCollection(list):
    """Keep per-cell lookup linear in the candidate set, not its square."""

    def __init__(self, rows):
        super().__init__(rows)
        self.by_subject = {}
        self.by_record = {}
        for row in self:
            self.by_subject.setdefault(row.get('subject_key'), []).append(row)
            key = (str(row.get('record_id')), row.get('column_name'),
                   str(row.get('inspection_date')))
            self.by_record.setdefault(key, []).append(row)


def _date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _korean_time(value=None):
    if value is None:
        return datetime.now(KOREA)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not isinstance(value, datetime):
        raise ValueError('확인 시각이 올바르지 않습니다.')
    # Explicit naive inputs are defined as Korean local time. Production
    # callers omit this argument so the operating system timezone is irrelevant.
    if value.tzinfo is None:
        return value.replace(tzinfo=KOREA)
    return value.astimezone(KOREA)


def _text(value):
    return '' if value is None else str(value).strip()


def _table_name(value):
    name = _text(value).lower()
    return name[7:] if name.startswith('public.') else name


def canonical_reason(value):
    reason = _text(value)
    return '해당값 정상 확인' if reason in _NORMAL_REASON_ALIASES else reason


def uses_new_policy(inspection_date, country):
    day = _date(inspection_date)
    return bool(day and day >= POLICY_START and _text(country).upper() in COUNTRIES)


def value_snapshot(value):
    """Retain the exact missing representation, including empty vs SQL NULL.

    String NULL, empty string, whitespace, numeric zero, and SQL NULL must not
    accidentally become the same approval just because a UI renders them alike.
    """
    if value is None:
        return {'type': 'null', 'value': None}
    if isinstance(value, bool):
        return {'type': 'boolean', 'value': value}
    if isinstance(value, str):
        return {'type': 'string', 'value': value}
    if isinstance(value, (int, float, Decimal)):
        return {'type': 'number', 'value': str(value)}
    if isinstance(value, (date, datetime)):
        return {'type': 'datetime', 'value': value.isoformat()}
    raise ValueError('자동확인 근거로 저장할 수 없는 값입니다.')


def _subject_key(record, column, *, table_name, country, product_line, retailer):
    item = _text(record.get('item'))
    product_name = _text(record.get('retailer_sku_name'))
    table = _table_name(table_name)
    country = _text(country).upper()
    product_line = _text(product_line).upper()
    account = _text(retailer).casefold()
    # Neither a missing item nor a missing product name can identify a product
    # safely.  Such findings can still be manually accepted for that record.
    if not all((item, product_name, table, account, _text(column))):
        return None
    if country not in COUNTRIES or product_line not in PRODUCT_LINES:
        return None
    payload = [POLICY_VERSION, table, country, product_line, account,
               item, product_name, _text(column)]
    encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def _as_dict(row):
    evidence = dict(row) if isinstance(row, dict) else dict(zip(_EVIDENCE_COLUMNS, row))
    snapshot = evidence.get('value_snapshot')
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except (TypeError, ValueError):
            snapshot = None
    evidence['value_snapshot'] = snapshot
    return evidence


def _auto_exclusion_reason(evidence):
    missing_identity = []
    if not _text(evidence.get('item')):
        missing_identity.append('item')
    if not _text(evidence.get('product_name')):
        missing_identity.append('제품명')
    if missing_identity:
        return '·'.join(missing_identity) + ' 정보 부족'
    if not _text(evidence.get('retailer')):
        return '리테일러 정보 부족'
    if not evidence.get('subject_key'):
        return '상품 식별정보 부족'
    if canonical_reason(evidence.get('reason')) not in ELIGIBLE_REASONS:
        return '자동확인 대상 사유 아님'
    return ''


def _metadata(evidence, *, automatic):
    reviewed_at = _korean_time(evidence['reviewed_at'])
    revoked_at = evidence.get('revoked_at')
    exclusion_reason = _auto_exclusion_reason(evidence)
    return {
        'reason': canonical_reason(evidence.get('reason')),
        'memo': evidence.get('memo') or '',
        'created_id': evidence.get('reviewer') or '',
        'created_at': reviewed_at.isoformat(),
        'auto_applied': automatic,
        'original_crawl_date': str(evidence['inspection_date']),
        'original_created_at': reviewed_at.isoformat(),
        'evidence_id': evidence['id'],
        'correction_id': evidence['correction_id'],
        'auto_apply_from': str(evidence['auto_apply_from']),
        'auto_eligible': not exclusion_reason,
        'auto_exclusion_reason': exclusion_reason,
        'revoked_at': _korean_time(revoked_at).isoformat() if revoked_at else None,
        'revoked_by': evidence.get('revoked_by') or '',
        'revoke_memo': evidence.get('revoke_memo') or '',
    }


def save_manual_evidence(
        cursor, *, correction_id, inspection_date, record, column_name,
        reason, reviewer, memo='', now=None,
        table_name, country, product_line, retailer):
    """Insert one immutable snapshot in the correction's transaction."""
    day = _date(inspection_date)
    if not uses_new_policy(day, country):
        return None
    reviewed_at = _korean_time(now)
    if reviewed_at.date() < POLICY_START:
        return None
    if day > reviewed_at.date():
        raise ValueError('미래 검수일의 확인은 저장할 수 없습니다.')
    if _text(product_line).upper() not in PRODUCT_LINES:
        return None
    if column_name not in record:
        raise ValueError('확인할 항목의 원본 값이 없습니다.')
    if record.get('id') is None:
        raise ValueError('확인할 레코드 ID가 없습니다.')
    context = dict(table_name=table_name, country=country,
                   product_line=product_line, retailer=retailer)
    subject_key = _subject_key(record, column_name, **context)
    snapshot = value_snapshot(record[column_name])
    evidence = {
        'correction_id': correction_id,
        'policy_version': POLICY_VERSION,
        'table_name': _table_name(table_name),
        'country': _text(country).upper(),
        'product_line': _text(product_line).upper(),
        'retailer': _text(retailer),
        'record_id': record['id'],
        'item': _text(record.get('item')),
        'product_name': _text(record.get('retailer_sku_name')),
        'column_name': column_name,
        'subject_key': subject_key,
        'value_snapshot': snapshot,
        'inspection_date': day,
        'reviewed_at': reviewed_at,
        'auto_apply_from': max(day, reviewed_at.date()) + timedelta(days=1),
        'reason': canonical_reason(reason),
        'reviewer': reviewer,
        'memo': memo or '',
        'revoked_at': None,
        'revoked_by': None,
        'revoke_memo': None,
    }
    columns = _EVIDENCE_COLUMNS[1:]
    values = [evidence[name] for name in columns]
    values[columns.index('value_snapshot')] = json.dumps(snapshot, ensure_ascii=False)
    placeholders = ['%s::jsonb' if name == 'value_snapshot' else '%s' for name in columns]
    cursor.execute(
        f"INSERT INTO {EVIDENCE_TABLE} ({', '.join(columns)}) "
        f"VALUES ({', '.join(placeholders)}) RETURNING id",
        tuple(values),
    )
    inserted = cursor.fetchone()
    if not inserted:
        raise ValueError('NULL 확인 근거를 저장하지 못했습니다.')
    evidence['id'] = inserted['id'] if isinstance(inserted, dict) else inserted[0]
    return _metadata(evidence, automatic=False)


def load_evidence(
        cursor, *, inspection_date, records, columns,
        table_name, country, product_line, retailer):
    """Load only subjects present in this collection, without a time expiry.

    Do not filter revoked or non-eligible approvals here: a newer revoked or
    differently justified manual review must prevent fallback to an older one.
    """
    if not uses_new_policy(inspection_date, country):
        return []
    context = dict(table_name=table_name, country=country,
                   product_line=product_line, retailer=retailer)
    records = list(records)
    columns = list(columns)
    subjects = sorted({
        key for record in records for column in columns
        if (key := _subject_key(record, column, **context)) is not None
    })
    record_ids = sorted({int(record['id']) for record in records if record.get('id') is not None})
    if not columns or not (subjects or record_ids):
        return []
    day = _date(inspection_date)
    end_time = datetime.combine(day + timedelta(days=1), time.min, KOREA)
    cursor.execute(f"""
        WITH scoped AS (
            SELECT {', '.join(_EVIDENCE_COLUMNS)}
            FROM {EVIDENCE_TABLE}
            WHERE policy_version = %s
              AND table_name = %s AND country = %s AND product_line = %s
              AND LOWER(TRIM(retailer)) = %s
              AND inspection_date <= %s AND reviewed_at < %s
              AND (
                  subject_key = ANY(%s)
                  OR (inspection_date = %s AND record_id = ANY(%s)
                      AND column_name = ANY(%s))
              )
        ), latest AS (
            SELECT DISTINCT ON (subject_key) {', '.join(_EVIDENCE_COLUMNS)}
            FROM scoped WHERE subject_key IS NOT NULL
            ORDER BY subject_key, reviewed_at DESC, id DESC
        )
        SELECT {', '.join(_EVIDENCE_COLUMNS)} FROM latest
        UNION
        SELECT {', '.join(_EVIDENCE_COLUMNS)} FROM scoped
        WHERE inspection_date = %s AND record_id = ANY(%s)
          AND column_name = ANY(%s)
    """, (POLICY_VERSION, _table_name(table_name), _text(country).upper(),
          _text(product_line).upper(), _text(retailer).lower(), day, end_time,
          subjects, day, record_ids, columns, day, record_ids, columns))
    return _EvidenceCollection(_as_dict(row) for row in cursor.fetchall())


def match_review(
        record, column, inspection_date, evidence, *,
        table_name, country, product_line, retailer):
    """Return the latest matching human decision; never chain auto decisions."""
    day = _date(inspection_date)
    if not uses_new_policy(day, country) or column not in record:
        return None
    context = dict(table_name=table_name, country=country,
                   product_line=product_line, retailer=retailer)
    subject = _subject_key(record, column, **context)
    candidates = []
    if isinstance(evidence, _EvidenceCollection):
        record_key = (str(record.get('id')), column, str(day))
        relevant = list(evidence.by_subject.get(subject, ())) if subject else []
        relevant.extend(evidence.by_record.get(record_key, ()))
    else:
        relevant = evidence
    for raw in relevant:
        decision = _as_dict(raw)
        reviewed_on = _date(decision.get('inspection_date'))
        reviewed_at = _korean_time(decision['reviewed_at'])
        same_record = (
            str(decision.get('record_id')) == str(record.get('id'))
            and reviewed_on == day
            and decision.get('column_name') == column
            and decision.get('item') == _text(record.get('item'))
            and decision.get('product_name') == _text(record.get('retailer_sku_name'))
        )
        if (
            decision.get('policy_version') == POLICY_VERSION
            and ((subject and decision.get('subject_key') == subject) or same_record)
            and _table_name(decision.get('table_name')) == _table_name(table_name)
            and decision.get('country') == _text(country).upper()
            and decision.get('product_line') == _text(product_line).upper()
            and _text(decision.get('retailer')).casefold() == _text(retailer).casefold()
            and reviewed_on and POLICY_START <= reviewed_on <= day
            and POLICY_START <= reviewed_at.date() <= day
        ):
            candidates.append(decision)
    if not candidates:
        return None
    manual_candidates = [
        row for row in candidates
        if str(row.get('record_id')) == str(record.get('id'))
        and _date(row['inspection_date']) == day
    ]
    latest = max(manual_candidates or candidates,
                 key=lambda row: (_korean_time(row['reviewed_at']), int(row['id'])))
    revoked_at = latest.get('revoked_at')
    if revoked_at and _korean_time(revoked_at).date() <= day:
        return None
    if latest.get('value_snapshot') != value_snapshot(record[column]):
        return None
    if manual_candidates:
        return _metadata(latest, automatic=False)
    if (
        not subject
        or canonical_reason(latest.get('reason')) not in ELIGIBLE_REASONS
        or _date(latest.get('auto_apply_from')) is None
        or day < _date(latest['auto_apply_from'])
        or day <= _date(latest['inspection_date'])
    ):
        return None
    return _metadata(latest, automatic=True)


def revoke_evidence(cursor, correction_ids, reviewer, memo='', now=None):
    """Stop future reuse while retaining the immutable approval and its date."""
    ids = sorted({int(value) for value in correction_ids})
    if not ids:
        return 0
    cursor.execute(f"""
        UPDATE {EVIDENCE_TABLE}
        SET revoked_at = %s, revoked_by = %s, revoke_memo = %s
        WHERE correction_id = ANY(%s) AND revoked_at IS NULL
    """, (_korean_time(now), reviewer, memo or '', ids))
    return cursor.rowcount
