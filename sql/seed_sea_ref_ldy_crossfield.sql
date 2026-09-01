-- SEA REF/LDY Layer 3 cross-field rules (idempotent).
-- Run this file in PostgreSQL with DBeaver after deploying the application.
-- It intentionally has no BEGIN/COMMIT and creates no temporary table, so it
-- can be rerun safely whether DBeaver auto-commit is on or a transaction is
-- already open.  Existing matching rows are updated; missing rows are added.
-- The application performs validation with allow-listed Python rules; query
-- text stored here is metadata only and is never executed by the validator.

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
        ('Bestbuy', 'review_count_match',
         '리뷰 수와 별점 수 일치',
         'count_of_reviews', 'count_of_star_ratings',
         'count_of_reviews와 count_of_star_ratings가 다릅니다.',
         'count_of_reviews|count_of_star_ratings|detailed_review_content', 10),
        ('Bestbuy', 'rating_count_presence',
         '별점과 별점 수 존재 일치',
         'star_rating', 'count_of_star_ratings',
         '양수 star_rating이 있는데 count_of_star_ratings가 없거나 0입니다.',
         'star_rating|count_of_star_ratings|count_of_reviews', 20),
        ('Bestbuy', 'rank_page_type',
         '페이지 유형과 순위 필드 일치',
         'page_type', 'main_rank|bsr_rank',
         'MAIN/BSR page_type에 해당하는 순위 필드가 없습니다.',
         'page_type|main_rank|bsr_rank', 30),
        ('Bestbuy', 'final_original_price',
         '최종가와 원가 순서',
         'final_sku_price', 'original_sku_price',
         'Bestbuy 최종가가 원가보다 큽니다.',
         'final_sku_price|original_sku_price|savings', 40),
        ('Bestbuy', 'discount_rate_90',
         '90% 이상 할인 검사',
         'final_sku_price', 'original_sku_price',
         '최종가와 원가로 계산한 할인율이 90% 이상입니다.',
         'final_sku_price|original_sku_price|savings', 50),
        ('Bestbuy', 'review_body_count',
         '리뷰 수와 리뷰 본문 개수 일치',
         'count_of_reviews', 'detailed_review_content',
         '리뷰 수에 필요한 detailed_review_content의 reviewN이 부족합니다.',
         'count_of_reviews|count_of_star_ratings|detailed_review_content', 60),
        ('Bestbuy', 'recommendation_intent',
         '추천 의향 형식',
         'recommendation_intent', 'count_of_reviews',
         'recommendation_intent는 NN% would recommend to a friend 형식이어야 합니다.',
         'count_of_reviews|recommendation_intent|detailed_review_content', 110),

        ('Lowes', 'review_count_match',
         '리뷰 수와 별점 수 일치',
         'count_of_reviews', 'count_of_star_ratings',
         'count_of_reviews와 count_of_star_ratings가 다릅니다.',
         'count_of_reviews|count_of_star_ratings|detailed_review_content', 10),
        ('Lowes', 'final_original_price',
         '최종가와 원가 순서',
         'final_sku_price', 'original_sku_price',
         'Lowes 최종가가 원가보다 크거나 같습니다.',
         'final_sku_price|original_sku_price|savings', 40),
        ('Lowes', 'review_body_count',
         '리뷰 수보다 많은 리뷰 본문 검사',
         'count_of_reviews', 'detailed_review_content',
         'detailed_review_content의 reviewN이 count_of_reviews보다 큽니다.',
         'count_of_reviews|count_of_star_ratings|detailed_review_content', 60),
        ('Lowes', 'savings_missing',
         '최종가·원가 존재 시 savings 확인',
         'savings', 'final_sku_price|original_sku_price',
         '최종가와 원가가 있는데 savings가 없습니다.',
         'final_sku_price|original_sku_price|savings', 70),
        ('Lowes', 'original_missing',
         '최종가·savings 존재 시 원가 확인',
         'original_sku_price', 'final_sku_price|savings',
         '최종가와 savings가 있는데 original_sku_price가 없습니다.',
         'final_sku_price|original_sku_price|savings', 80),
        ('Lowes', 'savings_amount_match',
         '할인 금액 일치',
         'savings', 'original_sku_price|final_sku_price',
         'original_sku_price-final_sku_price와 savings가 다릅니다.',
         'final_sku_price|original_sku_price|savings', 90),
        ('Lowes', 'final_missing',
         '원가·savings 존재 시 최종가 확인',
         'final_sku_price', 'original_sku_price|savings',
         '원가 또는 savings가 있는데 final_sku_price가 없습니다.',
         'final_sku_price|original_sku_price|savings', 100),
        ('Lowes', 'recommendation_intent',
         '추천 의향 형식',
         'recommendation_intent', 'count_of_reviews',
         'recommendation_intent는 NN% Recommend this product 형식이어야 합니다.',
         'count_of_reviews|recommendation_intent|detailed_review_content', 110)
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
    check_column = seed.field1,
    check_type = 'cross_field',
    comparison_type = seed.validation_type,
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
    seed.field1,
    'cross_field',
    seed.validation_type,
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
    'seed_sea_crossfield'
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

-- Enable source-value editing for fields shown by the SEA cross-field rules.
-- Structural fields (page_type/main_rank/batch_id/date) remain read-only.
UPDATE public.monitoring_retail_columns
SET is_editable = TRUE,
    updated_id = 'seed_sea_crossfield',
    updated_at = NOW()
WHERE product_line IN ('sea_ref', 'sea_ldy')
  AND LOWER(BTRIM(retailer)) IN ('bestbuy', 'lowes')
  AND column_name IN (
      'count_of_reviews',
      'count_of_star_ratings',
      'star_rating',
      'final_sku_price',
      'original_sku_price',
      'savings',
      'detailed_review_content',
      'recommendation_intent',
      'bsr_rank'
  )
  AND is_active IS TRUE
  AND COALESCE(is_del, FALSE) IS FALSE;

-- Verification: expected 30 active rows (15 per product line).
SELECT
    product_line,
    retailer,
    COUNT(*) AS active_rule_count,
    STRING_AGG(validation_type, ', ' ORDER BY sort_order) AS rules
FROM public.monitoring_validation_rules
WHERE rule_type = 'crossfield'
  AND section_code IN ('sea_ref_retail', 'sea_ldy_retail')
  AND table_name IN ('public.ref_retail_com', 'public.ldy_retail_com')
  AND is_active IS TRUE
GROUP BY product_line, retailer
ORDER BY product_line, retailer;

SELECT
    product_line,
    retailer,
    COUNT(*) AS editable_column_count,
    STRING_AGG(column_name, ', ' ORDER BY column_name) AS editable_columns
FROM public.monitoring_retail_columns
WHERE product_line IN ('sea_ref', 'sea_ldy')
  AND LOWER(BTRIM(retailer)) IN ('bestbuy', 'lowes')
  AND is_editable IS TRUE
  AND is_active IS TRUE
  AND COALESCE(is_del, FALSE) IS FALSE
GROUP BY product_line, retailer
ORDER BY product_line, retailer;
