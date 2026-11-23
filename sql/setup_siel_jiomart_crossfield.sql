-- SIEL Jiomart TV·REF·LDY 크로스필드 규칙을 제품군마다 7개 등록합니다.
-- DBeaver에서 전체 스크립트를 실행합니다. 재실행하면 기존 규칙 ID를 유지합니다.
BEGIN;

LOCK TABLE public.monitoring_validation_rules IN SHARE ROW EXCLUSIVE MODE;

WITH products(product, section_name) AS (
    VALUES ('tv', 'SIEL TV'), ('ref', 'SIEL REF'), ('ldy', 'SIEL LDY')
), rules(rule_key, detail_name, field1, field2, error_message, sort_order) AS (
    VALUES
    ('jiomart_rating_count_presence', '별점과 별점 수 존재 일치',
     'star_rating', 'count_of_star_ratings',
     '별점과 별점 수 중 하나가 양수인데 다른 하나가 0 또는 빈값입니다.', 210),
    ('jiomart_review_gt_star_count', '리뷰 수가 별점 수 이하',
     'count_of_reviews', 'count_of_star_ratings',
     '리뷰 수가 별점 수보다 크거나 리뷰 수가 1 이상인데 별점 수가 비어 있습니다.', 220),
    ('jiomart_final_original_price', '판매가와 원가 순서',
     'final_sku_price', 'original_sku_price',
     '판매가와 원가가 숫자이고 판매가가 원가보다 크거나 같습니다.', 230),
    ('jiomart_savings_missing', '할인율 누락',
     'savings', 'original_sku_price|final_sku_price',
     '계산 할인율이 1% 이상인데 savings가 비어 있습니다.', 240),
    ('jiomart_original_missing', '원가 누락',
     'original_sku_price', 'final_sku_price|savings',
     '숫자 판매가와 savings가 있는데 원가가 비어 있습니다.', 250),
    ('jiomart_final_missing', '판매가 누락',
     'final_sku_price', 'original_sku_price|savings',
     '원가 또는 savings가 있는데 판매가가 비어 있습니다.', 260),
    ('jiomart_savings_rate_match', '표시 할인율과 가격 차이 일치',
     'savings', 'original_sku_price|final_sku_price',
     '표시 할인율과 계산 할인율의 차이가 1%p를 초과합니다.', 270)
), seed AS (
    SELECT 'siel_' || product AS product_line,
           'siel_' || product || '_retail' AS section_code,
           'dx_siel.dx_siel_' || product || '_retail_com' AS table_name,
           'siel_' || product || '_' || rule_key AS detail_code,
           CASE WHEN sort_order <= 220 THEN 'star_rating|count_of_star_ratings|count_of_reviews'
                ELSE 'original_sku_price|final_sku_price|savings' END AS select_fields,
           section_name, rules.*
    FROM products CROSS JOIN rules
), updated AS (
    UPDATE public.monitoring_validation_rules AS target
    SET detail_name = seed.detail_name, section_name = seed.section_name,
        date_column = 'crawl_datetime', product_line = seed.product_line,
        field1 = seed.field1, field2 = seed.field2, validation_type = seed.rule_key,
        error_message = seed.error_message, select_fields = seed.select_fields,
        query = '', sort_order = seed.sort_order, is_active = TRUE
    FROM seed
    WHERE target.rule_type = 'crossfield'
      AND target.section_code = seed.section_code AND target.table_name = seed.table_name
      AND target.detail_code = seed.detail_code AND LOWER(BTRIM(target.retailer)) = 'jiomart'
    RETURNING target.detail_code
)
INSERT INTO public.monitoring_validation_rules (
    rule_type, section_code, section_name, detail_code, detail_name,
    table_name, date_column, product_line, retailer, field1, field2,
    validation_type, error_message, select_fields, query, sort_order,
    is_active, created_at, created_id
)
SELECT 'crossfield', section_code, section_name, detail_code, detail_name,
       table_name, 'crawl_datetime', product_line, 'Jiomart', field1, field2,
       rule_key, error_message, select_fields, '', sort_order,
       TRUE, NOW(), 'setup_siel_jiomart_crossfield'
FROM seed
WHERE NOT EXISTS (SELECT 1 FROM updated WHERE updated.detail_code = seed.detail_code);

COMMIT;

-- 제품군별 7건씩 확인합니다.
SELECT section_code, COUNT(*) AS active_rules
FROM public.monitoring_validation_rules
WHERE rule_type = 'crossfield' AND is_active
  AND LOWER(BTRIM(retailer)) = 'jiomart'
  AND LEFT(validation_type, 8) = 'jiomart_'
  AND section_code IN ('siel_tv_retail', 'siel_ref_retail', 'siel_ldy_retail')
GROUP BY section_code
ORDER BY section_code;
