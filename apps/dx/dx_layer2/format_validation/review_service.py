"""Exact-value review policies shared by detail, statistics and batch review."""
from collections import Counter
from copy import deepcopy
from datetime import date
import hashlib
import json
import re

from django.conf import settings
from django.core import signing
from . import review_repository as repository
from . import review_evidence


# Presentation scope only: these fields still participate in format validation.
BASELINE_EXCLUDED_FIELDS = frozenset({
    'item', 'product_url', 'url', 'sku', 'account_name', 'country', 'product', 'page_type',
    'star_rating', 'count_of_star_ratings', 'detailed_review_content', 'summarized_review_content',
    'count_of_reviews', 'final_sku_price', 'original_sku_price',
})


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def retailer_key(value):
    return re.sub(r'\s+', '', str(value or '')).casefold()


def supported(table):
    return table == 'tv_retail' or bool(re.fullmatch(
        r'(sea|siel|tse|seda|seg|sem|seib)_(tv|ref|ldy|ldy_dryer)_retail', str(table),
    ))


def load_scopes():
    return repository.scopes()


def has_scope(scopes, table, retailer, day=None):
    country = 'SEA' if table == 'tv_retail' else str(table).split('_')[0].upper()
    return any(scope.context.get('country') == country
               and scope.context['retailer'] == retailer_key(retailer)
               and scope.context.get('environment') == ('test' if settings.DEBUG else 'production')
               and any(not p.get('is_del') and p['action'] in ('normal', 'error')
                       and (p['action'] == 'normal' or scope.context['section'] == table)
                       and (day is None or p['date'] <= str(day)) for p in scope.policies.values())
               for scope in scopes.values()) if supported(table) else False


def context_for(data):
    section = data['table']
    country = 'SEA' if section == 'tv_retail' else section.split('_')[0].upper()
    product = 'TV' if section == 'tv_retail' else section.split('_', 1)[1].removesuffix('_retail').upper()
    return {
        'section': section, 'source_table': data['actual_table'], 'country': country,
        'product': product, 'retailer': retailer_key(data['retailer']),
        'retailer_name': data['retailer'],
        'check': 'format', 'environment': 'test' if settings.DEBUG else 'production',
    }


def group_key(field, value):
    # Whitespace, case and Unicode differences in collected values remain distinct.
    return digest([field, value])


def shared_context(context):
    """Normal approvals span products, but never countries or DB environments."""
    return (context['country'], context['retailer'], context['check'], context['environment'],
            context['source_table'].removeprefix('public.').startswith('test_'))


def related_scopes(context, scopes):
    return {key: scope for key, scope in scopes.items()
            if shared_context(scope.context) == shared_context(context)}


def effective_policies(context, scopes, day=None):
    policies, local_errors = {}, {}
    local_key = digest(context)
    for fingerprint, scope in related_scopes(context, scopes).items():
        for key, policy in scope.policies.items():
            # Only normal registrations and their revocation are shared. Error
            # records and their IDs retain the original source-table scope.
            if day is not None and policy['date'] > str(day):
                continue
            enriched = {**policy, 'origin_fingerprint': fingerprint,
                        'origin_product': scope.context['product']}
            if policy['action'] == 'error':
                if fingerprint == local_key:
                    local_errors[key] = enriched
                continue
            if not policy.get('shared_normal', True):
                continue
            previous = policies.get(key)
            if previous and previous.get('event_id', 0) > policy.get('event_id', 0):
                continue
            policies[key] = enriched
    for key, policy in local_errors.items():
        shared = policies.get(key, {})
        if (shared.get('action') != 'normal' or shared.get('is_del')
                or policy.get('event_id', 0) > shared.get('event_id', 0)):
            policies[key] = policy
    return policies


def shared_revision(context, scopes):
    return digest({key: scope.revision for key, scope in related_scopes(context, scopes).items()})


def apply_detail(data, scopes, errors_only=False):
    data = deepcopy(data)
    if not data.get('actual_table'):
        return data
    context = context_for(data)
    scope = scopes.get(digest(context))
    policies = effective_policies(context, scopes, data['date'])
    day = str(data['date'])
    targets = {str(i) for i in data.get('target_ids', [])}
    fields = data.get('validation_fields', [])
    counts, review_counts = Counter(), Counter()
    legacy = data.get('normal_reviews', {})
    for row in data.get('results', []):
        current = str(row['id']) in targets
        baseline = set(row.get('error_fields', []))
        raw_errors = set(row.get('error_details', {})) | baseline
        row['raw_error_fields'] = sorted(raw_errors)
        row['raw_error_details'] = deepcopy(row.get('error_details', {}))
        row['review_states'] = {}
        row['is_review_target'] = current
        effective = set(baseline)
        for field in fields:
            value = row.get(field)
            if value is None or str(value).strip() == '':
                continue
            key = group_key(field, str(value))
            policy = policies.get(key)
            active = policy and not policy.get('is_del') and day >= policy['date']
            old_review = f"{row['id']}_{field}" in legacy
            if old_review:
                effective.discard(field)
            state = 'legacy_normal' if old_review else 'pending' if field in baseline else 'baseline_normal'
            if active and policy['action'] == 'normal':
                state = 'registered_normal'
                effective.discard(field)
            elif active and policy['action'] == 'error':
                effective.add(field)
                state = 'error' if day == policy['date'] and str(row['id']) in {
                    str(i) for i in policy['record_ids']
                } else 'pending'
                row.setdefault('error_details', {})[field] = {
                    'rule': '운영 검토 오류',
                    'reason': policy['reason'] if state == 'error' else '과거 오류로 확인된 동일 값 — 재검증 필요',
                }
                legacy.pop(f"{row['id']}_{field}", None)
            row['review_states'][field] = state
            if current:
                review_counts[state] += 1
        row['error_fields'] = sorted(effective)
        if current:
            counts.update(effective)
    if errors_only:
        current_errors = [r for r in data['results'] if r['is_review_target'] and r['error_fields']]
        ids = {str(r['id']) for r in current_errors}
        items = {str(r['item']) for r in current_errors if r.get('item')}
        data['results'] = [r for r in data['results'] if str(r['id']) in ids or
                           (not r['is_review_target'] and str(r.get('item')) in items)]
    data.update(field_counts=dict(counts), total_format_count=sum(counts.values()),
                review_counts=dict(review_counts), review_revision=scope.revision if scope else 0)
    return data


def inventory(cursor, day, table, retailer, scopes=None):
    from .services import _get_format_detail_raw
    if not supported(table) or not retailer:
        raise ValueError('지원하는 Retail 리테일러를 선택하세요.')
    scopes = load_scopes() if scopes is None else scopes
    data = _get_format_detail_raw(cursor, day, table, retailer, 1, include_normal=True)
    if not data.get('actual_table') or not data.get('retailer'):
        raise ValueError('조회 가능한 리테일러 범위를 찾지 못했습니다.')
    if retailer_key(data['retailer']) != retailer_key(retailer):
        raise ValueError('리테일러 범위가 일치하지 않습니다.')
    context = context_for(data)
    fingerprint = digest(context)
    scope = scopes.get(fingerprint)
    data = apply_detail(data, scopes)
    groups = {}
    for row in data['results']:
        if not row['is_review_target']:
            continue
        for field, state in row['review_states'].items():
            value = str(row[field])
            key = group_key(field, value)
            group = groups.setdefault(key, {
                'key': key, 'field': field, 'value': value, 'states': {}, 'records': [],
                'source_date': data.get('source_date', str(day)),
            })
            group['states'][state] = group['states'].get(state, 0) + 1
            group['records'].append({
                'id': row['id'], 'item': str(row.get('item') or ''),
                'name': str(row.get('retailer_sku_name') or ''),
                'url': str(row.get('product_url') or ''), 'state': state,
                'collected_at': str(row.get(data.get('date_column', 'crawl_datetime')) or ''),
                'original_error': row.get('raw_error_details', {}).get(field, {}),
            })
    for group in groups.values():
        group['records'].sort(key=lambda r: str(r['id']))
        group['count'] = len(group['records'])
        states = group['states']
        group['tab'] = 'issues' if states.get('pending', 0) + states.get('error', 0) else (
            'registered' if states.get('registered_normal') else 'baseline'
        )
    registrations = [dict(policy) for policy in effective_policies(context, scopes).values()
                     if not policy.get('is_del')]
    history = []
    for key, related in related_scopes(context, scopes).items():
        for event in repository.history(related):
            if key != fingerprint and not event['shared_normal']:
                continue
            history.append({**event, 'origin_fingerprint': key,
                            'origin_product': related.context['product'],
                            'origin_revision': related.revision})
    return {
        'context': context, 'fingerprint': fingerprint, 'date': str(day),
        'source_date': data.get('source_date', str(day)), 'retailer': data['retailer'],
        'revision': scope.revision if scope else 0, 'groups': list(groups.values()),
        'shared_revision': shared_revision(context, scopes),
        'counts': data['review_counts'], 'registrations': registrations,
        'history': sorted(history, key=lambda e: e['id'], reverse=True)[:100],
        'available': repository.ready(evidence=True),
        'record_count': len(data['target_ids']),
        'baseline_excluded_fields': sorted(BASELINE_EXCLUDED_FIELDS),
    }


def validate_reason(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 1000:
        raise ValueError('확인 또는 취소 사유를 1~1,000자로 입력하세요.')
    return value.strip()


def selected_targets(data, keys, action):
    if not isinstance(keys, list) or not 1 <= len(keys) <= 100 or any(not isinstance(k, str) for k in keys):
        raise ValueError('한 번에 1~100개 값 그룹을 선택하세요.')
    if len(set(keys)) != len(keys):
        raise ValueError('중복된 그룹이 있습니다.')
    groups = {g['key']: g for g in data['groups']}
    if action == 'revoke':
        for policy in data['registrations']:
            groups.setdefault(policy['key'], {**policy, 'records': [], 'count': 0})
            groups[policy['key']] = {**groups[policy['key']],
                                     'shared_normal': policy['action'] == 'normal'}
    if any(key not in groups for key in keys):
        raise repository.ReviewConflict('수집 데이터가 변경됐습니다. 새로 조회하세요.')
    if action == 'revoke' and any(key not in {p['key'] for p in data['registrations']} for key in keys):
        raise ValueError('현재 등록된 기준만 취소할 수 있습니다.')
    return [groups[key] for key in sorted(keys)]


def preview(data, keys, action, reason, evidence=None):
    if not data['available']:
        raise ValueError('검토 저장소가 준비되지 않았습니다. dx_layer2 마이그레이션이 필요합니다.')
    if action not in ('normal', 'error', 'revoke'):
        raise ValueError('지원하지 않는 처리입니다.')
    reason = validate_reason(reason)
    targets = selected_targets(data, keys, action)
    evidence = review_evidence.validate(evidence, targets)
    stamp = {
        'fingerprint': data['fingerprint'], 'revision': data['revision'], 'date': data['date'],
        'keys': sorted(keys), 'action': action, 'reason': reason, 'snapshot': digest(targets),
        'evidence': digest(review_evidence.signature(evidence)),
        'shared_revision': data['shared_revision'],
    }
    return {
        'token': signing.dumps(stamp, salt='format-review-v1', compress=True),
        'count': sum(g['count'] for g in targets), 'groups': len(targets),
        'targets': [{'field': g['field'], 'value': g['value'], 'count': g['count']} for g in targets],
        'scope': data['context'], 'source_date': data['source_date'], 'action': action,
        'capture_count': len(evidence['captures']), 'checked_urls': evidence['checked_urls'],
    }


def commit(data, token, actor, evidence=None):
    try:
        stamp = signing.loads(token, salt='format-review-v1', max_age=600)
    except signing.BadSignature as exc:
        raise repository.ReviewConflict('미리보기가 만료되거나 유효하지 않습니다. 다시 확인하세요.') from exc
    if any(stamp.get(key) != data[key] for key in ('fingerprint', 'revision', 'date', 'shared_revision')):
        raise repository.ReviewConflict('검토 범위나 기준이 변경됐습니다. 다시 미리보기 하세요.')
    targets = selected_targets(data, stamp['keys'], stamp['action'])
    if digest(targets) != stamp['snapshot']:
        raise repository.ReviewConflict('미리보기 이후 수집 값 또는 대상이 변경됐습니다. 다시 확인하세요.')
    evidence = review_evidence.validate(evidence, targets)
    if stamp.get('evidence') != digest(review_evidence.signature(evidence)):
        raise repository.ReviewConflict('확인 근거가 변경됐습니다. 다시 미리보기 하세요.')
    return repository.save(data['context'], data['fingerprint'], data['revision'], stamp['action'],
                           targets, stamp['reason'], actor, date.fromisoformat(data['date']), evidence,
                           expected_shared_revision=data['shared_revision'])


def event_origin(data, event_id):
    for entry in [*data['history'], *data['registrations']]:
        if entry.get('event_id', entry.get('id')) == event_id:
            return entry['origin_fingerprint']
    raise ValueError('이 범위의 처리 이력을 찾을 수 없습니다.')


def merge_report(cursor, day, type_summary, reason_summary, table_summary, details):
    scopes = load_scopes()
    if not scopes:
        return
    from .services import _get_format_stats_raw
    stats, _ = _get_format_stats_raw(cursor, day)
    destinations = {(table['table'], retailer['retailer'])
                    for table in stats['tables'] for retailer in table.get('retailers', [])
                    if has_scope(scopes, table['table'], retailer['retailer'], day)}
    additions = []
    for table, retailer in sorted(destinations):
        data = inventory(cursor, day, table, retailer, scopes=scopes)
        context = data['context']
        policies = effective_policies(context, scopes, day)
        for group in data['groups']:
            policy = policies.get(group['key'])
            if not policy or policy.get('is_del'):
                continue
            for row in group['records']:
                if row['state'] not in ('registered_normal', 'error'):
                    continue
                additions.append({
                    'correction_type': 'format_check', 'table_name': context['source_table'],
                    'column_name': group['field'], 'record_id': row['id'],
                    'old_value': group['value'], 'new_value': group['value'],
                    'status': 'normal' if row['state'] == 'registered_normal' else 'error',
                    'memo': '값별 일괄 검토 · 원본 변경 없음', 'reason': policy['reason'],
                    'created_id': policy['actor'], 'retailer': data['retailer'], 'item': row['item'],
                    'rule_id': None, 'rule_name': '형식검증 운영 기준', 'detail_code': '',
                })
    if not additions:
        return
    def cell(row):
        return (row['table_name'].removeprefix('public.'), str(row['record_id']), row['column_name'])
    cells = {cell(row) for row in additions}
    details[:] = [row for row in details if row['correction_type'] != 'format_check' or cell(row) not in cells]
    details.extend(additions)
    format_details = [row for row in details if row['correction_type'] == 'format_check']
    type_summary['format_check'] = dict(Counter(row['status'] for row in format_details))
    for table in table_summary.values():
        table.pop('format_check', None)
    reason_summary[:] = [row for row in reason_summary if row['correction_type'] != 'format_check']
    reasons = Counter()
    for row in format_details:
        counts = table_summary.setdefault(row['table_name'], {}).setdefault('format_check', {})
        counts[row['status']] = counts.get(row['status'], 0) + 1
        if row['status'] == 'normal':
            reasons[row['reason']] += 1
    reason_summary.extend({'reason': reason, 'correction_type': 'format_check', 'count': count}
                          for reason, count in reasons.items())
