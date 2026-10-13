-- Bestbuy dryer: seven cross-field rules. Run after code deployment.
-- Configuration only; does not update collected products or other retailers.
BEGIN;
CREATE TEMP TABLE _bestbuy_crossfield ON COMMIT DROP AS
WITH products(product_line, product, section_code, date_column) AS (VALUES
 ('sea_ldy_dryer', 'LDY_DRYER', 'sea_ldy_dryer_retail', 'crawl_datetime')
), rules(validation_type, detail_name, field1, field2, error_message, sort_order) AS (VALUES
 ('review_count_match', '리뷰 수와 별점 수 일치', 'count_of_reviews', 'count_of_star_ratings',
  '리뷰 수와 별점 수가 같아야 합니다.', 10),
 ('rating_count_presence', '별점과 평가 수의 0 여부', 'star_rating', 'count_of_star_ratings|count_of_reviews',
  'Not yet reviewed 또는 별점 0이면 리뷰 수·별점 수가 모두 0이어야 하며, 양수 별점이면 두 수가 모두 1 이상이어야 합니다.', 20),
 ('final_original_price', '최종가와 원가 순서', 'final_sku_price', 'original_sku_price',
  '판매가는 원가를 초과할 수 없습니다. 같은 금액이면 할인액은 공란 또는 0이어야 합니다.', 30),
 ('savings_missing', '할인금액 누락', 'savings', 'original_sku_price|final_sku_price',
  '원가가 판매가보다 높으면 할인액이 있어야 합니다.', 40),
 ('original_missing', '원가 누락', 'original_sku_price', 'final_sku_price|savings',
  '판매가와 양수 할인액이 있으면 원가가 있어야 합니다.', 50),
 ('final_missing', '최종가 누락', 'final_sku_price', 'original_sku_price|savings',
  '원가나 할인액이 있으면 판매가가 있어야 합니다.', 60),
 ('savings_amount_match', '할인금액 일치', 'savings', 'original_sku_price|final_sku_price',
  '원가에서 판매가를 뺀 금액과 할인액이 센트 단위로 일치해야 합니다.', 70)
)
SELECT p.*, r.*, 'SEA ' || p.product AS section_name,
 'public.ldy_dryer_retail' AS table_name,
 'bestbuy_' || lower(p.product) || '_' || r.validation_type AS detail_code,
 'star_rating|count_of_star_ratings|count_of_reviews|final_sku_price|original_sku_price|savings' AS fields
FROM products p CROSS JOIN rules r;

-- Replace only Bestbuy dryer rules. Other products and retailers are unchanged.
UPDATE public.monitoring_validation_rules
SET is_active = FALSE
WHERE rule_type = 'crossfield' AND lower(trim(retailer)) = 'bestbuy'
 AND section_code IN ('sea_ldy_dryer_retail');

UPDATE public.monitoring_validation_rules t
SET section_name = s.section_name, detail_name = s.detail_name,
 table_name = s.table_name, date_column = s.date_column, product_line = s.product_line,
 field1 = s.field1, field2 = s.field2, validation_type = s.validation_type,
 check_type = 'cross_field', error_message = s.error_message,
 select_fields = s.fields, display_columns = s.fields,
 query = '', query_detail = '', sort_order = s.sort_order, is_active = TRUE
FROM _bestbuy_crossfield s
WHERE t.rule_type = 'crossfield' AND lower(trim(t.retailer)) = 'bestbuy'
 AND t.section_code = s.section_code AND t.detail_code = s.detail_code;

INSERT INTO public.monitoring_validation_rules
 (rule_type, section_code, section_name, detail_code, detail_name, table_name,
  date_column, product_line, retailer, field1, field2, validation_type, check_type,
  error_message, select_fields, display_columns, query, query_detail, sort_order,
  is_active, created_at, created_id)
SELECT 'crossfield', s.section_code, s.section_name, s.detail_code, s.detail_name, s.table_name,
 s.date_column, s.product_line, 'Bestbuy', s.field1, s.field2, s.validation_type, 'cross_field',
 s.error_message, s.fields, s.fields, '', '', s.sort_order, TRUE, NOW(), 'setup_bestbuy_dryer_crossfield'
FROM _bestbuy_crossfield s
WHERE NOT EXISTS (SELECT 1 FROM public.monitoring_validation_rules t
 WHERE t.rule_type = 'crossfield' AND lower(trim(t.retailer)) = 'bestbuy'
 AND t.section_code = s.section_code AND t.detail_code = s.detail_code);

-- Expected: seven active rules in sea_ldy_dryer_retail.
SELECT section_code, COUNT(*) AS active_rules
FROM public.monitoring_validation_rules
WHERE rule_type = 'crossfield' AND lower(trim(retailer)) = 'bestbuy' AND is_active
 AND section_code IN ('sea_ldy_dryer_retail')
GROUP BY section_code ORDER BY section_code;
COMMIT;
