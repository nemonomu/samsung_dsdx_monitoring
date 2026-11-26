"""Reuse verified D-DAY counts using the source database's completion revisions."""
import hashlib
import json
import logging

from django.conf import settings
from django.core.cache import cache
from psycopg2 import Error

from apps.common.db import dx_connection


logger = logging.getLogger(__name__)


def completed_revisions(day):
    if not getattr(settings, 'DX_DDAY_COLLECTION_REVISIONS', False):
        return {}
    try:
        with dx_connection(connect_timeout=3) as (_, cursor):
            cursor.execute("SET LOCAL statement_timeout = '1000ms'")
            cursor.execute("""
                SELECT country, product, retailer, revision
                FROM public.dx_dday_collection_revision
                WHERE source_date = %s AND completed AND revision IS NOT NULL
            """, [day])
            return {(country, product, retailer): revision
                    for country, product, retailer, revision in cursor.fetchall()}
    except (Error, OSError):
        logger.warning('D-DAY completion revisions unavailable; reading source counts', exc_info=True)
        return {}


class CollectionReads:
    def __init__(self, day):
        self.day = day
        self.revisions = completed_revisions(day)
        self.keys = {scope: 'dday-counts:v1:' + hashlib.sha256(
            json.dumps([str(day), scope, str(revision)], ensure_ascii=False).encode('utf-8')
        ).hexdigest() for scope, revision in self.revisions.items()}
        self.cached = cache.get_many(self.keys.values()) if self.keys else {}
        self.fresh = {}

    def read(self, fetch, source, scope):
        key = self.keys.get(scope)
        if key in self.cached:
            return self.cached[key]
        with dx_connection() as (_, cursor):
            counts = fetch(cursor, source, self.day)
        if key:
            self.fresh[scope] = counts
        return counts

    def store(self, countries):
        normal = {(panel['country'], row['product'], row['retailer'])
                  for panel in countries for row in panel['retailers']
                  if row['status'] == 'received' and row['count'] and row['batch_id']}
        to_verify = self.fresh.keys() & normal
        if to_verify:
            latest = completed_revisions(self.day)
            entries = {self.keys[scope]: self.fresh[scope] for scope in to_verify
                       if latest.get(scope) == self.revisions[scope]}
            if entries:
                cache.set_many(entries, timeout=86400)
