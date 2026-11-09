"""Conservative source pruning for automatic review history, never approvals."""
from concurrent.futures import ThreadPoolExecutor

from apps.common.null_review_evidence import EVIDENCE_TABLE, POLICY_VERSION


# Bound the total concurrency within each application worker, even when several
# dates are requested together. Each task owns and closes its DB connection.
_POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix='null-review')


class ReviewScope:
    def __init__(self, scopes):
        self.scopes = scopes

    def __call__(self, table, retailer=None):
        names = self.scopes.get(str(table).removeprefix('public.'), set())
        return bool(names) if retailer is None else str(retailer or '').strip().casefold() in names

    def partitions(self):
        groups = [{}, {}, {}]
        for table, names in sorted(self.scopes.items(), key=lambda item: (-len(item[1]), item[0])):
            group = min(groups, key=lambda g: sum(len(v) for v in g.values()))
            group[table] = names
        return [ReviewScope(group) for group in groups if group]


def load_scope(cursor, inspection_date):
    # Include revoked, same-day and ineligible decisions too. The existing
    # matcher must decide precedence and cancellations; this only skips scopes
    # with no evidence at all and cannot introduce a new automatic approval.
    cursor.execute(f'''SELECT DISTINCT table_name, retailer
                       FROM {EVIDENCE_TABLE}
                       WHERE policy_version = %s AND inspection_date <= %s''',
                   [POLICY_VERSION, inspection_date])
    scopes = {}
    for table, retailer in cursor.fetchall():
        scopes.setdefault(str(table).removeprefix('public.'), set()).add(
            str(retailer or '').strip().casefold())

    return ReviewScope(scopes)


def collect(scope, inspection_date, *, strict):
    from apps.common.db import dx_connection
    from apps.common.monitoring_cache import _has_error
    from .services import get_null_stats

    def read(part):
        with dx_connection() as (_, cursor):
            validation, _ = get_null_stats(cursor, inspection_date, review_filter=part)
            if strict and _has_error(validation):
                raise RuntimeError('NULL 자동확인 이력을 완전히 조회하지 못했습니다.')
            return validation.get('auto_null_reviews', [])

    futures = [_POOL.submit(read, part) for part in scope.partitions()]
    try:
        return [row for future in futures for row in future.result()]
    except Exception:
        for future in futures:
            future.cancel()
        raise
