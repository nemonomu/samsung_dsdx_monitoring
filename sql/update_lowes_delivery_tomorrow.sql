-- SEA Lowes REF/LDY: accept the exact status "Delivery Tomorrow".
-- Run in the production database using DBeaver; commit if auto-commit is off.
-- Preserve existing delivery patterns. Safe to run repeatedly.
-- Application format-rule cache refreshes within 60 seconds.

UPDATE public.monitoring_format_templates
SET pattern = '^(' || pattern || '|Delivery Tomorrow)$'
WHERE name = 'SEA_APPLIANCE_LOWES_DELIVERY'
  AND pattern IS NOT NULL AND BTRIM(pattern) <> ''
  AND POSITION('Delivery Tomorrow' IN pattern) = 0;

UPDATE public.monitoring_format_rules
SET error_message = 'delivery_availability는 Delivery/Shipping 요일, 월 일, Delivery Tomorrow 또는 Delivery w/FREE Installation 형식이어야 합니다.'
WHERE table_name IN ('ref_retail_com', 'ldy_retail_com',
                     'public.ref_retail_com', 'public.ldy_retail_com')
  AND LOWER(BTRIM(account_name)) = 'lowes'
  AND column_name = 'delivery_availability'
  AND template_id IN (
      SELECT id FROM public.monitoring_format_templates
      WHERE name = 'SEA_APPLIANCE_LOWES_DELIVERY'
  );

SELECT r.table_name, r.account_name, r.column_name, t.pattern, r.error_message
FROM public.monitoring_format_rules r
JOIN public.monitoring_format_templates t ON t.id = r.template_id
WHERE t.name = 'SEA_APPLIANCE_LOWES_DELIVERY'
  AND LOWER(BTRIM(r.account_name)) = 'lowes'
  AND r.column_name = 'delivery_availability';
