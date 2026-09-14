-- HomeDepot SEM REF/LDY shared columns and Layer 2 NULL configuration.
-- PostgreSQL; run against the existing monitoring database after deploying
-- the HomeDepot validation code. Re-running updates the same settings.
-- No source data, source schema, collection schedules or Liverpool groups
-- are changed. SEM format and cross-field rules are implemented in Python;
-- inserting rows into generic format/cross-field rule tables is unnecessary.

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
    ('sem_ref', 'sem_ref_retail', 'SEM REF', 8,
     'homedepot_sem_ref', 'dx_sem.dx_sem_ref_retail_com'),
    ('sem_ldy', 'sem_ldy_retail', 'SEM LDY', 9,
     'homedepot_sem_ldy', 'dx_sem.dx_sem_ldy_retail_com');

CREATE TEMP TABLE _hd_columns (
    product_line text NOT NULL,
    column_name text NOT NULL,
    duplicate_key boolean NOT NULL,
    skip_missing_check boolean NOT NULL,
    is_editable boolean NOT NULL,
    PRIMARY KEY (product_line, column_name)
) ON COMMIT DROP;

-- Ten required common fields, plus six optional fields.
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
    ('crawl_datetime',         FALSE, TRUE,  FALSE),
    ('calendar_week',          FALSE, TRUE,  TRUE)
)
INSERT INTO _hd_columns
    (product_line, column_name, duplicate_key, skip_missing_check, is_editable)
SELECT source.product_line, field.column_name, field.duplicate_key,
       field.skip_missing_check, field.is_editable
FROM _hd_sources source CROSS JOIN field;

INSERT INTO _hd_columns VALUES
    ('sem_ref', 'ref_capacity',          FALSE, FALSE, TRUE),
    ('sem_ref', 'ref_refrigerator_type', FALSE, TRUE,  TRUE),
    ('sem_ldy', 'ldy_capacity',          FALSE, FALSE, TRUE),
    ('sem_ldy', 'ldy_loading_type',      FALSE, TRUE,  TRUE);

UPDATE public.monitoring_retail_columns AS target
SET duplicate_key = seed.duplicate_key,
    skip_missing_check = seed.skip_missing_check,
    is_editable = seed.is_editable,
    is_active = TRUE, is_del = FALSE,
    updated_at = NOW(), updated_id = 'setup_sem_homedepot'
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
       NOW(), 'setup_sem_homedepot', NOW(), 'setup_sem_homedepot'
FROM _hd_columns seed
WHERE NOT EXISTS (
    SELECT 1 FROM public.monitoring_retail_columns target
    WHERE LOWER(BTRIM(target.product_line)) = seed.product_line
      AND LOWER(BTRIM(target.retailer)) = 'homedepot'
      AND target.column_name = seed.column_name
);

-- Categories are shared with Liverpool. Preserve existing labels/order.
UPDATE public.monitoring_null_category AS target
SET has_retailer = TRUE, is_active = TRUE, is_del = FALSE,
    updated_at = NOW(), updated_id = 'setup_sem_homedepot'
FROM _hd_sources source
WHERE target.category_name = source.category_name;

INSERT INTO public.monitoring_null_category (
    category_name, display_name, display_order, has_retailer,
    is_active, is_del, created_at, created_id
)
SELECT source.category_name, source.display_name, source.display_order,
       TRUE, TRUE, FALSE, NOW(), 'setup_sem_homedepot'
FROM _hd_sources source
WHERE NOT EXISTS (
    SELECT 1 FROM public.monitoring_null_category target
    WHERE target.category_name = source.category_name
);

UPDATE public.monitoring_null_group AS target
SET display_name = 'HomeDepot', table_name = source.table_name,
    date_column = 'crawl_datetime', display_order = 2,
    is_active = TRUE, is_del = FALSE,
    updated_at = NOW(), updated_id = 'setup_sem_homedepot'
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
       'crawl_datetime', 2, TRUE, FALSE, NOW(), 'setup_sem_homedepot'
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
       'id|crawl_datetime|item|sku|retailer_sku_name' ||
       CASE
           WHEN column_name IN ('star_rating', 'count_of_star_ratings', 'count_of_reviews')
               THEN '|star_rating|count_of_star_ratings|count_of_reviews'
           WHEN column_name IN ('item', 'sku', 'retailer_sku_name', 'product_url')
               THEN ''
           ELSE '|' || column_name
       END || '|product_url'
FROM _hd_columns
WHERE skip_missing_check = FALSE;

-- Enforce exactly the agreed eleven NULL fields in each HomeDepot group.
-- Optional price/rate fields are checked conditionally by cross-field rules.
UPDATE public.monitoring_null_column AS target
SET is_active = FALSE, updated_at = NOW(), updated_id = 'setup_sem_homedepot'
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
    updated_at = NOW(), updated_id = 'setup_sem_homedepot'
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
       seed.display_columns, 0, TRUE, FALSE, NOW(), 'setup_sem_homedepot'
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

COMMIT;

-- Expected: REF/LDY each have 18 shared columns and 11 required columns.
SELECT product_line, retailer, COUNT(*) AS configured_columns,
       COUNT(*) FILTER (WHERE skip_missing_check IS FALSE) AS required_columns
FROM public.monitoring_retail_columns
WHERE LOWER(BTRIM(product_line)) IN ('sem_ref', 'sem_ldy')
  AND LOWER(BTRIM(retailer)) = 'homedepot'
  AND is_active IS TRUE AND is_del IS FALSE
GROUP BY product_line, retailer
ORDER BY product_line;

-- Expected: two HomeDepot groups, each with 11 active NULL checks.
SELECT category.category_name, null_group.check_name,
       COUNT(*) AS null_check_columns
FROM public.monitoring_null_column col
JOIN public.monitoring_null_group null_group ON null_group.id = col.group_id
JOIN public.monitoring_null_category category ON category.id = null_group.category_id
WHERE null_group.check_name IN ('homedepot_sem_ref', 'homedepot_sem_ldy')
  AND category.is_active IS TRUE AND category.is_del IS FALSE
  AND null_group.is_active IS TRUE AND null_group.is_del IS FALSE
  AND col.is_active IS TRUE AND col.is_del IS FALSE
GROUP BY category.category_name, null_group.check_name
ORDER BY category.category_name;
