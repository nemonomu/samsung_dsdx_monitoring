-- Run in the monitoring DB with DBeaver after deploying the SEDA adapter.
-- Casas Bahia only. Missing recommendation is allowed regardless of review count.
-- Existing SEA/SEG rules are intentionally not changed by this script.
BEGIN;

CREATE TEMP TABLE _seda_recommendation_seed ON COMMIT DROP AS
SELECT 'seda_' || product AS product_line,
       'seda_' || product || '_retail' AS section_code,
       'SEDA ' || UPPER(product) AS section_name,
       'dx_seda.dx_seda_' || product || '_retail_com' AS table_name,
       'seda_' || product || '_recommendation_intent' AS detail_code
FROM (VALUES ('tv'), ('ref'), ('ldy')) AS products(product);

UPDATE public.monitoring_validation_rules AS target
SET section_name = seed.section_name,
    detail_name = '추천 의향 형식·범위', date_column = 'crawl_strdatetime',
    product_line = seed.product_line, retailer = 'Casas Bahia',
    field1 = 'recommendation_intent', field2 = NULL,
    validation_type = 'recommendation_intent', check_type = 'cross_field',
    error_message = '값이 있으면 NN% recommend this product 형식과 정수 0~100%를 검사합니다. 빈값은 제외하며 리뷰 수와 연결하지 않습니다.',
    display_columns = 'recommendation_intent|star_rating|count_of_star_ratings|count_of_reviews',
    select_fields = 'recommendation_intent|star_rating|count_of_star_ratings|count_of_reviews',
    query = '', query_detail = '', sort_order = 110, is_active = TRUE
FROM _seda_recommendation_seed AS seed
WHERE target.rule_type = 'crossfield'
  AND target.section_code = seed.section_code
  AND target.table_name = seed.table_name
  AND target.detail_code = seed.detail_code
  AND LOWER(REPLACE(BTRIM(target.retailer), ' ', '')) = 'casasbahia';

INSERT INTO public.monitoring_validation_rules (
    rule_type, section_code, section_name, detail_code, detail_name,
    table_name, date_column, product_line, retailer, field1, field2,
    validation_type, check_type, error_message, display_columns, select_fields,
    query, query_detail, sort_order, is_active, created_at, created_id
)
SELECT 'crossfield', seed.section_code, seed.section_name, seed.detail_code,
       '추천 의향 형식·범위', seed.table_name, 'crawl_strdatetime', seed.product_line,
       'Casas Bahia', 'recommendation_intent', NULL, 'recommendation_intent', 'cross_field',
       '값이 있으면 NN% recommend this product 형식과 정수 0~100%를 검사합니다. 빈값은 제외하며 리뷰 수와 연결하지 않습니다.',
       'recommendation_intent|star_rating|count_of_star_ratings|count_of_reviews', 'recommendation_intent|star_rating|count_of_star_ratings|count_of_reviews',
       '', '', 110, TRUE, NOW(), 'setup_seda_recommendation'
FROM _seda_recommendation_seed AS seed
WHERE NOT EXISTS (
    SELECT 1 FROM public.monitoring_validation_rules AS target
    WHERE target.rule_type = 'crossfield'
      AND target.section_code = seed.section_code AND target.table_name = seed.table_name
      AND target.detail_code = seed.detail_code
      AND LOWER(REPLACE(BTRIM(target.retailer), ' ', '')) = 'casasbahia'
);

SELECT section_code, detail_code, retailer, is_active
FROM public.monitoring_validation_rules
WHERE rule_type = 'crossfield'
  AND detail_code IN (SELECT detail_code FROM _seda_recommendation_seed)
ORDER BY section_code, retailer;
COMMIT;
