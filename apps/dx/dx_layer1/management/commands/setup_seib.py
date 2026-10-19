"""Idempotent SEIB registration for Layer 1 and NULL validation only."""
from django.core.management.base import BaseCommand, CommandError
from apps.common.db import dx_connection, dx_table
from apps.common.seib_retail import SEIB_SOURCE_CONFIG, RETAILER


def register(cursor):
    schedule = 'public.' + dx_table('monitoring_collection_schedule')
    columns = 'public.' + dx_table('monitoring_retail_columns')
    categories = 'public.' + dx_table('monitoring_null_category')
    groups = 'public.' + dx_table('monitoring_null_group')
    checks = 'public.' + dx_table('monitoring_null_column')
    for order, (key, source) in enumerate(SEIB_SOURCE_CONFIG.items(), 30):
        # us_start_hour is deliberately unset: SEIB's fixed KST window is not a US clock.
        description = '스페인 MediaMarkt 당일(D) 수집 · KST 01:00~04:00 · 최초 2026-10-18'
        cursor.execute(f"""UPDATE {schedule}
            SET check_name=%s, check_group='Retail', schedule_type='daily', schedule_value=NULL,
                us_start_hour=NULL, expected_count=0, country='SEIB', collection_duration_min=180,
                view_table_name=%s, sort_order=6, description=%s, is_active=TRUE, is_del=0,
                updated_at=NOW(), updated_id='setup_seib'
            WHERE check_type='seib_retail' AND category=%s AND LOWER(BTRIM(retailer))=%s""",
                       (source['display_name'], source['table_name'], description, source['category'], RETAILER.lower()))
        if not cursor.rowcount:
            cursor.execute(f"""INSERT INTO {schedule}
                (check_group,check_type,check_name,category,schedule_type,retailer,expected_count,country,
                 collection_duration_min,view_table_name,sort_order,description,is_active,is_del,
                 created_at,created_id,updated_at,updated_id)
                VALUES ('Retail','seib_retail',%s,%s,'daily',%s,0,'SEIB',180,%s,6,%s,TRUE,0,
                        NOW(),'setup_seib',NOW(),'setup_seib')""",
                           (source['display_name'], source['category'], RETAILER, source['table_name'], description))
        for column in source['columns']:
            required = column in source['required_columns']
            editable = required or column in ('original_sku_price', 'savings')
            cursor.execute(f"""UPDATE {columns}
                SET skip_missing_check=%s, is_editable=%s, is_active=TRUE, is_del=FALSE,
                    updated_at=NOW(), updated_id='setup_seib'
                WHERE product_line=%s AND LOWER(BTRIM(retailer))=%s AND column_name=%s""",
                           (not required, editable, key, RETAILER.lower(), column))
            if not cursor.rowcount:
                cursor.execute(f"""INSERT INTO {columns}
                    (product_line,column_name,retailer,duplicate_key,skip_missing_check,is_editable,
                     is_active,is_del,created_at,created_id,updated_at,updated_id)
                    VALUES (%s,%s,%s,FALSE,%s,%s,TRUE,FALSE,NOW(),'setup_seib',NOW(),'setup_seib')""",
                               (key, column, RETAILER, not required, editable))
        cursor.execute(f"""UPDATE {categories} SET display_name=%s, display_order=%s,
            has_retailer=TRUE, is_active=TRUE, is_del=FALSE WHERE category_name=%s RETURNING id""",
                       (source['display_name'], order, source['section_code']))
        row = cursor.fetchone()
        if not row:
            cursor.execute(f"""INSERT INTO {categories}
                (category_name,display_name,display_order,has_retailer,is_active,is_del,created_at,created_id)
                VALUES (%s,%s,%s,TRUE,TRUE,FALSE,NOW(),'setup_seib') RETURNING id""",
                           (source['section_code'], source['display_name'], order))
            row = cursor.fetchone()
        category_id = row[0]
        check_name = 'mediamarkt_' + key
        cursor.execute(f"""UPDATE {groups} SET display_name=%s, table_name=%s, date_column='crawl_datetime',
            display_order=1,is_active=TRUE,is_del=FALSE,updated_at=NOW(),updated_id='setup_seib'
            WHERE category_id=%s AND check_name=%s RETURNING id""",
                       (RETAILER, source['table_name'], category_id, check_name))
        row = cursor.fetchone()
        if not row:
            cursor.execute(f"""INSERT INTO {groups}
                (category_id,check_name,display_name,table_name,date_column,display_order,is_active,is_del,created_at,created_id)
                VALUES (%s,%s,%s,%s,'crawl_datetime',1,TRUE,FALSE,NOW(),'setup_seib') RETURNING id""",
                           (category_id, check_name, RETAILER, source['table_name']))
            row = cursor.fetchone()
        group_id = row[0]
        cursor.execute(f"""UPDATE {checks} SET is_active=FALSE,updated_at=NOW(),updated_id='setup_seib'
            WHERE group_id=%s AND NOT (check_column = ANY(%s))""", (group_id, list(source['required_columns'])))
        for column in source['required_columns']:
            display = '|'.join(dict.fromkeys(('id', 'crawl_datetime', 'item', 'sku', 'retailer_sku_name', column,
                                              'star_rating', 'count_of_star_ratings', 'count_of_reviews',
                                              'final_sku_price', 'original_sku_price', 'savings', 'product_url')))
            cursor.execute(f"""UPDATE {checks} SET check_type='both',display_columns=%s,query_columns=%s,
                query_days=0,is_active=TRUE,is_del=FALSE,updated_at=NOW(),updated_id='setup_seib'
                WHERE group_id=%s AND check_column=%s""", (display, display, group_id, column))
            if not cursor.rowcount:
                cursor.execute(f"""INSERT INTO {checks}
                    (group_id,check_column,check_type,display_columns,query_columns,query_days,
                     is_active,is_del,created_at,created_id)
                    VALUES (%s,%s,'both',%s,%s,0,TRUE,FALSE,NOW(),'setup_seib')""", (group_id, column, display, display))
        cursor.execute(f'SELECT COUNT(*) FROM {checks} WHERE group_id=%s AND is_active AND NOT is_del', (group_id,))
        if cursor.fetchone()[0] != 11:
            raise CommandError(f'{key}: expected 11 NULL fields; registration rolled back.')


class Command(BaseCommand):
    help = 'Register SEIB MediaMarkt TV/REF/LDY/LDY_DRYER collection and NULL monitoring.'

    def handle(self, *args, **options):
        with dx_connection() as (connection, cursor):
            register(cursor)
            connection.commit()
        self.stdout.write(self.style.SUCCESS('SEIB: 4 schedules and 44 NULL fields registered. Source data unchanged.'))
