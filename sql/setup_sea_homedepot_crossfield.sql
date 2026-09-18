-- HomeDepot SEA REF/LDY: seven Layer 3 cross-field rules per product.
-- Requires the HomeDepot Layer 2 column setup. Run manually after code deployment.
-- Idempotent; only HomeDepot configuration is modified. No source data updates.
BEGIN;

-- HomeDepot does not use the 90% threshold, page type, review body or recommendation rules.
UPDATE public.monitoring_validation_rules
SET is_active = FALSE
WHERE rule_type = 'crossfield'
  AND section_code IN ('sea_ref_retail', 'sea_ldy_retail')
  AND table_name IN ('public.ref_retail_com', 'public.ldy_retail_com')
  AND LOWER(TRIM(retailer)) = 'homedepot'
  AND validation_type NOT IN (
      'review_count_match', 'rating_count_presence', 'final_original_price',
      'savings_missing', 'original_missing', 'savings_amount_match', 'final_missing'
  );

WITH products (
    product_line, category, section_code, section_name, table_name
) AS (
    VALUES
        ('sea_ref', 'REF', 'sea_ref_retail', 'SEA REF',
         'public.ref_retail_com'),
        ('sea_ldy', 'LDY', 'sea_ldy_retail', 'SEA LDY',
         'public.ldy_retail_com')
), retailer_rules (
    retailer, validation_type, detail_name, field1, field2,
    error_message, select_fields, sort_order
) AS (
    VALUES
        ('HomeDepot', 'review_count_match',
         '리뷰 수와 별점 수 일치',
         'count_of_reviews', 'count_of_star_ratings',
         'count_of_reviews와 count_of_star_ratings가 다릅니다.',
         'count_of_reviews|count_of_star_ratings', 10),
        ('HomeDepot', 'rating_count_presence',
         '별점 0과 별점 수 0 일치',
         'star_rating', 'count_of_star_ratings',
         'star_rating과 별점 수 또는 리뷰 수의 0 여부가 다릅니다.',
         'star_rating|count_of_star_ratings|count_of_reviews', 20),
        ('HomeDepot', 'final_original_price',
         '최종가와 원가 순서',
         'final_sku_price', 'original_sku_price',
         'HomeDepot 최종가가 원가보다 크거나 같습니다.',
         'final_sku_price|original_sku_price|savings', 40),
        ('HomeDepot', 'savings_missing',
         '할인 가격 존재 시 savings 확인',
         'savings', 'final_sku_price|original_sku_price',
         '숫자 원가가 판매가보다 큰데 savings가 없습니다.',
         'final_sku_price|original_sku_price|savings', 70),
        ('HomeDepot', 'original_missing',
         '최종가·savings 존재 시 원가 확인',
         'original_sku_price', 'final_sku_price|savings',
         '최종가와 savings가 있는데 original_sku_price가 없습니다.',
         'final_sku_price|original_sku_price|savings', 80),
        ('HomeDepot', 'savings_amount_match',
         '할인 금액 일치',
         'savings', 'original_sku_price|final_sku_price',
         'original_sku_price-final_sku_price와 savings가 다릅니다.',
         'final_sku_price|original_sku_price|savings', 90),
        ('HomeDepot', 'final_missing',
         '원가·savings 존재 시 최종가 확인',
         'final_sku_price', 'original_sku_price|savings',
         '원가 또는 savings가 있는데 final_sku_price가 없습니다.',
         'final_sku_price|original_sku_price|savings', 100)
), seed AS (
SELECT
    p.product_line,
    p.category,
    p.section_code,
    p.section_name,
    p.table_name,
    r.retailer,
    r.validation_type,
    p.product_line || '_' || r.validation_type AS detail_code,
    r.detail_name,
    r.field1,
    r.field2,
    r.error_message,
    r.select_fields,
    r.sort_order
FROM products p
CROSS JOIN retailer_rules r
), updated AS (

UPDATE public.monitoring_validation_rules target
SET
    section_name = seed.section_name,
    detail_name = seed.detail_name,
    date_column = 'crawl_strdatetime',
    product_line = seed.product_line,
    field1 = seed.field1,
    field2 = seed.field2,
    validation_type = seed.validation_type,
    check_column = NULL,
    check_type = 'cross_field',
    comparison_type = NULL,
    error_message = seed.error_message,
    display_columns = seed.select_fields,
    select_fields = seed.select_fields,
    query = '',
    query_detail = '',
    sort_order = seed.sort_order,
    is_active = TRUE
FROM seed
WHERE target.rule_type = 'crossfield'
  AND target.section_code = seed.section_code
  AND target.table_name = seed.table_name
  AND target.detail_code = seed.detail_code
  AND LOWER(BTRIM(target.retailer)) = LOWER(BTRIM(seed.retailer))
RETURNING target.id
)

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
    'crossfield',
    seed.section_code,
    seed.section_name,
    seed.detail_code,
    seed.detail_name,
    seed.table_name,
    'crawl_strdatetime',
    seed.product_line,
    seed.retailer,
    seed.field1,
    seed.field2,
    seed.validation_type,
    NULL,
    'cross_field',
    NULL,
    NULL,
    NULL,
    NULL,
    seed.error_message,
    seed.select_fields,
    seed.select_fields,
    '',
    '',
    seed.sort_order,
    TRUE,
    NOW(),
    'seed_sea_homedepot_crossfield'
FROM seed
WHERE NOT EXISTS (
    SELECT 1
    FROM public.monitoring_validation_rules existing
    WHERE existing.rule_type = 'crossfield'
      AND existing.section_code = seed.section_code
      AND existing.table_name = seed.table_name
      AND existing.detail_code = seed.detail_code
      AND LOWER(BTRIM(existing.retailer)) = LOWER(BTRIM(seed.retailer))
);

UPDATE public.monitoring_retail_columns
SET is_editable = TRUE, updated_at = NOW(), updated_id = 'seed_sea_homedepot_crossfield'
WHERE product_line IN ('sea_ref', 'sea_ldy')
  AND LOWER(TRIM(retailer)) = 'homedepot'
  AND column_name IN ('count_of_reviews', 'count_of_star_ratings', 'star_rating',
                      'final_sku_price', 'original_sku_price', 'savings')
  AND is_active IS TRUE AND COALESCE(is_del, FALSE) IS FALSE;

-- Expected: HomeDepot REF 7 and LDY 7.
SELECT product_line, retailer, COUNT(*) AS active_rule_count,
       STRING_AGG(validation_type, ', ' ORDER BY sort_order) AS rules
FROM public.monitoring_validation_rules
WHERE rule_type = 'crossfield' AND is_active IS TRUE
  AND section_code IN ('sea_ref_retail', 'sea_ldy_retail')
  AND table_name IN ('public.ref_retail_com', 'public.ldy_retail_com')
  AND LOWER(TRIM(retailer)) = 'homedepot'
GROUP BY product_line, retailer ORDER BY product_line;

COMMIT;
