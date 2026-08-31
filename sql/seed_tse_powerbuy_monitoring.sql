-- Idempotent TSE TV PowerBuy monitoring seed.
--
-- PowerBuy follows the active Homepro TV collection-column and cross-field
-- policies. Layer 1 discovers the retailer directly from collected data;
-- this seed enables the DB-configured Layer 2, Layer 3, and Layer 4 paths.

BEGIN;

INSERT INTO public.monitoring_retail_columns (
    product_line,
    column_name,
    retailer,
    duplicate_key,
    skip_missing_check,
    is_editable,
    related_columns,
    is_active,
    is_del,
    created_id,
    updated_id,
    created_at,
    updated_at,
    memo
)
SELECT
    source.product_line,
    source.column_name,
    'powerbuy',
    source.duplicate_key,
    source.skip_missing_check,
    source.is_editable,
    source.related_columns,
    TRUE,
    FALSE,
    'seed_tse_powerbuy',
    'seed_tse_powerbuy',
    NOW(),
    NOW(),
    'PowerBuy: cloned from active Homepro TSE TV column policy'
FROM public.monitoring_retail_columns source
WHERE LOWER(BTRIM(source.retailer)) = 'homepro'
  AND source.product_line = 'tse_tv'
  AND source.is_active IS TRUE
  AND COALESCE(source.is_del, FALSE) IS FALSE
  AND NOT EXISTS (
      SELECT 1
      FROM public.monitoring_retail_columns existing
      WHERE existing.product_line = source.product_line
        AND existing.column_name = source.column_name
        AND LOWER(BTRIM(existing.retailer)) = 'powerbuy'
        AND COALESCE(existing.is_del, FALSE) IS FALSE
  );

-- PowerBuy TV uses all eight active Homepro TV cross-field relationships,
-- including the original-price and savings checks confirmed for email review.
INSERT INTO public.monitoring_validation_rules (
    rule_type,
    section_code,
    section_name,
    detail_code,
    detail_name,
    table_name,
    date_column,
    product_line,
    retailer,
    field1,
    field2,
    validation_type,
    check_column,
    check_type,
    comparison_type,
    threshold,
    threshold_pct,
    threshold_min,
    error_message,
    display_columns,
    select_fields,
    query,
    query_detail,
    sort_order,
    is_active,
    created_at,
    created_id
)
SELECT
    source.rule_type,
    source.section_code,
    source.section_name,
    source.detail_code,
    source.detail_name,
    source.table_name,
    source.date_column,
    source.product_line,
    'powerbuy',
    source.field1,
    source.field2,
    source.validation_type,
    source.check_column,
    source.check_type,
    source.comparison_type,
    source.threshold,
    source.threshold_pct,
    source.threshold_min,
    source.error_message,
    source.display_columns,
    source.select_fields,
    REGEXP_REPLACE(source.query, 'homepro', 'PowerBuy', 'gi'),
    REGEXP_REPLACE(source.query_detail, 'homepro', 'PowerBuy', 'gi'),
    source.sort_order,
    TRUE,
    NOW(),
    'seed_tse_powerbuy'
FROM public.monitoring_validation_rules source
WHERE source.rule_type = 'crossfield'
  AND source.section_code = 'tse_tv_retail'
  AND source.table_name = 'dx_tse.dx_tse_tv_retail_com'
  AND LOWER(BTRIM(source.retailer)) = 'homepro'
  AND source.is_active IS TRUE
  AND NOT EXISTS (
      SELECT 1
      FROM public.monitoring_validation_rules existing
      WHERE existing.rule_type = source.rule_type
        AND existing.section_code = source.section_code
        AND existing.table_name = source.table_name
        AND existing.detail_code = source.detail_code
        AND LOWER(BTRIM(existing.retailer)) = 'powerbuy'
  );

COMMIT;

-- monitoring_retail_columns is cached for at most 60 seconds by the app.
