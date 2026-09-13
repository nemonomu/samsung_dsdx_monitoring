-- Existing installations: run this file in PostgreSQL/DBeaver.
-- Only changes the Lowes REF capacity rule; never changes collected data.
-- The shared Lowes LDY template and decimal grammar stay unchanged.
-- After COMMIT, the application rule cache refreshes within 60 seconds.
BEGIN;

DO $migration$
DECLARE
    target_rule_id integer;
    capacity_template_id integer;
    capacity_pattern text := $capacity$^(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?: Cu\.Feet|\s*[Ll][Ii][Tt][Ee][Rr][Ss]?)$$capacity$;
BEGIN
    -- Fail instead of silently updating no rule or multiple rules.
    SELECT id INTO STRICT target_rule_id
    FROM public.monitoring_format_rules
    WHERE table_name = 'ref_retail_com'
      AND column_name = 'ref_capacity'
      AND account_name = 'Lowes'
      AND is_active IS TRUE AND is_del IS FALSE
    FOR UPDATE;

    SELECT id INTO capacity_template_id
    FROM public.monitoring_format_templates
    WHERE name = 'SEA_APPLIANCE_LOWES_REF_CAPACITY';

    IF capacity_template_id IS NULL THEN
        INSERT INTO public.monitoring_format_templates (
            name, description, check_type, pattern, is_active,
            created_id, created_at, updated_id, updated_at
        ) VALUES (
            'SEA_APPLIANCE_LOWES_REF_CAPACITY',
            'Lowes refrigerator capacity: Cu.Feet or Liter (optional spacing)',
            'regex', capacity_pattern, TRUE,
            'lowes_ref_liter', NOW(), 'lowes_ref_liter', NOW()
        ) RETURNING id INTO capacity_template_id;
    ELSE
        UPDATE public.monitoring_format_templates
        SET pattern = capacity_pattern, check_type = 'regex', is_active = TRUE,
            description = 'Lowes refrigerator capacity: Cu.Feet or Liter (optional spacing)',
            updated_id = 'lowes_ref_liter', updated_at = NOW()
        WHERE id = capacity_template_id;
    END IF;

    UPDATE public.monitoring_format_rules
    SET template_id = capacity_template_id,
        error_message = '용량은 "숫자 Cu.Feet" 또는 "숫자 Liter" 형식이어야 합니다.',
        updated_id = 'lowes_ref_liter', updated_at = NOW()
    WHERE id = target_rule_id;
END;
$migration$;

COMMIT;

-- Expected: one Lowes ref_capacity rule with the new dedicated template.
SELECT r.table_name, r.account_name, r.column_name, t.name, t.pattern
FROM public.monitoring_format_rules r
JOIN public.monitoring_format_templates t ON t.id = r.template_id
WHERE r.table_name = 'ref_retail_com' AND r.account_name = 'Lowes'
  AND r.column_name = 'ref_capacity' AND r.is_active IS TRUE AND r.is_del IS FALSE;
