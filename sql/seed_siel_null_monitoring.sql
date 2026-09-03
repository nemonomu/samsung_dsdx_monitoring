-- SIEL Layer2 NULL validation configuration (TV/REF/LDY)
-- PostgreSQL only. Review and run manually in DBeaver.
-- This script does not create format or duplicate validation rules.
-- Exact expected active rules: 40 (Amazon 16, Flipkart 24).

BEGIN;

DO $$
BEGIN
    IF EXISTS (
        SELECT category_name
        FROM public.monitoring_null_category
        WHERE category_name IN (
            'siel_tv_retail', 'siel_ref_retail', 'siel_ldy_retail'
        )
        GROUP BY category_name
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'Duplicate SIEL NULL categories exist; resolve them before seeding';
    END IF;
END $$;

CREATE TEMP TABLE _siel_null_category_seed (
    category_name text PRIMARY KEY,
    display_name text NOT NULL,
    display_order integer NOT NULL
) ON COMMIT DROP;

INSERT INTO _siel_null_category_seed
    (category_name, display_name, display_order)
VALUES
    ('siel_tv_retail', 'SIEL TV', 4),
    ('siel_ref_retail', 'SIEL REF', 5),
    ('siel_ldy_retail', 'SIEL LDY', 6);

UPDATE public.monitoring_null_category target
SET display_name = seed.display_name,
    display_order = seed.display_order,
    has_retailer = TRUE,
    is_active = TRUE,
    is_del = FALSE
FROM _siel_null_category_seed seed
WHERE target.category_name = seed.category_name;

INSERT INTO public.monitoring_null_category
    (category_name, display_name, display_order, has_retailer, is_active, is_del)
SELECT seed.category_name, seed.display_name, seed.display_order,
       TRUE, TRUE, FALSE
FROM _siel_null_category_seed seed
WHERE NOT EXISTS (
    SELECT 1
    FROM public.monitoring_null_category target
    WHERE target.category_name = seed.category_name
);

CREATE TEMP TABLE _siel_null_group_seed (
    source_key text NOT NULL,
    category_name text NOT NULL,
    retailer_key text NOT NULL,
    check_name text NOT NULL,
    display_name text NOT NULL,
    table_name text NOT NULL,
    date_column text NOT NULL,
    display_order integer NOT NULL,
    PRIMARY KEY (category_name, check_name)
) ON COMMIT DROP;

INSERT INTO _siel_null_group_seed
    (source_key, category_name, retailer_key, check_name, display_name,
     table_name, date_column, display_order)
VALUES
    ('siel_tv', 'siel_tv_retail', 'amazon', 'amazon_siel_tv', 'Amazon',
     'dx_siel.dx_siel_tv_retail_com', 'crawl_datetime', 1),
    ('siel_tv', 'siel_tv_retail', 'flipkart', 'flipkart_siel_tv', 'Flipkart',
     'dx_siel.dx_siel_tv_retail_com', 'crawl_datetime', 2),
    ('siel_ref', 'siel_ref_retail', 'amazon', 'amazon_siel_ref', 'Amazon',
     'dx_siel.dx_siel_ref_retail_com', 'crawl_datetime', 1),
    ('siel_ref', 'siel_ref_retail', 'flipkart', 'flipkart_siel_ref', 'Flipkart',
     'dx_siel.dx_siel_ref_retail_com', 'crawl_datetime', 2),
    ('siel_ldy', 'siel_ldy_retail', 'amazon', 'amazon_siel_ldy', 'Amazon',
     'dx_siel.dx_siel_ldy_retail_com', 'crawl_datetime', 1),
    ('siel_ldy', 'siel_ldy_retail', 'flipkart', 'flipkart_siel_ldy', 'Flipkart',
     'dx_siel.dx_siel_ldy_retail_com', 'crawl_datetime', 2);

DO $$
BEGIN
    IF EXISTS (
        SELECT category.category_name, null_group.check_name
        FROM public.monitoring_null_group null_group
        JOIN public.monitoring_null_category category
          ON category.id = null_group.category_id
        WHERE category.category_name IN (
            'siel_tv_retail', 'siel_ref_retail', 'siel_ldy_retail'
        )
        GROUP BY category.category_name, null_group.check_name
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'Duplicate SIEL NULL groups exist; resolve them before seeding';
    END IF;
END $$;

UPDATE public.monitoring_null_group target
SET display_name = seed.display_name,
    table_name = seed.table_name,
    date_column = seed.date_column,
    display_order = seed.display_order,
    is_active = TRUE,
    is_del = FALSE
FROM _siel_null_group_seed seed
JOIN public.monitoring_null_category category
  ON category.category_name = seed.category_name
WHERE target.category_id = category.id
  AND target.check_name = seed.check_name;

INSERT INTO public.monitoring_null_group
    (category_id, check_name, display_name, table_name, date_column,
     display_order, is_active, is_del)
SELECT category.id, seed.check_name, seed.display_name, seed.table_name,
       seed.date_column, seed.display_order, TRUE, FALSE
FROM _siel_null_group_seed seed
JOIN public.monitoring_null_category category
  ON category.category_name = seed.category_name
WHERE NOT EXISTS (
    SELECT 1
    FROM public.monitoring_null_group target
    WHERE target.category_id = category.id
      AND target.check_name = seed.check_name
);

-- Disable stale groups only inside the three SIEL NULL categories. This is
-- reversible and prevents an old group from adding unapproved checks.
UPDATE public.monitoring_null_group target
SET is_active = FALSE
FROM public.monitoring_null_category category
WHERE target.category_id = category.id
  AND category.category_name IN (
      'siel_tv_retail', 'siel_ref_retail', 'siel_ldy_retail'
  )
  AND NOT EXISTS (
      SELECT 1
      FROM _siel_null_group_seed seed
      WHERE seed.category_name = category.category_name
        AND seed.check_name = target.check_name
  );

CREATE TEMP TABLE _siel_null_column_seed (
    source_key text NOT NULL,
    retailer_key text NOT NULL,
    check_column text NOT NULL,
    PRIMARY KEY (source_key, retailer_key, check_column)
) ON COMMIT DROP;

INSERT INTO _siel_null_column_seed
    (source_key, retailer_key, check_column)
VALUES
    ('siel_ldy', 'amazon', 'count_of_star_ratings'),
    ('siel_ldy', 'amazon', 'final_sku_price'),
    ('siel_ldy', 'amazon', 'retailer_sku_name'),
    ('siel_ldy', 'amazon', 'sku'),
    ('siel_ldy', 'amazon', 'star_rating'),
    ('siel_ref', 'amazon', 'count_of_star_ratings'),
    ('siel_ref', 'amazon', 'final_sku_price'),
    ('siel_ref', 'amazon', 'retailer_sku_name'),
    ('siel_ref', 'amazon', 'sku'),
    ('siel_ref', 'amazon', 'star_rating'),
    ('siel_tv', 'amazon', 'count_of_star_ratings'),
    ('siel_tv', 'amazon', 'final_sku_price'),
    ('siel_tv', 'amazon', 'retailer_sku_name'),
    ('siel_tv', 'amazon', 'screen_size'),
    ('siel_tv', 'amazon', 'sku'),
    ('siel_tv', 'amazon', 'star_rating'),
    ('siel_ldy', 'flipkart', 'count_of_reviews'),
    ('siel_ldy', 'flipkart', 'count_of_star_ratings'),
    ('siel_ldy', 'flipkart', 'final_sku_price'),
    ('siel_ldy', 'flipkart', 'ldy_capacity'),
    ('siel_ldy', 'flipkart', 'retailer_sku_name'),
    ('siel_ldy', 'flipkart', 'sku'),
    ('siel_ldy', 'flipkart', 'star_rating'),
    ('siel_ref', 'flipkart', 'count_of_reviews'),
    ('siel_ref', 'flipkart', 'count_of_star_ratings'),
    ('siel_ref', 'flipkart', 'final_sku_price'),
    ('siel_ref', 'flipkart', 'ref_capacity'),
    ('siel_ref', 'flipkart', 'ref_refrigerator_type'),
    ('siel_ref', 'flipkart', 'retailer_sku_name'),
    ('siel_ref', 'flipkart', 'sku'),
    ('siel_ref', 'flipkart', 'star_rating'),
    ('siel_tv', 'flipkart', 'count_of_reviews'),
    ('siel_tv', 'flipkart', 'count_of_star_ratings'),
    ('siel_tv', 'flipkart', 'estimated_annual_electricity_use'),
    ('siel_tv', 'flipkart', 'final_sku_price'),
    ('siel_tv', 'flipkart', 'model_year'),
    ('siel_tv', 'flipkart', 'retailer_sku_name'),
    ('siel_tv', 'flipkart', 'screen_size'),
    ('siel_tv', 'flipkart', 'sku'),
    ('siel_tv', 'flipkart', 'star_rating');

CREATE TEMP TABLE _siel_null_rule_seed AS
SELECT
    group_seed.category_name,
    group_seed.check_name,
    column_seed.check_column,
    'both'::text AS check_type,
    CASE
        WHEN column_seed.check_column IN (
            'item', 'account_name', 'country', 'sku', 'retailer_sku_name',
            'product_url'
        ) THEN
            'crawl_datetime|item|account_name|country|sku|retailer_sku_name|product_url'
        ELSE
            'crawl_datetime|item|account_name|country|sku|retailer_sku_name|'
            || column_seed.check_column || '|product_url'
    END AS display_columns,
    CASE column_seed.source_key
        WHEN 'siel_tv' THEN
            'id|crawl_datetime|batch_id|account_name|country|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|screen_size|model_year|estimated_annual_electricity_use|product_url'
        WHEN 'siel_ref' THEN
            'id|crawl_datetime|batch_id|account_name|country|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|ref_capacity|ref_refrigerator_type|product_url'
        ELSE
            'id|crawl_datetime|batch_id|account_name|country|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|ldy_capacity|product_url'
    END AS query_columns,
    0::integer AS query_days
FROM _siel_null_column_seed column_seed
JOIN _siel_null_group_seed group_seed
  ON group_seed.source_key = column_seed.source_key
 AND group_seed.retailer_key = column_seed.retailer_key;

DO $$
BEGIN
    IF EXISTS (
        SELECT null_column.group_id, null_column.check_column
        FROM public.monitoring_null_column null_column
        JOIN public.monitoring_null_group null_group
          ON null_group.id = null_column.group_id
        JOIN public.monitoring_null_category category
          ON category.id = null_group.category_id
        WHERE category.category_name IN (
            'siel_tv_retail', 'siel_ref_retail', 'siel_ldy_retail'
        )
        GROUP BY null_column.group_id, null_column.check_column
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'Duplicate SIEL NULL columns exist; resolve them before seeding';
    END IF;
END $$;

UPDATE public.monitoring_null_column target
SET check_type = seed.check_type,
    display_columns = seed.display_columns,
    query_columns = seed.query_columns,
    query_days = seed.query_days,
    is_active = TRUE,
    is_del = FALSE
FROM _siel_null_rule_seed seed
JOIN public.monitoring_null_category category
  ON category.category_name = seed.category_name
JOIN public.monitoring_null_group null_group
  ON null_group.category_id = category.id
 AND null_group.check_name = seed.check_name
WHERE target.group_id = null_group.id
  AND target.check_column = seed.check_column;

INSERT INTO public.monitoring_null_column
    (group_id, check_column, check_type, display_columns,
     query_columns, query_days, is_active, is_del)
SELECT null_group.id, seed.check_column, seed.check_type,
       seed.display_columns, seed.query_columns, seed.query_days,
       TRUE, FALSE
FROM _siel_null_rule_seed seed
JOIN public.monitoring_null_category category
  ON category.category_name = seed.category_name
JOIN public.monitoring_null_group null_group
  ON null_group.category_id = category.id
 AND null_group.check_name = seed.check_name
WHERE NOT EXISTS (
    SELECT 1
    FROM public.monitoring_null_column target
    WHERE target.group_id = null_group.id
      AND target.check_column = seed.check_column
);

-- Disable columns not present in the user-approved 40-rule matrix. No row is
-- deleted, so a DBeaver operator can re-enable a row if policy changes later.
UPDATE public.monitoring_null_column target
SET is_active = FALSE
FROM public.monitoring_null_group null_group
JOIN public.monitoring_null_category category
  ON category.id = null_group.category_id
WHERE target.group_id = null_group.id
  AND category.category_name IN (
      'siel_tv_retail', 'siel_ref_retail', 'siel_ldy_retail'
  )
  AND NOT EXISTS (
      SELECT 1
      FROM _siel_null_rule_seed seed
      WHERE seed.category_name = category.category_name
        AND seed.check_name = null_group.check_name
        AND seed.check_column = target.check_column
  );

DO $$
DECLARE
    active_rule_count integer;
BEGIN
    SELECT COUNT(*)
    INTO active_rule_count
    FROM public.monitoring_null_column null_column
    JOIN public.monitoring_null_group null_group
      ON null_group.id = null_column.group_id
    JOIN public.monitoring_null_category category
      ON category.id = null_group.category_id
    WHERE category.category_name IN (
        'siel_tv_retail', 'siel_ref_retail', 'siel_ldy_retail'
    )
      AND category.is_active = TRUE
      AND category.is_del = FALSE
      AND null_group.is_active = TRUE
      AND null_group.is_del = FALSE
      AND null_column.is_active = TRUE
      AND null_column.is_del = FALSE;

    IF active_rule_count <> 40 THEN
        RAISE EXCEPTION
            'Expected 40 active SIEL NULL rules, found %', active_rule_count;
    END IF;
END $$;

COMMIT;

-- Verification result: six rows with counts 6/9, 5/8, 5/7.
SELECT
    category.category_name,
    null_group.display_name AS retailer,
    COUNT(*) AS configured_columns,
    STRING_AGG(null_column.check_column, ', ' ORDER BY null_column.check_column)
        AS check_columns
FROM public.monitoring_null_column null_column
JOIN public.monitoring_null_group null_group
  ON null_group.id = null_column.group_id
JOIN public.monitoring_null_category category
  ON category.id = null_group.category_id
WHERE category.category_name IN (
    'siel_tv_retail', 'siel_ref_retail', 'siel_ldy_retail'
)
  AND category.is_active = TRUE
  AND category.is_del = FALSE
  AND null_group.is_active = TRUE
  AND null_group.is_del = FALSE
  AND null_column.is_active = TRUE
  AND null_column.is_del = FALSE
GROUP BY category.category_name, category.display_order,
         null_group.display_name, null_group.display_order
ORDER BY category.display_order, null_group.display_order;
