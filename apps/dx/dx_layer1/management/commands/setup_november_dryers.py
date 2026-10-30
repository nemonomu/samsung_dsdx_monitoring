"""Register only OTTO/Liverpool/ECI dryers; never modify source records."""
from django.core.management.base import BaseCommand, CommandError
from apps.common.db import dx_connection, dx_table
from apps.common.seib_retail import SEIB_SOURCE_CONFIG
from apps.common.sem_retail import SEM_SOURCE_CONFIG, get_sem_table_columns
from apps.common.dryer_onboarding import REQUIRED_COLUMNS
from apps.dx.dx_layer2.seg_sources import SEG_SOURCE_CONFIG, get_seg_table_columns


def targets():
    # SEG/SEM keep their existing country windows. ECI has its own KST window.
    yield 'SEG', 'OTTO', SEG_SOURCE_CONFIG['seg_ldy_dryer'], get_seg_table_columns('seg_ldy_dryer'), 300, '07:00~12:00'
    yield 'SEM', 'Liverpool', SEM_SOURCE_CONFIG['sem_ldy_dryer'], get_sem_table_columns('sem_ldy_dryer'), 270, '09:00~13:30'
    yield 'SEIB', 'ECI', SEIB_SOURCE_CONFIG['seib_ldy_dryer'], SEIB_SOURCE_CONFIG['seib_ldy_dryer']['columns'], 60, '08:00~09:00'



def register(cursor):
    schedule = 'public.' + dx_table('monitoring_collection_schedule')
    columns = 'public.' + dx_table('monitoring_retail_columns')
    categories = 'public.' + dx_table('monitoring_null_category')
    groups = 'public.' + dx_table('monitoring_null_group')
    checks = 'public.' + dx_table('monitoring_null_column')
    for country, retailer, source, fields, duration, window in targets():
        key = source['source_key']
        check_type = country.lower() + '_retail'
        description = f'{country} {retailer} LDY_DRYER; D; KST {window}; operating from 2026-11-01; earlier rows are preview only'
        # Verify the existing source schema before registering any monitoring settings.
        cursor.execute(f"SELECT {', '.join(fields)} FROM {source['table_name']} LIMIT 0")
        cursor.execute(f"""UPDATE {schedule}
            SET check_name=%s, check_group='Retail', schedule_type='daily', schedule_value=NULL,
                us_start_hour=NULL, expected_count=0, country=%s, collection_duration_min=%s,
                view_table_name=%s, sort_order=6, description=%s, is_active=TRUE, is_del=0,
                updated_at=NOW(), updated_id='setup_november_dryers'
            WHERE check_type=%s AND category=%s AND LOWER(BTRIM(retailer))=%s""",
                       (source['display_name'], country, duration, source['table_name'], description, check_type, source['category'], retailer.lower()))
        if not cursor.rowcount:
            cursor.execute(f"""INSERT INTO {schedule}
                (check_group,check_type,check_name,category,schedule_type,retailer,expected_count,country,
                 collection_duration_min,view_table_name,sort_order,description,is_active,is_del,
                 created_at,created_id,updated_at,updated_id)
                VALUES ('Retail',%s,%s,%s,'daily',%s,0,%s,%s,%s,6,%s,TRUE,0,
                        NOW(),'setup_november_dryers',NOW(),'setup_november_dryers')""",
                           (check_type, source['display_name'], source['category'], retailer, country, duration, source['table_name'], description))
        for column in fields:
            required = column in REQUIRED_COLUMNS
            duplicate = column == 'item' or (country == 'SEG' and column == 'sku')
            editable = required or column in ('original_sku_price', 'savings')
            cursor.execute(f"""UPDATE {columns}
                SET duplicate_key=%s, skip_missing_check=%s, is_editable=%s, is_active=TRUE, is_del=FALSE,
                    updated_at=NOW(), updated_id='setup_november_dryers'
                WHERE product_line=%s AND LOWER(BTRIM(retailer))=%s AND column_name=%s""",
                           (duplicate, not required, editable, key, retailer.lower(), column))
            if not cursor.rowcount:
                cursor.execute(f"""INSERT INTO {columns}
                    (product_line,column_name,retailer,duplicate_key,skip_missing_check,is_editable,
                     is_active,is_del,created_at,created_id,updated_at,updated_id)
                    VALUES (%s,%s,%s,%s,%s,%s,TRUE,FALSE,NOW(),'setup_november_dryers',NOW(),'setup_november_dryers')""",
                               (key, column, retailer, duplicate, not required, editable))
        # Shared category metadata belongs to existing retailers too: do not rewrite it.
        cursor.execute(f'SELECT id FROM {categories} WHERE category_name=%s', (source['section_code'],))
        row = cursor.fetchone()
        if not row:
            cursor.execute(f"""INSERT INTO {categories}
                (category_name,display_name,display_order,has_retailer,is_active,is_del,created_at,created_id)
                VALUES (%s,%s,%s,TRUE,TRUE,FALSE,NOW(),'setup_november_dryers') RETURNING id""",
                           (source['section_code'], source['display_name'], 40))
            row = cursor.fetchone()
        category_id = row[0]
        check_name = retailer.lower() + '_' + key
        cursor.execute(f"""UPDATE {groups} SET display_name=%s, table_name=%s, date_column='crawl_datetime',
            display_order=3,is_active=TRUE,is_del=FALSE,updated_at=NOW(),updated_id='setup_november_dryers'
            WHERE category_id=%s AND check_name=%s RETURNING id""",
                       (retailer, source['table_name'], category_id, check_name))
        row = cursor.fetchone()
        if not row:
            cursor.execute(f"""INSERT INTO {groups}
                (category_id,check_name,display_name,table_name,date_column,display_order,is_active,is_del,created_at,created_id)
                VALUES (%s,%s,%s,%s,'crawl_datetime',3,TRUE,FALSE,NOW(),'setup_november_dryers') RETURNING id""",
                           (category_id, check_name, retailer, source['table_name']))
            row = cursor.fetchone()
        group_id = row[0]
        cursor.execute(f"""UPDATE {checks} SET is_active=FALSE,updated_at=NOW(),updated_id='setup_november_dryers'
            WHERE group_id=%s AND NOT (check_column = ANY(%s))""", (group_id, list(REQUIRED_COLUMNS)))
        for column in REQUIRED_COLUMNS:
            display = '|'.join(dict.fromkeys(('id', 'crawl_datetime', 'item', 'sku', 'retailer_sku_name', column,
                                              'star_rating', 'count_of_star_ratings', 'count_of_reviews',
                                              'final_sku_price', 'original_sku_price', 'savings', 'product_url')))
            cursor.execute(f"""UPDATE {checks} SET check_type='both',display_columns=%s,query_columns=%s,
                query_days=0,is_active=TRUE,is_del=FALSE,updated_at=NOW(),updated_id='setup_november_dryers'
                WHERE group_id=%s AND check_column=%s""", (display, display, group_id, column))
            if not cursor.rowcount:
                cursor.execute(f"""INSERT INTO {checks}
                    (group_id,check_column,check_type,display_columns,query_columns,query_days,
                     is_active,is_del,created_at,created_id)
                    VALUES (%s,%s,'both',%s,%s,0,TRUE,FALSE,NOW(),'setup_november_dryers')""", (group_id, column, display, display))
        cursor.execute(f'SELECT COUNT(*) FROM {checks} WHERE group_id=%s AND is_active AND NOT is_del', (group_id,))
        if cursor.fetchone()[0] != 11:
            raise CommandError(f'{key}: expected 11 NULL fields; registration rolled back.')


class Command(BaseCommand):
    help = 'Register three November dryers for Layer1, NULL and duplicates. No format/cross-field rules.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Validate registration then roll back all settings.')

    def handle(self, *args, **options):
        with dx_connection() as (connection, cursor):
            register(cursor)
            if options['dry_run']:
                connection.rollback()
            else:
                connection.commit()
        self.stdout.write(self.style.SUCCESS('Dryer settings validated and rolled back.' if options['dry_run'] else 'Three dryer schedules and 33 NULL fields registered. Source data unchanged.'))
