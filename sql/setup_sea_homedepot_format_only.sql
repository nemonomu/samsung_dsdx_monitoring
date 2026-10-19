-- SEA HomeDepot REF, LDY, LDY_DRYER format rules only.
-- This changes monitoring metadata, never collected retail rows or cross-field rules.
BEGIN;

SELECT setval(pg_get_serial_sequence('public.monitoring_format_templates', 'id'),
              COALESCE((SELECT MAX(id) + 1 FROM public.monitoring_format_templates), 1), FALSE);
SELECT setval(pg_get_serial_sequence('public.monitoring_format_rules', 'id'),
              COALESCE((SELECT MAX(id) + 1 FROM public.monitoring_format_rules), 1), FALSE);

CREATE TEMP TABLE _sea_hd_format_templates (
    name text PRIMARY KEY, check_type text, pattern text, description text
) ON COMMIT DROP;
INSERT INTO _sea_hd_format_templates VALUES
 ('SEA_HD_FORMAT_ENUM', 'enum', NULL, 'SEA HomeDepot identity and product'),
 ('SEA_HD_FORMAT_WEEK', 'regex',
  '^[0-9]{4}-W(?:0[1-9]|[1-4][0-9]|5[0-3])$', 'HomeDepot YYYY-W01 through YYYY-W53'),
 ('SEA_HD_FORMAT_USD', 'regex',
  '^[$](?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)(?:\.[0-9]{1,2})?$',
  'HomeDepot US dollar amount'),
 ('SEA_HD_FORMAT_SAVINGS', 'regex',
  '^[$](?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)(?:\.[0-9]{1,2})? \((?:[0-9]|[1-9][0-9]|100)%\)$',
  'HomeDepot saving amount and percent'),
 ('SEA_HD_FORMAT_RATING', 'range_float', NULL, 'Star rating between zero and five'),
 ('SEA_HD_FORMAT_COUNT', 'regex',
  '^(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)$',
  'Nonnegative integer count'),
 ('SEA_HD_FORMAT_CAPACITY', 'regex',
  '^[0-9]+(?:\.[0-9]+)? cu ft$', 'Cubic-feet capacity');

UPDATE public.monitoring_format_templates target
SET check_type = seed.check_type, pattern = seed.pattern,
    description = seed.description, is_active = TRUE,
    updated_id = 'setup_sea_homedepot_format_only', updated_at = NOW()
FROM _sea_hd_format_templates seed WHERE target.name = seed.name;
INSERT INTO public.monitoring_format_templates
 (name, description, check_type, pattern, is_active,
  created_id, created_at, updated_id, updated_at)
SELECT seed.name, seed.description, seed.check_type, seed.pattern, TRUE,
       'setup_sea_homedepot_format_only', NOW(),
       'setup_sea_homedepot_format_only', NOW()
FROM _sea_hd_format_templates seed
WHERE NOT EXISTS (SELECT 1 FROM public.monitoring_format_templates target
                  WHERE target.name = seed.name);

CREATE TEMP TABLE _sea_hd_format_rules (
    table_name text, column_name text, template_name text,
    rule_value text, error_message text,
    PRIMARY KEY (table_name, column_name)
) ON COMMIT DROP;
WITH products(table_name, product_column, capacity_column, product_value) AS (
    VALUES
     ('ref_retail_com', 'product', 'ref_capacity', 'REF'),
     ('ldy_retail_com', 'product', 'ldy_capacity', 'LDY'),
     ('ldy_dryer_retail', NULL, 'capacity', NULL)
)
INSERT INTO _sea_hd_format_rules
SELECT product.table_name, rule.column_name, rule.template_name,
       rule.rule_value, rule.error_message
FROM products product
CROSS JOIN LATERAL (VALUES
 ('account_name', 'SEA_HD_FORMAT_ENUM', 'HomeDepot', 'account_name은 HomeDepot이어야 합니다.'),
 ('country', 'SEA_HD_FORMAT_ENUM', 'SEA', 'country는 SEA여야 합니다.'),
 ('calendar_week', 'SEA_HD_FORMAT_WEEK', NULL, '주차는 YYYY-W01~W53 형식이어야 합니다.'),
 ('final_sku_price', 'SEA_HD_FORMAT_USD', NULL, '최종가는 달러 금액 형식이어야 합니다.'),
 ('original_sku_price', 'SEA_HD_FORMAT_USD', NULL, '원가는 달러 금액 형식이어야 합니다.'),
 ('savings', 'SEA_HD_FORMAT_SAVINGS', NULL, 'savings는 $금액 (할인율%) 형식이어야 합니다.'),
 ('star_rating', 'SEA_HD_FORMAT_RATING', '0~5', '별점은 0~5 사이여야 합니다.'),
 ('count_of_star_ratings', 'SEA_HD_FORMAT_COUNT', NULL, '별점 수는 0 이상의 정수여야 합니다.'),
 ('count_of_reviews', 'SEA_HD_FORMAT_COUNT', NULL, '리뷰 수는 0 이상의 정수여야 합니다.'),
 (product.capacity_column, 'SEA_HD_FORMAT_CAPACITY', NULL, '용량은 7.4 cu ft 형식이어야 합니다.'),
 (product.product_column, 'SEA_HD_FORMAT_ENUM', product.product_value,
  'product는 테이블 제품군과 일치해야 합니다.')
) AS rule(column_name, template_name, rule_value, error_message)
WHERE rule.column_name IS NOT NULL;

UPDATE public.monitoring_format_rules target
SET template_id = template.id, rule_value = seed.rule_value,
    extra_allowed = NULL, forbidden_chars = NULL,
    error_message = seed.error_message, is_active = TRUE, is_del = FALSE,
    updated_id = 'setup_sea_homedepot_format_only', updated_at = NOW()
FROM _sea_hd_format_rules seed
JOIN public.monitoring_format_templates template ON template.name = seed.template_name
WHERE target.table_name = seed.table_name
  AND LOWER(TRIM(target.account_name)) = 'homedepot'
  AND target.column_name = seed.column_name;
INSERT INTO public.monitoring_format_rules
 (table_name, column_name, account_name, template_id, rule_value, error_message,
  is_active, is_del, created_id, created_at, updated_id, updated_at)
SELECT seed.table_name, seed.column_name, 'HomeDepot', template.id,
       seed.rule_value, seed.error_message, TRUE, FALSE,
       'setup_sea_homedepot_format_only', NOW(),
       'setup_sea_homedepot_format_only', NOW()
FROM _sea_hd_format_rules seed
JOIN public.monitoring_format_templates template ON template.name = seed.template_name
WHERE NOT EXISTS (SELECT 1 FROM public.monitoring_format_rules target
                  WHERE target.table_name = seed.table_name
                    AND LOWER(TRIM(target.account_name)) = 'homedepot'
                    AND target.column_name = seed.column_name);

COMMIT;

-- Expected: REF 11, LDY 11, LDY_DRYER 10 active rules.
SELECT table_name, COUNT(*) AS active_format_rules
FROM public.monitoring_format_rules
WHERE table_name IN ('ref_retail_com', 'ldy_retail_com', 'ldy_dryer_retail')
  AND LOWER(TRIM(account_name)) = 'homedepot'
  AND is_active = TRUE AND is_del = FALSE
GROUP BY table_name ORDER BY table_name;
