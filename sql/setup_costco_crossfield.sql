-- Costco TV/REF/LDY: seven cross-field rules. Run after code deployment.
-- Configuration only; does not update collected products or other retailers.
BEGIN;
CREATE TEMP TABLE _costco_crossfield ON COMMIT DROP AS
WITH products(product_line, product, section_code, date_column) AS (VALUES
 ('tv', 'TV', 'tv_retail', 'crawl_datetime'),
 ('sea_ref', 'REF', 'sea_ref_retail', 'crawl_strdatetime'),
 ('sea_ldy', 'LDY', 'sea_ldy_retail', 'crawl_strdatetime')
), rules(validation_type, detail_name, field1, field2, error_message, sort_order) AS (VALUES
 ('review_count_match', '리뷰 수와 별점 수 일치', 'count_of_reviews', 'count_of_star_ratings',
  'count_of_reviews와 count_of_star_ratings가 다릅니다.', 10),
 ('rating_count_presence', '별점과 평가 수의 0 여부', 'star_rating', 'count_of_star_ratings|count_of_reviews',
  '별점과 별점 수 또는 리뷰 수의 0 여부가 다릅니다.', 20),
 ('final_original_price', '최종가와 원가 순서', 'final_sku_price', 'original_sku_price',
  '최종가가 원가보다 크거나 같습니다.', 30),
 ('savings_missing', '할인금액 누락', 'savings', 'original_sku_price|final_sku_price',
  '숫자 원가가 최종가보다 큰데 savings가 없습니다.', 40),
 ('original_missing', '원가 누락', 'original_sku_price', 'final_sku_price|savings',
  '숫자 최종가와 savings가 있는데 원가가 없습니다.', 50),
 ('final_missing', '최종가 누락', 'final_sku_price', 'original_sku_price|savings',
  '원가 또는 savings가 있는데 최종가가 없습니다.', 60),
 ('savings_amount_match', '할인금액 일치', 'savings', 'original_sku_price|final_sku_price',
  '원가-최종가와 savings 금액이 다릅니다.', 70)
)
SELECT p.*, r.*, 'SEA ' || p.product AS section_name,
 'public.' || lower(p.product) || '_retail_com' AS table_name,
 'costco_' || lower(p.product) || '_' || r.validation_type AS detail_code,
 'star_rating|count_of_star_ratings|count_of_reviews|final_sku_price|original_sku_price|savings' AS fields
FROM products p CROSS JOIN rules r;

-- Disable older Costco-specific rules, including review-body checks.
-- ALL-retailer TV rules exclude Costco in application code, preserving other retailers.
UPDATE public.monitoring_validation_rules
SET is_active = FALSE
WHERE rule_type = 'crossfield' AND lower(trim(retailer)) = 'costco'
 AND section_code IN ('tv_retail', 'sea_ref_retail', 'sea_ldy_retail');

UPDATE public.monitoring_validation_rules t
SET section_name = s.section_name, detail_name = s.detail_name,
 table_name = s.table_name, date_column = s.date_column, product_line = s.product_line,
 field1 = s.field1, field2 = s.field2, validation_type = s.validation_type,
 check_type = 'cross_field', error_message = s.error_message,
 select_fields = s.fields, display_columns = s.fields,
 query = '', query_detail = '', sort_order = s.sort_order, is_active = TRUE
FROM _costco_crossfield s
WHERE t.rule_type = 'crossfield' AND lower(trim(t.retailer)) = 'costco'
 AND t.section_code = s.section_code AND t.detail_code = s.detail_code;

INSERT INTO public.monitoring_validation_rules
 (rule_type, section_code, section_name, detail_code, detail_name, table_name,
  date_column, product_line, retailer, field1, field2, validation_type, check_type,
  error_message, select_fields, display_columns, query, query_detail, sort_order,
  is_active, created_at, created_id)
SELECT 'crossfield', s.section_code, s.section_name, s.detail_code, s.detail_name, s.table_name,
 s.date_column, s.product_line, 'Costco', s.field1, s.field2, s.validation_type, 'cross_field',
 s.error_message, s.fields, s.fields, '', '', s.sort_order, TRUE, NOW(), 'setup_costco_crossfield'
FROM _costco_crossfield s
WHERE NOT EXISTS (SELECT 1 FROM public.monitoring_validation_rules t
 WHERE t.rule_type = 'crossfield' AND lower(trim(t.retailer)) = 'costco'
 AND t.section_code = s.section_code AND t.detail_code = s.detail_code);

-- Expected: seven active rules in each of the three sections.
SELECT section_code, COUNT(*) AS active_rules
FROM public.monitoring_validation_rules
WHERE rule_type = 'crossfield' AND lower(trim(retailer)) = 'costco' AND is_active
 AND section_code IN ('tv_retail', 'sea_ref_retail', 'sea_ldy_retail')
GROUP BY section_code ORDER BY section_code;
COMMIT;
