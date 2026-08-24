-- Idempotent TSE Lazada monitoring seed.
--
-- This script clones the active Homepro collection-column matrix because
-- Lazada supplies the same review/rating fields.  Retailer-specific format
-- behavior remains application code and is not copied from Homepro.

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
    'lazada',
    source.duplicate_key,
    source.skip_missing_check,
    source.is_editable,
    source.related_columns,
    TRUE,
    FALSE,
    'seed_tse_lazada',
    'seed_tse_lazada',
    NOW(),
    NOW(),
    'Lazada: cloned from active Homepro TSE column policy'
FROM public.monitoring_retail_columns source
WHERE LOWER(BTRIM(source.retailer)) = 'homepro'
  AND source.product_line IN ('tse_tv', 'tse_ref', 'tse_ldy')
  AND source.is_active IS TRUE
  AND COALESCE(source.is_del, FALSE) IS FALSE
  AND NOT EXISTS (
      SELECT 1
      FROM public.monitoring_retail_columns existing
      WHERE existing.product_line = source.product_line
        AND existing.column_name = source.column_name
        AND LOWER(BTRIM(existing.retailer)) = 'lazada'
        AND COALESCE(existing.is_del, FALSE) IS FALSE
  );

-- Lazada uses the Homepro cross-field relationships, including
-- review_zero_pair.  Rows with zero reviews/ratings and star_rating=5.0 stay
-- visible for review until the source behavior is confirmed.
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
    'lazada',
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
    REGEXP_REPLACE(source.query, 'homepro', 'Lazada', 'gi'),
    REGEXP_REPLACE(source.query_detail, 'homepro', 'Lazada', 'gi'),
    source.sort_order,
    TRUE,
    NOW(),
    'seed_tse_lazada'
FROM public.monitoring_validation_rules source
WHERE source.rule_type = 'crossfield'
  AND source.section_code IN (
      'tse_tv_retail', 'tse_ref_retail', 'tse_ldy_retail'
  )
  AND LOWER(BTRIM(source.retailer)) = 'homepro'
  AND source.is_active IS TRUE
  AND NOT EXISTS (
      SELECT 1
      FROM public.monitoring_validation_rules existing
      WHERE existing.rule_type = source.rule_type
        AND existing.section_code = source.section_code
        AND existing.table_name = source.table_name
        AND existing.detail_code = source.detail_code
        AND LOWER(BTRIM(existing.retailer)) = 'lazada'
  );

COMMIT;

-- monitoring_retail_columns is cached for at most 60 seconds by the app.
