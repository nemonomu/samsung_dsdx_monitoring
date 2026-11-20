"""Register the existing ECI rule set for SEIB REF and LDY."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.common.db import dx_connection
from apps.common.seib_retail import ECI_APPLIANCE_PRODUCTS, get_seib_source
from apps.dx.dx_layer3.cross_field.seib_services import load_active_rules, rule_definitions


def register(cursor):
    definitions = rule_definitions('ECI')
    cursor.execute("SET LOCAL lock_timeout = '5s'")
    cursor.execute('LOCK TABLE public.monitoring_validation_rules IN SHARE ROW EXCLUSIVE MODE')
    for product in ECI_APPLIANCE_PRODUCTS:
        source = get_seib_source(product)
        for order, (key, definition) in enumerate(definitions.items(), 1):
            name, field1, field2, message, fields = definition
            code = f'{product}_eci_{key}'
            cursor.execute("""
                INSERT INTO public.monitoring_validation_rules
                    (rule_type, section_code, section_name, detail_code, detail_name, table_name,
                     date_column, product_line, retailer, field1, field2, validation_type,
                     check_type, error_message, display_columns, select_fields, query, query_detail,
                     sort_order, is_active, created_at, created_id)
                SELECT 'crossfield', %s, %s, %s, %s, %s, 'crawl_datetime', %s, 'ECI', %s, %s, %s,
                       'cross_field', %s, %s, %s, '', '', %s, TRUE, NOW(), 'setup_seib_eci_crossfield'
                WHERE NOT EXISTS (
                    SELECT 1 FROM public.monitoring_validation_rules
                    WHERE rule_type = 'crossfield' AND section_code = %s AND table_name = %s
                      AND detail_code = %s AND LOWER(BTRIM(retailer)) = 'eci'
                )
            """, (source['section_code'], source['display_name'], code, name, source['table_name'],
                  product, field1, field2, key, message, fields, fields, order * 10,
                  source['section_code'], source['table_name'], code))
        rules = [rule['rule_key'] for rule in load_active_rules(cursor, source) if rule['retailers'] == ['ECI']]
        if sorted(rules) != sorted(definitions):
            raise CommandError(f'{product}: expected exactly four active ECI rules. Registration rolled back.')


class Command(BaseCommand):
    help = 'Register the eight ECI REF/LDY cross-field rules on the production server.'

    def handle(self, *args, **options):
        if settings.DEBUG:
            self.stdout.write('ECI cross-field registration skipped outside the production server.')
            return
        with dx_connection(connect_timeout=5) as (connection, cursor):
            register(cursor)
            connection.commit()
        self.stdout.write(self.style.SUCCESS('ECI REF and LDY cross-field rules registered.'))
