-- Run manually in PostgreSQL/DBeaver. Only updates SEA REF / Lowes rules.
-- Source data and the shared LDY templates are unchanged.
-- Idempotent; the application rule cache refreshes within 60 seconds.
BEGIN;

DO $migration$
DECLARE
    rule_seed record;
    target_rule_id integer;
    target_template_id integer;
BEGIN
    FOR rule_seed IN
        SELECT * FROM (VALUES
            ('discount_type', 'SEA_APPLIANCE_LOWES_REF_DISCOUNT',
             $pattern$^(Exclusive Appliance Bundle|Unlock Member Deal|Get [$][1-9][0-9]* Off In Cart On Purchase Of [1-9][0-9]* Items|[$][1-9][0-9]* Instant Savings|Buy [1-9][0-9]*[+] Get ([1-9][0-9]?|100)% Off|Buy More, Save More|Buy [1-9][0-9]* And Get [1-9][0-9]*)$$pattern$,
             'Lowes REF discount phrases including Buy More and Buy N And Get N',
             'discount_type은 허용된 Lowes 할인 문구여야 하며 금액과 수량은 양의 정수, 할인율은 1~100 정수여야 합니다.'),
            ('pick_up_availability', 'SEA_APPLIANCE_LOWES_REF_PICKUP',
             $pattern$^Pickup Ready (Today|Tomorrow|by (Mon|Tue|Wed|Thu|Fri|Sat|Sun), (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) ([1-9]|[12][0-9]|3[01])( \(Est\.\))?)$$pattern$,
             'Lowes REF pickup date with optional (Est.), Pickup Ready Today or Pickup Ready Tomorrow',
             'pick_up_availability는 Pickup Ready Today, Pickup Ready Tomorrow 또는 Pickup Ready by 요일, 월 일 형식이며 날짜 뒤 (Est.)는 선택적으로 허용합니다.')
        ) AS seed(column_name, template_name, pattern, description, error_message)
    LOOP
        SELECT id INTO STRICT target_rule_id
        FROM public.monitoring_format_rules
        WHERE table_name = 'ref_retail_com' AND account_name = 'Lowes'
          AND column_name = rule_seed.column_name
          AND is_active IS TRUE AND is_del IS FALSE
        FOR UPDATE;

        SELECT id INTO target_template_id
        FROM public.monitoring_format_templates
        WHERE name = rule_seed.template_name;

        IF target_template_id IS NULL THEN
            INSERT INTO public.monitoring_format_templates (
                name, description, check_type, pattern, is_active,
                created_id, created_at, updated_id, updated_at
            ) VALUES (
                rule_seed.template_name, rule_seed.description, 'regex', rule_seed.pattern, TRUE,
                'lowes_ref_formats', NOW(), 'lowes_ref_formats', NOW()
            ) RETURNING id INTO target_template_id;
        ELSE
            UPDATE public.monitoring_format_templates
            SET pattern = rule_seed.pattern, check_type = 'regex', is_active = TRUE,
                description = rule_seed.description,
                updated_id = 'lowes_ref_formats', updated_at = NOW()
            WHERE id = target_template_id;
        END IF;

        UPDATE public.monitoring_format_rules
        SET template_id = target_template_id, error_message = rule_seed.error_message,
            updated_id = 'lowes_ref_formats', updated_at = NOW()
        WHERE id = target_rule_id;
    END LOOP;
END;
$migration$;

COMMIT;

SELECT r.table_name, r.account_name, r.column_name, t.name, t.pattern
FROM public.monitoring_format_rules r
JOIN public.monitoring_format_templates t ON t.id = r.template_id
WHERE r.table_name = 'ref_retail_com' AND r.account_name = 'Lowes'
  AND r.column_name IN ('discount_type', 'pick_up_availability')
  AND r.is_active IS TRUE AND r.is_del IS FALSE;
