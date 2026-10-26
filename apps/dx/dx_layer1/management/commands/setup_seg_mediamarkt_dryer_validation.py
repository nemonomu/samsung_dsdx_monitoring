"""Register the six agreed Mediamarkt dryer cross-field rules, idempotently."""
from django.core.management.base import BaseCommand, CommandError

from apps.common.db import dx_connection
from apps.dx.dx_layer3.cross_field.seg_services import SEG_RULE_SPECS

RULE_KEYS = (
    'rating_count_presence', 'review_count_match', 'final_original_price',
    'savings_missing', 'original_missing', 'final_missing',
)


def register_rules(cursor):
    # Match load_active_seg_rules: SEG cross-field metadata uses this registry.
    # Format approvals use their separate environment-scoped review storage.
    table = 'public.monitoring_validation_rules'
    for index, key in enumerate(RULE_KEYS, 1):
        spec = SEG_RULE_SPECS[key]
        code = 'seg_ldy_dryer_mediamarkt_' + key
        fields = '|'.join(spec['display_fields'])
        values = ('SEG LDY_DRYER', spec['detail_name'], 'crawl_datetime',
                  'seg_ldy_dryer', spec['field1'], spec.get('field2'), key,
                  spec['error_message'], fields, index * 10)
        identity = ('seg_ldy_dryer_retail', 'dx_seg.dx_seg_ldy_dryer_retail', code)
        cursor.execute(f"""
            UPDATE {table}
            SET section_name=%s, detail_name=%s, date_column=%s, product_line=%s,
                field1=%s, field2=%s, validation_type=%s, error_message=%s,
                select_fields=%s, sort_order=%s, is_active=TRUE
            WHERE rule_type='crossfield' AND section_code=%s AND table_name=%s
              AND detail_code=%s AND LOWER(BTRIM(retailer))='mediamarkt'
        """, (*values, *identity))
        cursor.execute(f"""
            INSERT INTO {table}
                (section_name, detail_name, date_column, product_line, field1,
                 field2, validation_type, error_message, select_fields, sort_order,
                 section_code, table_name, detail_code, rule_type, retailer,
                 is_active, query, created_at, created_id)
            SELECT %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                   'crossfield','Mediamarkt',TRUE,
                   'Application-enforced SEG rule; copy query generated at runtime.',
                   NOW(),'setup_seg_mediamarkt_dryer_validation'
            WHERE NOT EXISTS (
                SELECT 1 FROM {table} WHERE rule_type='crossfield'
                  AND section_code=%s AND table_name=%s AND detail_code=%s
                  AND LOWER(BTRIM(retailer))='mediamarkt')
        """, (*values, *identity, *identity))
    cursor.execute(f"""
        SELECT validation_type, COUNT(*) FROM {table}
        WHERE rule_type='crossfield' AND section_code='seg_ldy_dryer_retail'
          AND table_name='dx_seg.dx_seg_ldy_dryer_retail'
          AND LOWER(BTRIM(retailer))='mediamarkt' AND is_active=TRUE
        GROUP BY validation_type
    """)
    counts = dict(cursor.fetchall())
    if counts != dict.fromkeys(RULE_KEYS, 1):
        raise CommandError(f'Expected exactly six unique Mediamarkt dryer rules; got {counts!r}.')
    return counts


class Command(BaseCommand):
    help = 'Register six SEG Mediamarkt dryer cross-field rules without changing source data.'

    def handle(self, *args, **options):
        with dx_connection() as (connection, cursor):
            register_rules(cursor)
            connection.commit()
        self.stdout.write(self.style.SUCCESS('SEG Mediamarkt LDY_DRYER: six cross-field rules registered.'))
