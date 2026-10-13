-- Bestbuy dryer only: 11 NULL columns; loading_type is optional.
-- Idempotent configuration only; no source-data, format or cross-field changes.
-- Run on the monitoring database after deploying the matching application code.
BEGIN;

CREATE TEMP TABLE _bestbuy_sources (
    product_line text, product text, category_name text,
    table_name text, date_column text, check_name text
) ON COMMIT DROP;
INSERT INTO _bestbuy_sources VALUES
 ('sea_ldy_dryer', 'LDY_DRYER', 'sea_ldy_dryer_retail', 'public.ldy_dryer_retail', 'crawl_datetime', 'bestbuy_sea_ldy_dryer');

CREATE TEMP TABLE _bestbuy_columns (
    product_line text, column_name text, required boolean, editable boolean,
    PRIMARY KEY (product_line, column_name)
) ON COMMIT DROP;
INSERT INTO _bestbuy_columns
SELECT s.product_line, c.column_name, c.required, c.editable
FROM _bestbuy_sources s CROSS JOIN (VALUES
 ('country', TRUE, TRUE), ('account_name', TRUE, TRUE),
 ('item', TRUE, TRUE), ('retailer_sku_name', TRUE, TRUE),
 ('product_url', TRUE, TRUE), ('final_sku_price', TRUE, TRUE),
 ('star_rating', TRUE, TRUE), ('count_of_star_ratings', TRUE, TRUE),
 ('count_of_reviews', TRUE, TRUE),
 ('original_sku_price', FALSE, TRUE), ('savings', FALSE, TRUE),
 ('main_rank', FALSE, FALSE), ('bsr_rank', FALSE, FALSE)
) c(column_name, required, editable);
INSERT INTO _bestbuy_columns VALUES
 ('sea_ldy_dryer', 'capacity', TRUE, TRUE),
 ('sea_ldy_dryer', 'sku', TRUE, TRUE),
 ('sea_ldy_dryer', 'loading_type', FALSE, FALSE);

UPDATE public.monitoring_retail_columns t
SET duplicate_key = (c.column_name = 'item'), skip_missing_check = NOT c.required,
    is_editable = c.editable, is_active = TRUE, is_del = FALSE,
    updated_at = NOW(), updated_id = 'setup_bestbuy_dryer_layer2'
FROM _bestbuy_columns c
WHERE t.product_line = c.product_line AND LOWER(TRIM(t.retailer)) = 'bestbuy'
  AND t.column_name = c.column_name;
INSERT INTO public.monitoring_retail_columns
 (product_line, column_name, retailer, duplicate_key, skip_missing_check,
  is_editable, is_active, is_del, created_at, created_id, updated_at, updated_id)
SELECT c.product_line, c.column_name, 'Bestbuy', c.column_name = 'item', NOT c.required,
       c.editable, TRUE, FALSE, NOW(), 'setup_bestbuy_dryer_layer2', NOW(), 'setup_bestbuy_dryer_layer2'
FROM _bestbuy_columns c
WHERE NOT EXISTS (SELECT 1 FROM public.monitoring_retail_columns t
 WHERE t.product_line = c.product_line AND LOWER(TRIM(t.retailer)) = 'bestbuy'
 AND t.column_name = c.column_name);

INSERT INTO public.monitoring_null_category
 (category_name, display_name, display_order, has_retailer, is_active, is_del, created_at, created_id)
SELECT s.category_name, 'SEA ' || s.product,
       4,
       TRUE, TRUE, FALSE, NOW(), 'setup_bestbuy_dryer_layer2'
FROM _bestbuy_sources s
WHERE NOT EXISTS (SELECT 1 FROM public.monitoring_null_category c WHERE c.category_name = s.category_name);

UPDATE public.monitoring_null_group g
SET display_name = 'Bestbuy', display_order = 3, table_name = s.table_name, date_column = s.date_column,
    is_active = TRUE, is_del = FALSE, updated_at = NOW(), updated_id = 'setup_bestbuy_dryer_layer2'
FROM _bestbuy_sources s JOIN public.monitoring_null_category c ON c.category_name = s.category_name
WHERE g.category_id = c.id AND g.check_name = s.check_name;
INSERT INTO public.monitoring_null_group
 (category_id, check_name, display_name, table_name, date_column, display_order,
  is_active, is_del, created_at, created_id)
SELECT c.id, s.check_name, 'Bestbuy', s.table_name, s.date_column, 3,
       TRUE, FALSE, NOW(), 'setup_bestbuy_dryer_layer2'
FROM _bestbuy_sources s JOIN public.monitoring_null_category c ON c.category_name = s.category_name
WHERE NOT EXISTS (SELECT 1 FROM public.monitoring_null_group g
 WHERE g.category_id = c.id AND g.check_name = s.check_name);

CREATE TEMP TABLE _bestbuy_null ON COMMIT DROP AS
SELECT g.id AS group_id, f.column_name,
       'id|' || s.date_column || '|item|sku|retailer_sku_name|' || f.column_name ||
       '|star_rating|count_of_star_ratings|count_of_reviews|final_sku_price|original_sku_price|savings|product_url' AS display_columns
FROM _bestbuy_sources s
JOIN _bestbuy_columns f ON f.product_line = s.product_line AND f.required
JOIN public.monitoring_null_category c ON c.category_name = s.category_name
JOIN public.monitoring_null_group g ON g.category_id = c.id AND g.check_name = s.check_name;

UPDATE public.monitoring_null_column t
SET is_active = FALSE, updated_at = NOW(), updated_id = 'setup_bestbuy_dryer_layer2'
WHERE t.group_id IN (SELECT group_id FROM _bestbuy_null)
  AND NOT EXISTS (SELECT 1 FROM _bestbuy_null n WHERE n.group_id = t.group_id AND n.column_name = t.check_column);
UPDATE public.monitoring_null_column t
SET check_type = 'both', display_columns = n.display_columns, query_columns = n.display_columns,
    query_days = 0, is_active = TRUE, is_del = FALSE,
    updated_at = NOW(), updated_id = 'setup_bestbuy_dryer_layer2'
FROM _bestbuy_null n WHERE t.group_id = n.group_id AND t.check_column = n.column_name;
INSERT INTO public.monitoring_null_column
 (group_id, check_column, check_type, display_columns, query_columns, query_days,
  is_active, is_del, created_at, created_id)
SELECT n.group_id, n.column_name, 'both', n.display_columns, n.display_columns, 0,
       TRUE, FALSE, NOW(), 'setup_bestbuy_dryer_layer2'
FROM _bestbuy_null n
WHERE NOT EXISTS (SELECT 1 FROM public.monitoring_null_column t
 WHERE t.group_id = n.group_id AND t.check_column = n.column_name);

-- Expected: LDY_DRYER 11. Duplicates use latest Bestbuy batch + item (read-only).
SELECT s.product, COUNT(*) AS null_columns
FROM _bestbuy_sources s
JOIN public.monitoring_null_category c ON c.category_name = s.category_name
JOIN public.monitoring_null_group g ON g.category_id = c.id AND g.check_name = s.check_name
JOIN public.monitoring_null_column n ON n.group_id = g.id AND n.is_active AND NOT n.is_del
GROUP BY s.product ORDER BY s.product;
COMMIT;
