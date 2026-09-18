-- SEA HomeDepot REF/LDY Layer 2: 11 NULL fields and 11 format fields per product.
-- Idempotent. Does not alter SEM HomeDepot, other retailers, source data or Layer 3 rules.
BEGIN;

CREATE TEMP TABLE _hd_sources (
    product_line text PRIMARY KEY,
    category_name text NOT NULL,
    display_name text NOT NULL,
    display_order integer NOT NULL,
    check_name text NOT NULL,
    table_name text NOT NULL
) ON COMMIT DROP;

INSERT INTO _hd_sources VALUES
    ('sea_ref', 'sea_ref_retail', 'SEA REF', 2,
     'homedepot_sea_ref', 'public.ref_retail_com'),
    ('sea_ldy', 'sea_ldy_retail', 'SEA LDY', 3,
     'homedepot_sea_ldy', 'public.ldy_retail_com');

CREATE TEMP TABLE _hd_columns (
    product_line text NOT NULL,
    column_name text NOT NULL,
    duplicate_key boolean NOT NULL,
    skip_missing_check boolean NOT NULL,
    is_editable boolean NOT NULL,
    PRIMARY KEY (product_line, column_name)
) ON COMMIT DROP;

-- Ten required common fields, plus seven optional fields.
-- Each product adds its required capacity and optional product type below.
WITH field(column_name, duplicate_key, skip_missing_check, is_editable) AS (
    VALUES
    ('country',               FALSE, FALSE, TRUE),
    ('account_name',          FALSE, FALSE, TRUE),
    ('item',                  TRUE,  FALSE, TRUE),
    ('sku',                   FALSE, FALSE, TRUE),
    ('retailer_sku_name',      FALSE, FALSE, TRUE),
    ('product_url',           FALSE, FALSE, TRUE),
    ('final_sku_price',        FALSE, FALSE, TRUE),
    ('star_rating',           FALSE, FALSE, TRUE),
    ('count_of_star_ratings', FALSE, FALSE, TRUE),
    ('count_of_reviews',       FALSE, FALSE, TRUE),
    ('original_sku_price',     FALSE, TRUE,  TRUE),
    ('savings',                FALSE, TRUE,  TRUE),
    ('main_rank',              FALSE, TRUE,  FALSE),
    ('bsr_rank',               FALSE, TRUE,  FALSE),
    ('crawl_strdatetime',         FALSE, TRUE,  FALSE),
    ('calendar_week',          FALSE, TRUE,  TRUE),
    ('product',                FALSE, TRUE,  TRUE)
)
INSERT INTO _hd_columns
    (product_line, column_name, duplicate_key, skip_missing_check, is_editable)
SELECT source.product_line, field.column_name, field.duplicate_key,
       field.skip_missing_check, field.is_editable
FROM _hd_sources source CROSS JOIN field;

INSERT INTO _hd_columns VALUES
    ('sea_ref', 'ref_capacity',          FALSE, FALSE, TRUE),
    ('sea_ref', 'ref_refrigerator_type', FALSE, TRUE,  FALSE),
    ('sea_ldy', 'ldy_capacity',          FALSE, FALSE, TRUE),
    ('sea_ldy', 'ldy_loading_type',      FALSE, TRUE,  FALSE);

UPDATE public.monitoring_retail_columns AS target
SET duplicate_key = seed.duplicate_key,
    skip_missing_check = seed.skip_missing_check,
    is_editable = seed.is_editable,
    is_active = TRUE, is_del = FALSE,
    updated_at = NOW(), updated_id = 'setup_sea_homedepot'
FROM _hd_columns seed
WHERE LOWER(BTRIM(target.product_line)) = seed.product_line
  AND LOWER(BTRIM(target.retailer)) = 'homedepot'
  AND target.column_name = seed.column_name;

INSERT INTO public.monitoring_retail_columns (
    product_line, column_name, retailer, duplicate_key, skip_missing_check,
    is_editable, is_active, is_del, created_at, created_id, updated_at, updated_id
)
SELECT seed.product_line, seed.column_name, 'HomeDepot', seed.duplicate_key,
       seed.skip_missing_check, seed.is_editable, TRUE, FALSE,
       NOW(), 'setup_sea_homedepot', NOW(), 'setup_sea_homedepot'
FROM _hd_columns seed
WHERE NOT EXISTS (
    SELECT 1 FROM public.monitoring_retail_columns target
    WHERE LOWER(BTRIM(target.product_line)) = seed.product_line
      AND LOWER(BTRIM(target.retailer)) = 'homedepot'
      AND target.column_name = seed.column_name
);

-- Categories are shared with Bestbuy/Lowes. Preserve existing labels/order.
UPDATE public.monitoring_null_category AS target
SET has_retailer = TRUE, is_active = TRUE, is_del = FALSE,
    updated_at = NOW(), updated_id = 'setup_sea_homedepot'
FROM _hd_sources source
WHERE target.category_name = source.category_name;

INSERT INTO public.monitoring_null_category (
    category_name, display_name, display_order, has_retailer,
    is_active, is_del, created_at, created_id
)
SELECT source.category_name, source.display_name, source.display_order,
       TRUE, TRUE, FALSE, NOW(), 'setup_sea_homedepot'
FROM _hd_sources source
WHERE NOT EXISTS (
    SELECT 1 FROM public.monitoring_null_category target
    WHERE target.category_name = source.category_name
);

UPDATE public.monitoring_null_group AS target
SET display_name = 'HomeDepot', table_name = source.table_name,
    date_column = 'crawl_strdatetime', display_order = 3,
    is_active = TRUE, is_del = FALSE,
    updated_at = NOW(), updated_id = 'setup_sea_homedepot'
FROM _hd_sources source
JOIN public.monitoring_null_category category
  ON category.category_name = source.category_name
WHERE target.category_id = category.id
  AND target.check_name = source.check_name;

INSERT INTO public.monitoring_null_group (
    category_id, check_name, display_name, table_name, date_column,
    display_order, is_active, is_del, created_at, created_id
)
SELECT category.id, source.check_name, 'HomeDepot', source.table_name,
       'crawl_strdatetime', 3, TRUE, FALSE, NOW(), 'setup_sea_homedepot'
FROM _hd_sources source
JOIN public.monitoring_null_category category
  ON category.category_name = source.category_name
WHERE NOT EXISTS (
    SELECT 1 FROM public.monitoring_null_group target
    WHERE target.category_id = category.id
      AND target.check_name = source.check_name
);

CREATE TEMP TABLE _hd_null_columns (
    product_line text NOT NULL,
    check_column text NOT NULL,
    display_columns text NOT NULL,
    PRIMARY KEY (product_line, check_column)
) ON COMMIT DROP;

INSERT INTO _hd_null_columns
SELECT product_line, column_name,
       'crawl_strdatetime|item|account_name|country|retailer_sku_name|sku' ||
       CASE
           WHEN column_name IN ('star_rating', 'count_of_star_ratings', 'count_of_reviews')
               THEN '|star_rating|count_of_star_ratings|count_of_reviews'
           WHEN column_name IN ('item', 'sku', 'retailer_sku_name', 'product_url', 'account_name', 'country')
               THEN ''
           ELSE '|' || column_name
       END || '|product_url'
FROM _hd_columns
WHERE skip_missing_check = FALSE;

-- Enforce exactly the agreed eleven NULL fields in each HomeDepot group.
-- Optional prices/discounts are format-checked only when populated.
UPDATE public.monitoring_null_column AS target
SET is_active = FALSE, updated_at = NOW(), updated_id = 'setup_sea_homedepot'
FROM _hd_sources source
JOIN public.monitoring_null_category category
  ON category.category_name = source.category_name
JOIN public.monitoring_null_group null_group
  ON null_group.category_id = category.id
 AND null_group.check_name = source.check_name
WHERE target.group_id = null_group.id
  AND NOT EXISTS (
      SELECT 1 FROM _hd_null_columns seed
      WHERE seed.product_line = source.product_line
        AND seed.check_column = target.check_column
  );

UPDATE public.monitoring_null_column AS target
SET check_type = 'both', display_columns = seed.display_columns,
    query_columns = seed.display_columns, query_days = 0,
    is_active = TRUE, is_del = FALSE,
    updated_at = NOW(), updated_id = 'setup_sea_homedepot'
FROM _hd_null_columns seed
JOIN _hd_sources source ON source.product_line = seed.product_line
JOIN public.monitoring_null_category category
  ON category.category_name = source.category_name
JOIN public.monitoring_null_group null_group
  ON null_group.category_id = category.id
 AND null_group.check_name = source.check_name
WHERE target.group_id = null_group.id
  AND target.check_column = seed.check_column;

INSERT INTO public.monitoring_null_column (
    group_id, check_column, check_type, display_columns, query_columns,
    query_days, is_active, is_del, created_at, created_id
)
SELECT null_group.id, seed.check_column, 'both', seed.display_columns,
       seed.display_columns, 0, TRUE, FALSE, NOW(), 'setup_sea_homedepot'
FROM _hd_null_columns seed
JOIN _hd_sources source ON source.product_line = seed.product_line
JOIN public.monitoring_null_category category
  ON category.category_name = source.category_name
JOIN public.monitoring_null_group null_group
  ON null_group.category_id = category.id
 AND null_group.check_name = source.check_name
WHERE NOT EXISTS (
    SELECT 1 FROM public.monitoring_null_column target
    WHERE target.group_id = null_group.id
      AND target.check_column = seed.check_column
);

CREATE TEMP TABLE _hd_format_templates (
    name text PRIMARY KEY, check_type text, pattern text, description text
) ON COMMIT DROP;
INSERT INTO _hd_format_templates VALUES
 ('SEA_HOMEDEPOT_ENUM', 'enum', NULL, 'HomeDepot allowed identity values'),
 ('SEA_HOMEDEPOT_WEEK', 'regex',
  $pattern$^[0-9]{4}-W(?:0[1-9]|[1-4][0-9]|5[0-3])$$pattern$,
  'HomeDepot year and week, e.g. 2026-W38'),
 ('SEA_HOMEDEPOT_USD', 'regex',
  $pattern$^[$](?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)(?:\.[0-9]{1,2})?$$pattern$,
  'HomeDepot USD price, e.g. $1,249.00'),
 ('SEA_HOMEDEPOT_SAVINGS', 'regex',
  $pattern$^[$](?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)(?:\.[0-9]{1,2})? \((?:[0-9]|[1-9][0-9]|100)%\)$$pattern$,
  'HomeDepot saving amount and percentage, e.g. $150.00 (11%)'),
 ('SEA_HOMEDEPOT_RATING', 'range_float', NULL, 'HomeDepot star rating between 0 and 5'),
 ('SEA_HOMEDEPOT_COUNT', 'regex',
  $pattern$^(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)$$pattern$,
  'HomeDepot nonnegative integer count'),
 ('SEA_HOMEDEPOT_CAPACITY', 'regex',
  $pattern$^[0-9]+(?:\.[0-9]+)? cu ft$$pattern$,
  'HomeDepot capacity in cubic feet, e.g. 0.75 cu ft');

UPDATE public.monitoring_format_templates target
SET check_type = seed.check_type, pattern = seed.pattern, description = seed.description,
    is_active = TRUE, updated_at = NOW(), updated_id = 'setup_sea_homedepot'
FROM _hd_format_templates seed WHERE target.name = seed.name;
INSERT INTO public.monitoring_format_templates
 (name, description, check_type, pattern, is_active, created_id, created_at, updated_id, updated_at)
SELECT name, description, check_type, pattern, TRUE, 'setup_sea_homedepot', NOW(), 'setup_sea_homedepot', NOW()
FROM _hd_format_templates seed
WHERE NOT EXISTS (SELECT 1 FROM public.monitoring_format_templates target WHERE target.name = seed.name);

CREATE TEMP TABLE _hd_format_rules (
    table_name text, column_name text, template_name text, rule_value text, error_message text
) ON COMMIT DROP;
INSERT INTO _hd_format_rules
SELECT SPLIT_PART(source.table_name, '.', 2), rule.column_name, rule.template_name,
       rule.rule_value, rule.error_message
FROM _hd_sources source CROSS JOIN (VALUES
 ('account_name', 'SEA_HOMEDEPOT_ENUM', 'HomeDepot', 'account_name은 HomeDepot이어야 합니다.'),
 ('calendar_week', 'SEA_HOMEDEPOT_WEEK', NULL, 'calendar_week는 2026-W38 같은 YYYY-W01~W53 형식이어야 합니다.'),
 ('country', 'SEA_HOMEDEPOT_ENUM', 'SEA', 'country는 SEA여야 합니다.'),
 ('final_sku_price', 'SEA_HOMEDEPOT_USD', NULL::text, '가격은 $1,249.00 같은 달러 금액 형식이어야 합니다.'),
 ('original_sku_price', 'SEA_HOMEDEPOT_USD', NULL, '원가는 $1,249.00 같은 달러 금액 형식이어야 합니다.'),
 ('savings', 'SEA_HOMEDEPOT_SAVINGS', NULL, '할인은 $150.00 (11%) 같은 금액·할인율 형식이어야 합니다.'),
 ('star_rating', 'SEA_HOMEDEPOT_RATING', '0~5', '별점은 0~5 사이의 숫자여야 합니다.'),
 ('count_of_star_ratings', 'SEA_HOMEDEPOT_COUNT', NULL, '별점 수는 0 이상의 정수여야 합니다.'),
 ('count_of_reviews', 'SEA_HOMEDEPOT_COUNT', NULL, '리뷰 수는 0 이상의 정수여야 합니다.')
) rule(column_name, template_name, rule_value, error_message);
INSERT INTO _hd_format_rules
SELECT SPLIT_PART(table_name, '.', 2), CASE WHEN product_line = 'sea_ref' THEN 'ref_capacity' ELSE 'ldy_capacity' END,
       'SEA_HOMEDEPOT_CAPACITY', NULL, '용량은 21 cu ft 또는 0.75 cu ft 같은 형식이어야 합니다.'
FROM _hd_sources;

INSERT INTO _hd_format_rules
SELECT SPLIT_PART(table_name, '.', 2), 'product', 'SEA_HOMEDEPOT_ENUM',
       UPPER(SPLIT_PART(product_line, '_', 2)), 'product가 테이블 제품군(REF/LDY)과 일치해야 합니다.'
FROM _hd_sources;

UPDATE public.monitoring_format_rules target
SET template_id = template.id, rule_value = seed.rule_value, extra_allowed = NULL,
    forbidden_chars = NULL, error_message = seed.error_message, is_active = TRUE, is_del = FALSE,
    updated_id = 'setup_sea_homedepot', updated_at = NOW()
FROM _hd_format_rules seed JOIN public.monitoring_format_templates template ON template.name = seed.template_name
WHERE target.table_name = seed.table_name AND LOWER(TRIM(target.account_name)) = 'homedepot'
  AND target.column_name = seed.column_name;
INSERT INTO public.monitoring_format_rules
 (table_name, column_name, account_name, template_id, rule_value, error_message,
  is_active, is_del, created_id, created_at, updated_id, updated_at)
SELECT seed.table_name, seed.column_name, 'HomeDepot', template.id, seed.rule_value, seed.error_message,
       TRUE, FALSE, 'setup_sea_homedepot', NOW(), 'setup_sea_homedepot', NOW()
FROM _hd_format_rules seed JOIN public.monitoring_format_templates template ON template.name = seed.template_name
WHERE NOT EXISTS (SELECT 1 FROM public.monitoring_format_rules target
                  WHERE target.table_name = seed.table_name AND target.column_name = seed.column_name
                    AND LOWER(TRIM(target.account_name)) = 'homedepot');

COMMIT;
