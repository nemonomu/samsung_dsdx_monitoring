-- Disable TSE Lazada and PowerBuy monitoring without deleting source data.
--
-- The application also excludes both retailers defensively. This script
-- retires the database configuration created by the former seed scripts so
-- Layer 2-4 configuration APIs and jobs do not discover them independently.

BEGIN;

UPDATE public.monitoring_retail_columns
SET is_active = FALSE,
    is_del = TRUE,
    updated_id = 'disable_tse_lazada_powerbuy',
    updated_at = NOW(),
    memo = CONCAT_WS(
        ' | ', NULLIF(memo, ''),
        'TSE Lazada/PowerBuy monitoring disabled'
    )
WHERE product_line IN ('tse_tv', 'tse_ref', 'tse_ldy')
  AND LOWER(BTRIM(retailer)) IN ('lazada', 'powerbuy')
  AND (is_active IS TRUE OR COALESCE(is_del, FALSE) IS FALSE);

UPDATE public.monitoring_validation_rules
SET is_active = FALSE
WHERE rule_type = 'crossfield'
  AND section_code IN (
      'tse_tv_retail', 'tse_ref_retail', 'tse_ldy_retail'
  )
  AND LOWER(BTRIM(retailer)) IN ('lazada', 'powerbuy')
  AND is_active IS TRUE;

COMMIT;

-- monitoring_retail_columns is cached for at most 60 seconds by the app.
