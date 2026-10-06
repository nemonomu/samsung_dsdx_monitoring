-- Costco format validation. Deploy matching code, then run on monitoring DB.
-- TV 10 / REF 12 / LDY 12 fields; NULL policy and source values are unchanged.
BEGIN;
CREATE TEMP TABLE _cf_sources(product_line text, product text, table_name text) ON COMMIT DROP;
INSERT INTO _cf_sources VALUES
 ('tv', 'TV', 'tv_retail_com'), ('sea_ref', 'REF', 'ref_retail_com'), ('sea_ldy', 'LDY', 'ldy_retail_com');
CREATE TEMP TABLE _cf_templates(name text, check_type text, pattern text, description text) ON COMMIT DROP;
INSERT INTO _cf_templates VALUES
 ('COSTCO_ENUM', 'enum', NULL, 'Costco allowed values'),
 ('COSTCO_WEEK', 'regex', $p$^[0-9]{4}-W(?:0[1-9]|[1-4][0-9]|5[0-3])$$p$, 'YYYY-W01 through W53'),
 ('COSTCO_USD', 'regex', $p$^[$](?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)(?:\.[0-9]{1,2})?$$p$, 'USD amount, e.g. $1,249.99 or $300'),
 ('COSTCO_RATING', 'range_float', NULL, 'Rating 0 through 5'),
 ('COSTCO_COUNT', 'regex', $p$^(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)$$p$, 'Nonnegative integer count'),
 ('COSTCO_SCREEN', 'regex', $p$^[0-9]+(?:\.[0-9]+)? in\.$$p$, 'Screen size, e.g. 55 in.'),
 ('COSTCO_CAPACITY', 'regex', $p$(?i)^[0-9]+(?:\.[0-9]+)? cu\.?\s*ft\.?$$p$, 'Cubic feet, including observed punctuation and case variants'),
 ('COSTCO_REF_TYPE', 'regex', $p$^(?:Side-by-Side|French Door|Bottom Freezer|Merchandiser|Top Freezer|Compact|Freezerless)(?: \| (?:Side-by-Side|French Door|Bottom Freezer|Merchandiser|Top Freezer|Compact|Freezerless))*$$p$, 'Known refrigerator types, optionally combined with |');

UPDATE public.monitoring_format_templates t
SET check_type=s.check_type, pattern=s.pattern, description=s.description,
 is_active=TRUE, updated_at=NOW(), updated_id='setup_costco_format'
FROM _cf_templates s WHERE t.name=s.name;
INSERT INTO public.monitoring_format_templates
 (name, check_type, pattern, description, is_active, created_at, created_id, updated_at, updated_id)
SELECT name, check_type, pattern, description, TRUE, NOW(), 'setup_costco_format', NOW(), 'setup_costco_format'
FROM _cf_templates s WHERE NOT EXISTS (SELECT 1 FROM public.monitoring_format_templates t WHERE t.name=s.name);

CREATE TEMP TABLE _cf_rules(table_name text, column_name text, template_name text, rule_value text, error_message text) ON COMMIT DROP;
INSERT INTO _cf_rules
SELECT s.table_name, r.* FROM _cf_sources s CROSS JOIN (VALUES
 ('account_name', 'COSTCO_ENUM', 'Costco', 'account_name은 Costco여야 합니다.'),
 ('country', 'COSTCO_ENUM', 'SEA', 'country는 SEA여야 합니다.'),
 ('calendar_week', 'COSTCO_WEEK', NULL, '주차는 YYYY-W01~W53 형식이어야 합니다.'),
 ('star_rating', 'COSTCO_RATING', '0~5', '별점은 0~5 사이 숫자여야 합니다.'),
 ('count_of_star_ratings', 'COSTCO_COUNT', NULL, '별점 수는 0 이상의 정수여야 합니다.'),
 ('count_of_reviews', 'COSTCO_COUNT', NULL, '리뷰 수는 0 이상의 정수여야 합니다.'),
 ('final_sku_price', 'COSTCO_USD', NULL, '판매가는 $1,249.99 같은 달러 금액이어야 합니다.'),
 ('original_sku_price', 'COSTCO_USD', NULL, '원가는 $1,249.99 같은 달러 금액이어야 합니다.'),
 ('savings', 'COSTCO_USD', NULL, '할인금액은 $300 같은 달러 금액이어야 합니다.')
) r(column_name, template_name, rule_value, error_message);
INSERT INTO _cf_rules VALUES
 ('tv_retail_com', 'screen_size', 'COSTCO_SCREEN', NULL, '화면 크기는 55 in. 같은 형식이어야 합니다.'),
 ('ref_retail_com', 'product', 'COSTCO_ENUM', 'REF', 'product는 REF여야 합니다.'),
 ('ldy_retail_com', 'product', 'COSTCO_ENUM', 'LDY', 'product는 LDY여야 합니다.'),
 ('ref_retail_com', 'ref_capacity', 'COSTCO_CAPACITY', NULL, '용량은 숫자와 cu. ft. 단위여야 합니다.'),
 ('ldy_retail_com', 'ldy_capacity', 'COSTCO_CAPACITY', NULL, '용량은 숫자와 cu. ft. 단위여야 합니다.'),
 ('ref_retail_com', 'ref_refrigerator_type', 'COSTCO_REF_TYPE', NULL, '허용된 냉장고 유형 또는 | 조합이어야 합니다.'),
 ('ldy_retail_com', 'ldy_loading_type', 'COSTCO_ENUM', 'Front Load|Top Load', '로딩 타입은 Front Load 또는 Top Load여야 합니다.');

UPDATE public.monitoring_format_rules t SET is_active=FALSE, updated_at=NOW(), updated_id='setup_costco_format'
WHERE lower(trim(t.account_name))='costco' AND t.table_name IN (SELECT table_name FROM _cf_sources)
 AND NOT EXISTS (SELECT 1 FROM _cf_rules s WHERE s.table_name=t.table_name AND s.column_name=t.column_name);
UPDATE public.monitoring_format_rules t
SET template_id=p.id, rule_value=s.rule_value, error_message=s.error_message,
 extra_allowed=NULL, forbidden_chars=NULL, is_active=TRUE, is_del=FALSE,
 updated_at=NOW(), updated_id='setup_costco_format'
FROM _cf_rules s JOIN public.monitoring_format_templates p ON p.name=s.template_name
WHERE t.table_name=s.table_name AND t.column_name=s.column_name AND lower(trim(t.account_name))='costco';
INSERT INTO public.monitoring_format_rules
 (table_name,column_name,account_name,template_id,rule_value,error_message,is_active,is_del,created_at,created_id,updated_at,updated_id)
SELECT s.table_name,s.column_name,'Costco',p.id,s.rule_value,s.error_message,TRUE,FALSE,NOW(),'setup_costco_format',NOW(),'setup_costco_format'
FROM _cf_rules s JOIN public.monitoring_format_templates p ON p.name=s.template_name
WHERE NOT EXISTS (SELECT 1 FROM public.monitoring_format_rules t
 WHERE t.table_name=s.table_name AND t.column_name=s.column_name AND lower(trim(t.account_name))='costco');

-- Enable editing without changing existing NULL-required flags.
UPDATE public.monitoring_retail_columns t
SET is_editable=TRUE, is_active=TRUE, is_del=FALSE, updated_at=NOW(), updated_id='setup_costco_format'
FROM _cf_sources p JOIN _cf_rules r ON r.table_name=p.table_name
WHERE t.product_line=p.product_line AND t.column_name=r.column_name AND lower(trim(t.retailer))='costco';
INSERT INTO public.monitoring_retail_columns
 (product_line,column_name,retailer,duplicate_key,skip_missing_check,is_editable,is_active,is_del,created_at,created_id,updated_at,updated_id)
SELECT p.product_line,r.column_name,'Costco',FALSE,TRUE,TRUE,TRUE,FALSE,NOW(),'setup_costco_format',NOW(),'setup_costco_format'
FROM _cf_sources p JOIN _cf_rules r ON r.table_name=p.table_name
WHERE NOT EXISTS (SELECT 1 FROM public.monitoring_retail_columns t
 WHERE t.product_line=p.product_line AND t.column_name=r.column_name AND lower(trim(t.retailer))='costco');

SELECT table_name,COUNT(*) AS active_fields FROM public.monitoring_format_rules
WHERE lower(trim(account_name))='costco' AND is_active AND NOT is_del
 AND table_name IN (SELECT table_name FROM _cf_sources)
GROUP BY table_name ORDER BY table_name;
COMMIT;
