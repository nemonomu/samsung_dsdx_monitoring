-- Monitoring metadata only: Lowes dryer (7) and Spain MediaMarkt (4 x 7).
-- Run after deploying the matching application code. Source tables are untouched.
BEGIN;
LOCK TABLE public.monitoring_validation_rules IN SHARE ROW EXCLUSIVE MODE;

CREATE TEMP TABLE lowes_seib_crossfield_seed ON COMMIT DROP AS
WITH products(source_key, section_name, table_name, retailer, savings_kind) AS (VALUES
    ('sea_ldy_dryer', 'SEA LDY_DRYER', 'public.ldy_dryer_retail', 'Lowes', 'amount'),
    ('seib_tv', 'SEIB TV', 'dx_seib.dx_seib_tv_retail_com', 'MediaMarkt', 'rate'),
    ('seib_ref', 'SEIB REF', 'dx_seib.dx_seib_ref_retail_com', 'MediaMarkt', 'rate'),
    ('seib_ldy', 'SEIB LDY', 'dx_seib.dx_seib_ldy_retail_com', 'MediaMarkt', 'rate'),
    ('seib_ldy_dryer', 'SEIB LDY_DRYER', 'dx_seib.dx_seib_ldy_dryer_retail_com', 'MediaMarkt', 'rate')
), rules(validation_type, detail_name, field1, field2, error_message, select_fields, sort_order, savings_kind) AS (VALUES
    ('review_count_match', '리뷰 수와 별점 수 일치', 'count_of_reviews', 'count_of_star_ratings',
     '리뷰 수와 별점 수가 다릅니다.', 'count_of_reviews|count_of_star_ratings|star_rating', 210, 'both'),
    ('rating_count_presence', '별점과 건수의 0 여부 일치', 'star_rating', 'count_of_star_ratings|count_of_reviews',
     '별점과 별점 수 또는 리뷰 수의 0 여부가 다릅니다.', 'star_rating|count_of_star_ratings|count_of_reviews', 220, 'both'),
    ('final_original_price', '판매가와 원가 순서', 'final_sku_price', 'original_sku_price',
     '판매가가 원가보다 크거나 같습니다.', 'final_sku_price|original_sku_price|savings', 230, 'both'),
    ('savings_missing', '할인금액 누락', 'savings', 'original_sku_price|final_sku_price',
     '원가가 판매가보다 큰데 savings가 없습니다.', 'final_sku_price|original_sku_price|savings', 240, 'amount'),
    ('savings_missing', '할인율 누락', 'savings', 'original_sku_price|final_sku_price',
     '계산 할인율의 버림값이 1% 이상인데 savings가 없습니다.', 'final_sku_price|original_sku_price|savings', 240, 'rate'),
    ('original_missing', '원가 누락', 'original_sku_price', 'final_sku_price|savings',
     '판매가와 savings가 있는데 원가가 없습니다.', 'final_sku_price|original_sku_price|savings', 250, 'both'),
    ('final_missing', '판매가 누락', 'final_sku_price', 'original_sku_price|savings',
     '원가 또는 savings가 있는데 판매가가 없습니다.', 'final_sku_price|original_sku_price|savings', 260, 'both'),
    ('savings_amount_match', '할인금액 일치', 'savings', 'original_sku_price|final_sku_price',
     'savings와 원가에서 판매가를 뺀 금액이 다릅니다.', 'final_sku_price|original_sku_price|savings', 270, 'amount'),
    ('savings_rate_match', '할인율 일치', 'savings', 'original_sku_price|final_sku_price',
     '표시 할인율과 계산 할인율의 소수점 버림값이 다릅니다.', 'final_sku_price|original_sku_price|savings', 270, 'rate')
)
SELECT p.source_key || '_retail' AS section_code, p.section_name,
       CASE WHEN p.retailer = 'Lowes' THEN p.source_key || '_lowes_' || r.validation_type
            ELSE p.source_key || '_' || r.validation_type END AS detail_code,
       r.detail_name, p.table_name, 'crawl_datetime'::text AS date_column,
       p.source_key AS product_line, p.retailer, r.field1, r.field2,
       r.validation_type, r.error_message, r.select_fields, r.sort_order
FROM products p CROSS JOIN rules r
WHERE r.savings_kind IN ('both', p.savings_kind);

UPDATE public.monitoring_validation_rules target
SET section_name = seed.section_name, detail_name = seed.detail_name,
    date_column = seed.date_column, product_line = seed.product_line,
    field1 = seed.field1, field2 = seed.field2,
    validation_type = seed.validation_type, check_type = 'cross_field',
    error_message = seed.error_message, select_fields = seed.select_fields,
    display_columns = seed.select_fields, query = '', query_detail = '',
    sort_order = seed.sort_order, is_active = TRUE
FROM lowes_seib_crossfield_seed seed
WHERE target.rule_type = 'crossfield'
  AND target.section_code = seed.section_code
  AND target.table_name = seed.table_name
  AND target.detail_code = seed.detail_code
  AND LOWER(BTRIM(target.retailer)) = LOWER(BTRIM(seed.retailer));

INSERT INTO public.monitoring_validation_rules (
    rule_type, section_code, section_name, detail_code, detail_name,
    table_name, date_column, product_line, retailer, field1, field2,
    validation_type, check_type, error_message, select_fields, display_columns,
    query, query_detail, sort_order, is_active, created_at, created_id
)
SELECT 'crossfield', seed.section_code, seed.section_name, seed.detail_code,
       seed.detail_name, seed.table_name, seed.date_column, seed.product_line,
       seed.retailer, seed.field1, seed.field2, seed.validation_type,
       'cross_field', seed.error_message, seed.select_fields, seed.select_fields,
       '', '', seed.sort_order, TRUE, NOW(), 'setup_lowes_seib_crossfield'
FROM lowes_seib_crossfield_seed seed
WHERE NOT EXISTS (
    SELECT 1 FROM public.monitoring_validation_rules target
    WHERE target.rule_type = 'crossfield'
      AND target.section_code = seed.section_code
      AND target.table_name = seed.table_name
      AND target.detail_code = seed.detail_code
      AND LOWER(BTRIM(target.retailer)) = LOWER(BTRIM(seed.retailer))
);

DO $$
BEGIN
    IF (SELECT COUNT(*) FROM lowes_seib_crossfield_seed) <> 35 THEN
        RAISE EXCEPTION 'Expected 35 Lowes/SEIB seed rules';
    END IF;
    IF (SELECT COUNT(*) FROM public.monitoring_validation_rules target
        JOIN lowes_seib_crossfield_seed seed
          ON target.section_code = seed.section_code
         AND target.table_name = seed.table_name
         AND target.detail_code = seed.detail_code
         AND LOWER(BTRIM(target.retailer)) = LOWER(BTRIM(seed.retailer))
        WHERE target.rule_type = 'crossfield' AND target.is_active IS TRUE) <> 35 THEN
        RAISE EXCEPTION 'Expected 35 active Lowes/SEIB rules';
    END IF;
END $$;
COMMIT;

SELECT section_code, retailer, COUNT(*) AS active_rules
FROM public.monitoring_validation_rules
WHERE rule_type = 'crossfield' AND is_active IS TRUE
  AND ((section_code = 'sea_ldy_dryer_retail' AND LOWER(BTRIM(retailer)) = 'lowes')
       OR (section_code IN ('seib_tv_retail', 'seib_ref_retail',
                            'seib_ldy_retail', 'seib_ldy_dryer_retail')
           AND LOWER(BTRIM(retailer)) = 'mediamarkt'))
GROUP BY section_code, retailer ORDER BY section_code, retailer;
