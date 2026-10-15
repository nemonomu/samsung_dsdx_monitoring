-- SEA HomeDepot dryer only: 10 format fields, item duplicate key, 7 cross-field rules.
-- Requires setup_homedepot_dryer (NULL onboarding). No collected rows are changed.
BEGIN;
CREATE TEMP TABLE _hd_sources (product_line text, table_name text) ON COMMIT DROP;
INSERT INTO _hd_sources VALUES ('sea_ldy_dryer', 'public.ldy_dryer_retail');
CREATE TEMP TABLE _hd_format_templates (
    name text PRIMARY KEY, check_type text, pattern text, description text
) ON COMMIT DROP;
INSERT INTO _hd_format_templates VALUES
 ('SEA_HOMEDEPOT_DRYER_ENUM', 'enum', NULL, 'HomeDepot allowed identity values'),
 ('SEA_HOMEDEPOT_DRYER_WEEK', 'regex',
  $pattern$^[0-9]{4}-W(?:0[1-9]|[1-4][0-9]|5[0-3])$$pattern$,
  'HomeDepot year and week, e.g. 2026-W38'),
 ('SEA_HOMEDEPOT_DRYER_USD', 'regex',
  $pattern$^[$](?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)(?:\.[0-9]{1,2})?$$pattern$,
  'HomeDepot USD price, e.g. $1,249.00'),
 ('SEA_HOMEDEPOT_DRYER_SAVINGS', 'regex',
  $pattern$^[$](?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)(?:\.[0-9]{1,2})? \((?:[0-9]|[1-9][0-9]|100)%\)$$pattern$,
  'HomeDepot saving amount and percentage, e.g. $150.00 (11%)'),
 ('SEA_HOMEDEPOT_DRYER_RATING', 'range_float', NULL, 'HomeDepot star rating between 0 and 5'),
 ('SEA_HOMEDEPOT_DRYER_COUNT', 'regex',
  $pattern$^(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)$$pattern$,
  'HomeDepot nonnegative integer count'),
 ('SEA_HOMEDEPOT_DRYER_CAPACITY', 'regex',
  $pattern$^[0-9]+(?:\.[0-9]+)? cu ft$$pattern$,
  'HomeDepot capacity in cubic feet, e.g. 0.75 cu ft');

UPDATE public.monitoring_format_templates target
SET check_type = seed.check_type, pattern = seed.pattern, description = seed.description,
    is_active = TRUE, updated_at = NOW(), updated_id = 'setup_homedepot_dryer_validation'
FROM _hd_format_templates seed WHERE target.name = seed.name;
INSERT INTO public.monitoring_format_templates
 (name, description, check_type, pattern, is_active, created_id, created_at, updated_id, updated_at)
SELECT name, description, check_type, pattern, TRUE, 'setup_homedepot_dryer_validation', NOW(), 'setup_homedepot_dryer_validation', NOW()
FROM _hd_format_templates seed
WHERE NOT EXISTS (SELECT 1 FROM public.monitoring_format_templates target WHERE target.name = seed.name);

CREATE TEMP TABLE _hd_format_rules (
    table_name text, column_name text, template_name text, rule_value text, error_message text
) ON COMMIT DROP;
INSERT INTO _hd_format_rules
SELECT SPLIT_PART(source.table_name, '.', 2), rule.column_name, rule.template_name,
       rule.rule_value, rule.error_message
FROM _hd_sources source CROSS JOIN (VALUES
 ('account_name', 'SEA_HOMEDEPOT_DRYER_ENUM', 'HomeDepot', 'account_name은 HomeDepot이어야 합니다.'),
 ('calendar_week', 'SEA_HOMEDEPOT_DRYER_WEEK', NULL, 'calendar_week는 2026-W38 같은 YYYY-W01~W53 형식이어야 합니다.'),
 ('country', 'SEA_HOMEDEPOT_DRYER_ENUM', 'SEA', 'country는 SEA여야 합니다.'),
 ('final_sku_price', 'SEA_HOMEDEPOT_DRYER_USD', NULL::text, '가격은 $1,249.00 같은 달러 금액 형식이어야 합니다.'),
 ('original_sku_price', 'SEA_HOMEDEPOT_DRYER_USD', NULL, '원가는 $1,249.00 같은 달러 금액 형식이어야 합니다.'),
 ('savings', 'SEA_HOMEDEPOT_DRYER_SAVINGS', NULL, '할인은 $150.00 (11%) 같은 금액·할인율 형식이어야 합니다.'),
 ('star_rating', 'SEA_HOMEDEPOT_DRYER_RATING', '0~5', '별점은 0~5 사이의 숫자여야 합니다.'),
 ('count_of_star_ratings', 'SEA_HOMEDEPOT_DRYER_COUNT', NULL, '별점 수는 0 이상의 정수여야 합니다.'),
 ('count_of_reviews', 'SEA_HOMEDEPOT_DRYER_COUNT', NULL, '리뷰 수는 0 이상의 정수여야 합니다.')
) rule(column_name, template_name, rule_value, error_message);
INSERT INTO _hd_format_rules
SELECT SPLIT_PART(table_name, '.', 2), 'capacity',
       'SEA_HOMEDEPOT_DRYER_CAPACITY', NULL, '용량은 21 cu ft 또는 0.75 cu ft 같은 형식이어야 합니다.'
FROM _hd_sources;

UPDATE public.monitoring_format_rules target
SET template_id = template.id, rule_value = seed.rule_value, extra_allowed = NULL,
    forbidden_chars = NULL, error_message = seed.error_message, is_active = TRUE, is_del = FALSE,
    updated_id = 'setup_homedepot_dryer_validation', updated_at = NOW()
FROM _hd_format_rules seed JOIN public.monitoring_format_templates template ON template.name = seed.template_name
WHERE target.table_name = seed.table_name AND LOWER(TRIM(target.account_name)) = 'homedepot'
  AND target.column_name = seed.column_name;
INSERT INTO public.monitoring_format_rules
 (table_name, column_name, account_name, template_id, rule_value, error_message,
  is_active, is_del, created_id, created_at, updated_id, updated_at)
SELECT seed.table_name, seed.column_name, 'HomeDepot', template.id, seed.rule_value, seed.error_message,
       TRUE, FALSE, 'setup_homedepot_dryer_validation', NOW(), 'setup_homedepot_dryer_validation', NOW()
FROM _hd_format_rules seed JOIN public.monitoring_format_templates template ON template.name = seed.template_name
WHERE NOT EXISTS (SELECT 1 FROM public.monitoring_format_rules target
                  WHERE target.table_name = seed.table_name AND target.column_name = seed.column_name
                    AND LOWER(TRIM(target.account_name)) = 'homedepot');

-- HomeDepot does not use the 90% threshold, page type, review body or recommendation rules.
UPDATE public.monitoring_validation_rules
SET is_active = FALSE
WHERE rule_type = 'crossfield'
  AND section_code IN ('sea_ldy_dryer_retail')
  AND table_name IN ('public.ldy_dryer_retail')
  AND LOWER(TRIM(retailer)) = 'homedepot'
  AND validation_type NOT IN (
      'review_count_match', 'rating_count_presence', 'final_original_price',
      'savings_missing', 'original_missing', 'savings_amount_match', 'final_missing'
  );

WITH products (
    product_line, category, section_code, section_name, table_name
) AS (
    VALUES ('sea_ldy_dryer', 'LDY_DRYER', 'sea_ldy_dryer_retail', 'SEA LDY_DRYER', 'public.ldy_dryer_retail')
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
    date_column = 'crawl_datetime',
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
    'crawl_datetime',
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
    'setup_homedepot_dryer_validation'
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
SET is_editable = TRUE, updated_at = NOW(), updated_id = 'setup_homedepot_dryer_validation'
WHERE product_line IN ('sea_ldy_dryer')
  AND LOWER(TRIM(retailer)) = 'homedepot'
  AND column_name IN ('count_of_reviews', 'count_of_star_ratings', 'star_rating',
                      'final_sku_price', 'original_sku_price', 'savings')
  AND is_active IS TRUE AND COALESCE(is_del, FALSE) IS FALSE;


-- Registration follows the same item key as the source uniqueness constraint.
UPDATE public.monitoring_retail_columns
SET duplicate_key = (column_name = 'item'), updated_at = NOW(),
    updated_id = 'setup_homedepot_dryer_validation'
WHERE product_line = 'sea_ldy_dryer' AND LOWER(TRIM(retailer)) = 'homedepot';

-- Make format identity/week fields editable through the existing audited editor.
INSERT INTO public.monitoring_retail_columns
 (product_line, column_name, retailer, duplicate_key, skip_missing_check,
  is_editable, is_active, is_del, created_at, created_id, updated_at, updated_id)
SELECT 'sea_ldy_dryer', f.column_name, 'HomeDepot', FALSE, TRUE,
 TRUE, TRUE, FALSE, NOW(), 'setup_homedepot_dryer_validation', NOW(), 'setup_homedepot_dryer_validation'
FROM _hd_format_rules f
WHERE NOT EXISTS (SELECT 1 FROM public.monitoring_retail_columns c
 WHERE c.product_line = 'sea_ldy_dryer' AND LOWER(TRIM(c.retailer)) = 'homedepot'
 AND c.column_name = f.column_name);
UPDATE public.monitoring_retail_columns c
SET is_editable = TRUE, is_active = TRUE, is_del = FALSE,
    updated_at = NOW(), updated_id = 'setup_homedepot_dryer_validation'
WHERE c.product_line = 'sea_ldy_dryer' AND LOWER(TRIM(c.retailer)) = 'homedepot'
 AND c.column_name IN (SELECT column_name FROM _hd_format_rules);

SELECT 'crossfield' AS kind, COUNT(*) AS configured
FROM public.monitoring_validation_rules
WHERE rule_type = 'crossfield' AND section_code = 'sea_ldy_dryer_retail'
 AND LOWER(TRIM(retailer)) = 'homedepot' AND is_active
UNION ALL
SELECT 'duplicate', COUNT(*) FROM public.monitoring_retail_columns
WHERE product_line = 'sea_ldy_dryer' AND LOWER(TRIM(retailer)) = 'homedepot'
 AND duplicate_key AND is_active AND NOT is_del
UNION ALL
SELECT 'format', COUNT(*) FROM public.monitoring_format_rules
WHERE table_name = 'ldy_dryer_retail' AND LOWER(TRIM(account_name)) = 'homedepot'
 AND is_active AND NOT is_del
ORDER BY kind;
COMMIT;
