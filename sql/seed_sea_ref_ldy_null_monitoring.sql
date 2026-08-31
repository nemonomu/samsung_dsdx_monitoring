-- SEA REF/LDY Layer2 NULL validation configuration
-- PostgreSQL only. Run in DBeaver against the database that owns public.ref_retail_com.
-- Idempotent: existing rows are re-enabled/updated; missing rows are inserted.

BEGIN;

CREATE TEMP TABLE _sea_null_category_seed (
    category_name text PRIMARY KEY,
    display_name text NOT NULL,
    display_order integer NOT NULL
) ON COMMIT DROP;

INSERT INTO _sea_null_category_seed
    (category_name, display_name, display_order)
VALUES
    ('sea_ref_retail', 'SEA REF', 2),
    ('sea_ldy_retail', 'SEA LDY', 3);

UPDATE public.monitoring_null_category target
SET display_name = seed.display_name,
    display_order = seed.display_order,
    has_retailer = TRUE,
    is_active = TRUE,
    is_del = FALSE
FROM _sea_null_category_seed seed
WHERE target.category_name = seed.category_name;

INSERT INTO public.monitoring_null_category
    (category_name, display_name, display_order, has_retailer, is_active, is_del)
SELECT
    seed.category_name,
    seed.display_name,
    seed.display_order,
    TRUE,
    TRUE,
    FALSE
FROM _sea_null_category_seed seed
WHERE NOT EXISTS (
    SELECT 1
    FROM public.monitoring_null_category target
    WHERE target.category_name = seed.category_name
);

CREATE TEMP TABLE _sea_null_group_seed (
    product_key text NOT NULL,
    category_name text NOT NULL,
    check_name text NOT NULL,
    display_name text NOT NULL,
    table_name text NOT NULL,
    date_column text NOT NULL,
    display_order integer NOT NULL
) ON COMMIT DROP;

INSERT INTO _sea_null_group_seed
    (product_key, category_name, check_name, display_name,
     table_name, date_column, display_order)
VALUES
    ('ref', 'sea_ref_retail', 'bestbuy_ref', 'Bestbuy',
     'public.ref_retail_com', 'crawl_strdatetime', 1),
    ('ref', 'sea_ref_retail', 'lowes_ref', 'Lowes',
     'public.ref_retail_com', 'crawl_strdatetime', 2),
    ('ldy', 'sea_ldy_retail', 'bestbuy_ldy', 'Bestbuy',
     'public.ldy_retail_com', 'crawl_strdatetime', 1),
    ('ldy', 'sea_ldy_retail', 'lowes_ldy', 'Lowes',
     'public.ldy_retail_com', 'crawl_strdatetime', 2);

UPDATE public.monitoring_null_group target
SET display_name = seed.display_name,
    table_name = seed.table_name,
    date_column = seed.date_column,
    display_order = seed.display_order,
    is_active = TRUE,
    is_del = FALSE
FROM _sea_null_group_seed seed
JOIN public.monitoring_null_category category
  ON category.category_name = seed.category_name
WHERE target.category_id = category.id
  AND target.check_name = seed.check_name;

INSERT INTO public.monitoring_null_group
    (category_id, check_name, display_name, table_name, date_column,
     display_order, is_active, is_del)
SELECT
    category.id,
    seed.check_name,
    seed.display_name,
    seed.table_name,
    seed.date_column,
    seed.display_order,
    TRUE,
    FALSE
FROM _sea_null_group_seed seed
JOIN public.monitoring_null_category category
  ON category.category_name = seed.category_name
WHERE NOT EXISTS (
    SELECT 1
    FROM public.monitoring_null_group target
    WHERE target.category_id = category.id
      AND target.check_name = seed.check_name
);

CREATE TEMP TABLE _sea_null_column_seed (
    product_key text NOT NULL,
    check_column text NOT NULL,
    check_type text NOT NULL,
    display_columns text NOT NULL,
    query_columns text NOT NULL,
    query_days integer NOT NULL
) ON COMMIT DROP;

INSERT INTO _sea_null_column_seed
    (product_key, check_column, check_type,
     display_columns, query_columns, query_days)
VALUES
    ('ref', 'count_of_reviews', 'both',
     'id|crawl_strdatetime|batch_id|account_name|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|ref_capacity|ref_refrigerator_type|product_url',
     'id|crawl_strdatetime|batch_id|account_name|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|ref_capacity|ref_refrigerator_type|product_url', 0),
    ('ref', 'count_of_star_ratings', 'both',
     'id|crawl_strdatetime|batch_id|account_name|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|ref_capacity|ref_refrigerator_type|product_url',
     'id|crawl_strdatetime|batch_id|account_name|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|ref_capacity|ref_refrigerator_type|product_url', 0),
    ('ref', 'final_sku_price', 'both',
     'id|crawl_strdatetime|batch_id|account_name|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|ref_capacity|ref_refrigerator_type|product_url',
     'id|crawl_strdatetime|batch_id|account_name|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|ref_capacity|ref_refrigerator_type|product_url', 0),
    ('ref', 'ref_capacity', 'both',
     'id|crawl_strdatetime|batch_id|account_name|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|ref_capacity|ref_refrigerator_type|product_url',
     'id|crawl_strdatetime|batch_id|account_name|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|ref_capacity|ref_refrigerator_type|product_url', 0),
    ('ref', 'ref_refrigerator_type', 'both',
     'id|crawl_strdatetime|batch_id|account_name|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|ref_capacity|ref_refrigerator_type|product_url',
     'id|crawl_strdatetime|batch_id|account_name|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|ref_capacity|ref_refrigerator_type|product_url', 0),
    ('ref', 'retailer_sku_name', 'both',
     'id|crawl_strdatetime|batch_id|account_name|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|ref_capacity|ref_refrigerator_type|product_url',
     'id|crawl_strdatetime|batch_id|account_name|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|ref_capacity|ref_refrigerator_type|product_url', 0),
    ('ref', 'sku', 'both',
     'id|crawl_strdatetime|batch_id|account_name|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|ref_capacity|ref_refrigerator_type|product_url',
     'id|crawl_strdatetime|batch_id|account_name|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|ref_capacity|ref_refrigerator_type|product_url', 0),
    ('ref', 'star_rating', 'both',
     'id|crawl_strdatetime|batch_id|account_name|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|ref_capacity|ref_refrigerator_type|product_url',
     'id|crawl_strdatetime|batch_id|account_name|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|ref_capacity|ref_refrigerator_type|product_url', 0),
    ('ldy', 'count_of_reviews', 'both',
     'id|crawl_strdatetime|batch_id|account_name|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|product_url',
     'id|crawl_strdatetime|batch_id|account_name|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|product_url', 0),
    ('ldy', 'count_of_star_ratings', 'both',
     'id|crawl_strdatetime|batch_id|account_name|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|product_url',
     'id|crawl_strdatetime|batch_id|account_name|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|product_url', 0),
    ('ldy', 'final_sku_price', 'both',
     'id|crawl_strdatetime|batch_id|account_name|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|product_url',
     'id|crawl_strdatetime|batch_id|account_name|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|product_url', 0),
    ('ldy', 'retailer_sku_name', 'both',
     'id|crawl_strdatetime|batch_id|account_name|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|product_url',
     'id|crawl_strdatetime|batch_id|account_name|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|product_url', 0),
    ('ldy', 'sku', 'both',
     'id|crawl_strdatetime|batch_id|account_name|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|product_url',
     'id|crawl_strdatetime|batch_id|account_name|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|product_url', 0),
    ('ldy', 'star_rating', 'both',
     'id|crawl_strdatetime|batch_id|account_name|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|product_url',
     'id|crawl_strdatetime|batch_id|account_name|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|product_url', 0);

UPDATE public.monitoring_null_column target
SET check_type = seed.check_type,
    display_columns = seed.display_columns,
    query_columns = seed.query_columns,
    query_days = seed.query_days,
    is_active = TRUE,
    is_del = FALSE
FROM _sea_null_column_seed seed
JOIN _sea_null_group_seed group_seed
  ON group_seed.product_key = seed.product_key
JOIN public.monitoring_null_category category
  ON category.category_name = group_seed.category_name
JOIN public.monitoring_null_group null_group
  ON null_group.category_id = category.id
 AND null_group.check_name = group_seed.check_name
WHERE target.group_id = null_group.id
  AND target.check_column = seed.check_column;

INSERT INTO public.monitoring_null_column
    (group_id, check_column, check_type, display_columns,
     query_columns, query_days, is_active, is_del)
SELECT
    null_group.id,
    seed.check_column,
    seed.check_type,
    seed.display_columns,
    seed.query_columns,
    seed.query_days,
    TRUE,
    FALSE
FROM _sea_null_column_seed seed
JOIN _sea_null_group_seed group_seed
  ON group_seed.product_key = seed.product_key
JOIN public.monitoring_null_category category
  ON category.category_name = group_seed.category_name
JOIN public.monitoring_null_group null_group
  ON null_group.category_id = category.id
 AND null_group.check_name = group_seed.check_name
WHERE NOT EXISTS (
    SELECT 1
    FROM public.monitoring_null_column target
    WHERE target.group_id = null_group.id
      AND target.check_column = seed.check_column
);

COMMIT;

-- Expected result: REF 8 rows per retailer, LDY 6 rows per retailer, 28 total.
SELECT
    REGEXP_REPLACE(LOWER(null_group.table_name), '^.*\.', '') AS table_name,
    null_group.display_name AS retailer,
    COUNT(*) AS configured_columns,
    STRING_AGG(null_column.check_column, ', ' ORDER BY null_column.check_column)
        AS check_columns
FROM public.monitoring_null_column null_column
JOIN public.monitoring_null_group null_group
  ON null_group.id = null_column.group_id
JOIN public.monitoring_null_category category
  ON category.id = null_group.category_id
WHERE category.category_name IN ('sea_ref_retail', 'sea_ldy_retail')
  AND category.is_active = TRUE
  AND category.is_del = FALSE
  AND null_group.is_active = TRUE
  AND null_group.is_del = FALSE
  AND null_column.is_active = TRUE
  AND null_column.is_del = FALSE
GROUP BY
    REGEXP_REPLACE(LOWER(null_group.table_name), '^.*\.', ''),
    null_group.display_name
ORDER BY table_name, retailer;
