"""Compare only the source fields that affect the D-DAY collection counts."""
import hashlib
import json

from psycopg2 import Error

from apps.common.monitoring_cache import _backend, _root


def batch_revision(column, *, page_type=False, extra_fields=()):
    page = ", LOWER(BTRIM(source.page_type))" if page_type else ""
    extra = ''.join(', ' + field for field in extra_fields)
    return f"""md5(COALESCE(string_agg(json_build_array(
        source.id, source.batch_id, CAST(source.{column} AS TEXT),
        source.main_rank IS NOT NULL, source.bsr_rank IS NOT NULL{page}{extra}
    )::text, ',' ORDER BY source.id), ''))"""


class CollectionReads:
    def __init__(self, day, cursor, cache=None):
        self.day = day
        self.cursor = cursor
        self.cache = cache if cache is not None else _backend(_root())
        self.reused = 0
        self.source_reads = 0
        self.fresh = {}

    def read(self, fetch, source, scope, complete):
        if complete:
            key = 'dday-counts:v2:' + hashlib.sha256(
                json.dumps([str(self.day), scope], ensure_ascii=False).encode('utf-8')).hexdigest()
            try:
                saved = self.cache.get(key)
                if saved and saved[0] == fetch(self.cursor, source, self.day, revision_only=True):
                    self.reused += 1
                    return saved[1]
                values = fetch(self.cursor, source, self.day, with_revision=True)
                self.source_reads += 1
                self.fresh[scope] = (key, values[-1], values[:-1])
                return values[:-1]
            except (Error, OSError):
                pass  # The existing source-count query can still succeed.

        self.source_reads += 1
        return fetch(self.cursor, source, self.day)

    def store(self, countries):
        for panel in countries:
            for row in panel['retailers']:
                item = self.fresh.get((panel['country'], row['product'], row['retailer']))
                if item:
                    key, revision, counts = item
                    if row['status'] == 'received' and row['count'] and row['batch_id']:
                        self.cache.set(key, (revision, counts), timeout=86400)
                    else:
                        self.cache.delete(key)
