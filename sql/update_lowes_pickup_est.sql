-- Allow the observed optional (Est.) suffix on SEA Lowes REF/LDY pickup dates.
-- Only format templates and error descriptions change; source data is untouched.
-- Idempotent. Application rule caches refresh within 60 seconds.
BEGIN;

DO $migration$
DECLARE
    product text;
    target_rule_id integer;
    target_template_id integer;
    pickup_pattern text := $pattern$^Pickup Ready (Today|Tomorrow|by (Mon|Tue|Wed|Thu|Fri|Sat|Sun), (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) ([1-9]|[12][0-9]|3[01])( \(Est\.\))?)$$pattern$;
BEGIN
    FOREACH product IN ARRAY ARRAY['ref', 'ldy'] LOOP
        SELECT r.id, t.id INTO STRICT target_rule_id, target_template_id
        FROM public.monitoring_format_rules r
        JOIN public.monitoring_format_templates t ON t.id = r.template_id
        WHERE r.table_name = product || '_retail_com'
          AND r.account_name = 'Lowes'
          AND r.column_name = 'pick_up_availability'
          AND r.is_active IS TRUE AND r.is_del IS FALSE
          AND t.name = 'SEA_APPLIANCE_LOWES_' || UPPER(product) || '_PICKUP'
          AND t.is_active IS TRUE
        FOR UPDATE OF r, t;

        UPDATE public.monitoring_format_templates
        SET pattern = pickup_pattern,
            description = 'Lowes ' || UPPER(product) || ' pickup date with optional (Est.), Pickup Ready Today or Pickup Ready Tomorrow',
            updated_id = 'lowes_pickup_est', updated_at = NOW()
        WHERE id = target_template_id;

        UPDATE public.monitoring_format_rules
        SET error_message = 'pick_up_availability는 Pickup Ready Today, Pickup Ready Tomorrow 또는 Pickup Ready by 요일, 월 일 형식이며 날짜 뒤 (Est.)는 선택적으로 허용합니다.',
            updated_id = 'lowes_pickup_est', updated_at = NOW()
        WHERE id = target_rule_id;
    END LOOP;
END;
$migration$;

COMMIT;
