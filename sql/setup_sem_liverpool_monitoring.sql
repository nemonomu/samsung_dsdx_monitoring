-- SEM Mexico / Liverpool monitoring bootstrap.
-- PostgreSQL; idempotent and safe to run repeatedly.

BEGIN;

-- Backup tables deliberately preserve the source column order because the
-- application uses INSERT INTO backup SELECT source.*.
CREATE TABLE IF NOT EXISTS dx_sem.dx_sem_tv_retail_com_backup
    (LIKE dx_sem.dx_sem_tv_retail_com INCLUDING DEFAULTS INCLUDING STORAGE INCLUDING COMMENTS);
CREATE TABLE IF NOT EXISTS dx_sem.dx_sem_ref_retail_com_backup
    (LIKE dx_sem.dx_sem_ref_retail_com INCLUDING DEFAULTS INCLUDING STORAGE INCLUDING COMMENTS);
CREATE TABLE IF NOT EXISTS dx_sem.dx_sem_ldy_retail_com_backup
    (LIKE dx_sem.dx_sem_ldy_retail_com INCLUDING DEFAULTS INCLUDING STORAGE INCLUDING COMMENTS);

CREATE UNIQUE INDEX IF NOT EXISTS dx_sem_tv_retail_com_backup_id_uq
    ON dx_sem.dx_sem_tv_retail_com_backup (id);
CREATE UNIQUE INDEX IF NOT EXISTS dx_sem_ref_retail_com_backup_id_uq
    ON dx_sem.dx_sem_ref_retail_com_backup (id);
CREATE UNIQUE INDEX IF NOT EXISTS dx_sem_ldy_retail_com_backup_id_uq
    ON dx_sem.dx_sem_ldy_retail_com_backup (id);

-- Layer 1 activation. Actual status is based on the latest Liverpool batch's
-- MAIN count versus the previous seven valid days; expected_count is retained
-- as schedule metadata only.
WITH source(category, table_name) AS (
    VALUES
        ('TV',  'dx_sem.dx_sem_tv_retail_com'),
        ('REF', 'dx_sem.dx_sem_ref_retail_com'),
        ('LDY', 'dx_sem.dx_sem_ldy_retail_com')
), updated AS (
    UPDATE public.monitoring_collection_schedule target
    SET check_group = 'Retail',
        check_name = 'SEM ' || source.category || ' 수집',
        schedule_type = 'daily',
        schedule_value = NULL,
        us_start_hour = NULL,
        expected_count = 300,
        country = 'SEM',
        collection_duration_min = 600,
        view_table_name = source.table_name,
        sort_order = 4,
        description = 'SEM Mexico Liverpool ' || source.category || ' 당일(D) 수집',
        is_active = TRUE,
        is_del = 0,
        updated_at = NOW(),
        updated_id = 'setup_sem_liverpool'
    FROM source
    WHERE target.check_type = 'sem_retail'
      AND target.category = source.category
      AND LOWER(BTRIM(target.retailer)) = 'liverpool'
    RETURNING target.id
)
INSERT INTO public.monitoring_collection_schedule (
    check_group, check_type, check_name, category, schedule_type,
    schedule_value, us_start_hour, retailer, expected_count, country,
    collection_duration_min, view_table_name, sort_order, description,
    is_active, is_del, created_at, created_id, updated_at, updated_id
)
SELECT
    'Retail', 'sem_retail', 'SEM ' || source.category || ' 수집',
    source.category, 'daily', NULL, NULL, 'Liverpool', 300, 'SEM', 600,
    source.table_name, 4,
    'SEM Mexico Liverpool ' || source.category || ' 당일(D) 수집',
    TRUE, 0, NOW(), 'setup_sem_liverpool', NOW(), 'setup_sem_liverpool'
FROM source
WHERE NOT EXISTS (
    SELECT 1 FROM public.monitoring_collection_schedule target
    WHERE target.check_type = 'sem_retail'
      AND target.category = source.category
      AND LOWER(BTRIM(target.retailer)) = 'liverpool'
);

-- Email and shared retail column configuration. Optional source fields remain
-- available in email through its explicit skipped-column allowlist.
CREATE TEMP TABLE _sem_retail_column_seed (
    product_line text NOT NULL,
    column_name text NOT NULL,
    duplicate_key boolean NOT NULL DEFAULT FALSE,
    skip_missing_check boolean NOT NULL DEFAULT FALSE,
    is_editable boolean NOT NULL DEFAULT FALSE,
    PRIMARY KEY (product_line, column_name)
) ON COMMIT DROP;

INSERT INTO _sem_retail_column_seed
    (product_line, column_name, duplicate_key, skip_missing_check)
VALUES
    ('sem_tv', 'country', FALSE, FALSE),
    ('sem_tv', 'account_name', FALSE, FALSE),
    ('sem_tv', 'item', TRUE, FALSE),
    ('sem_tv', 'sku', FALSE, TRUE),
    ('sem_tv', 'retailer_sku_name', FALSE, FALSE),
    ('sem_tv', 'product_url', FALSE, FALSE),
    ('sem_tv', 'screen_size', FALSE, FALSE),
    ('sem_tv', 'final_sku_price', FALSE, FALSE),
    ('sem_tv', 'original_sku_price', FALSE, TRUE),
    ('sem_tv', 'savings', FALSE, TRUE),
    ('sem_tv', 'star_rating', FALSE, TRUE),
    ('sem_tv', 'count_of_star_ratings', FALSE, TRUE),
    ('sem_tv', 'count_of_reviews', FALSE, TRUE),
    ('sem_tv', 'main_rank', FALSE, TRUE),
    ('sem_tv', 'bsr_rank', FALSE, TRUE),
    ('sem_ref', 'country', FALSE, FALSE),
    ('sem_ref', 'account_name', FALSE, FALSE),
    ('sem_ref', 'item', TRUE, FALSE),
    ('sem_ref', 'sku', FALSE, TRUE),
    ('sem_ref', 'retailer_sku_name', FALSE, FALSE),
    ('sem_ref', 'product_url', FALSE, FALSE),
    ('sem_ref', 'ref_capacity', FALSE, FALSE),
    ('sem_ref', 'ref_refrigerator_type', FALSE, TRUE),
    ('sem_ref', 'final_sku_price', FALSE, FALSE),
    ('sem_ref', 'original_sku_price', FALSE, TRUE),
    ('sem_ref', 'savings', FALSE, TRUE),
    ('sem_ref', 'star_rating', FALSE, TRUE),
    ('sem_ref', 'count_of_star_ratings', FALSE, TRUE),
    ('sem_ref', 'count_of_reviews', FALSE, TRUE),
    ('sem_ref', 'main_rank', FALSE, TRUE),
    ('sem_ref', 'bsr_rank', FALSE, TRUE),
    ('sem_ldy', 'country', FALSE, FALSE),
    ('sem_ldy', 'account_name', FALSE, FALSE),
    ('sem_ldy', 'item', TRUE, FALSE),
    ('sem_ldy', 'sku', FALSE, TRUE),
    ('sem_ldy', 'retailer_sku_name', FALSE, FALSE),
    ('sem_ldy', 'product_url', FALSE, FALSE),
    ('sem_ldy', 'ldy_capacity', FALSE, FALSE),
    ('sem_ldy', 'ldy_loading_type', FALSE, TRUE),
    ('sem_ldy', 'final_sku_price', FALSE, FALSE),
    ('sem_ldy', 'original_sku_price', FALSE, TRUE),
    ('sem_ldy', 'savings', FALSE, TRUE),
    ('sem_ldy', 'star_rating', FALSE, TRUE),
    ('sem_ldy', 'count_of_star_ratings', FALSE, TRUE),
    ('sem_ldy', 'count_of_reviews', FALSE, TRUE),
    ('sem_ldy', 'main_rank', FALSE, TRUE),
    ('sem_ldy', 'bsr_rank', FALSE, TRUE);

UPDATE public.monitoring_retail_columns target
SET duplicate_key = seed.duplicate_key,
    skip_missing_check = seed.skip_missing_check,
    is_editable = seed.is_editable,
    is_active = TRUE,
    is_del = FALSE,
    updated_id = 'setup_sem_liverpool',
    updated_at = NOW()
FROM _sem_retail_column_seed seed
WHERE LOWER(BTRIM(target.product_line)) = seed.product_line
  AND LOWER(BTRIM(target.retailer)) = 'liverpool'
  AND target.column_name = seed.column_name;

INSERT INTO public.monitoring_retail_columns (
    product_line, column_name, retailer, duplicate_key,
    skip_missing_check, is_active, is_del, is_editable,
    created_id, created_at, updated_id, updated_at
)
SELECT seed.product_line, seed.column_name, 'Liverpool', seed.duplicate_key,
       seed.skip_missing_check, TRUE, FALSE, seed.is_editable,
       'setup_sem_liverpool', NOW(), 'setup_sem_liverpool', NOW()
FROM _sem_retail_column_seed seed
WHERE NOT EXISTS (
    SELECT 1 FROM public.monitoring_retail_columns target
    WHERE LOWER(BTRIM(target.product_line)) = seed.product_line
      AND LOWER(BTRIM(target.retailer)) = 'liverpool'
      AND target.column_name = seed.column_name
);

-- Layer 2 sidebar/detail metadata. Hard-coded application allowlists still
-- enforce the actual SEM fields and latest-batch scope.
CREATE TEMP TABLE _sem_null_category_seed (
    category_name text PRIMARY KEY, display_name text, display_order integer
) ON COMMIT DROP;
INSERT INTO _sem_null_category_seed VALUES
    ('sem_tv_retail', 'SEM TV', 7),
    ('sem_ref_retail', 'SEM REF', 8),
    ('sem_ldy_retail', 'SEM LDY', 9);

UPDATE public.monitoring_null_category target
SET display_name = seed.display_name, display_order = seed.display_order,
    has_retailer = TRUE, is_active = TRUE, is_del = FALSE,
    updated_at = NOW(), updated_id = 'setup_sem_liverpool'
FROM _sem_null_category_seed seed
WHERE target.category_name = seed.category_name;

INSERT INTO public.monitoring_null_category (
    category_name, display_name, display_order, has_retailer,
    is_active, is_del, created_at, created_id
)
SELECT category_name, display_name, display_order, TRUE, TRUE, FALSE,
       NOW(), 'setup_sem_liverpool'
FROM _sem_null_category_seed seed
WHERE NOT EXISTS (
    SELECT 1 FROM public.monitoring_null_category target
    WHERE target.category_name = seed.category_name
);

CREATE TEMP TABLE _sem_null_group_seed (
    category_name text PRIMARY KEY, check_name text, display_name text,
    table_name text, date_column text
) ON COMMIT DROP;
INSERT INTO _sem_null_group_seed VALUES
    ('sem_tv_retail', 'liverpool_sem_tv', 'Liverpool',
     'dx_sem.dx_sem_tv_retail_com', 'crawl_datetime'),
    ('sem_ref_retail', 'liverpool_sem_ref', 'Liverpool',
     'dx_sem.dx_sem_ref_retail_com', 'crawl_datetime'),
    ('sem_ldy_retail', 'liverpool_sem_ldy', 'Liverpool',
     'dx_sem.dx_sem_ldy_retail_com', 'crawl_datetime');

UPDATE public.monitoring_null_group target
SET display_name = seed.display_name, table_name = seed.table_name,
    date_column = seed.date_column, display_order = 1,
    is_active = TRUE, is_del = FALSE,
    updated_at = NOW(), updated_id = 'setup_sem_liverpool'
FROM _sem_null_group_seed seed
JOIN public.monitoring_null_category category
  ON category.category_name = seed.category_name
WHERE target.category_id = category.id
  AND target.check_name = seed.check_name;

INSERT INTO public.monitoring_null_group (
    category_id, check_name, display_name, table_name, date_column,
    display_order, is_active, is_del, created_at, created_id
)
SELECT category.id, seed.check_name, seed.display_name, seed.table_name,
       seed.date_column, 1, TRUE, FALSE, NOW(), 'setup_sem_liverpool'
FROM _sem_null_group_seed seed
JOIN public.monitoring_null_category category
  ON category.category_name = seed.category_name
WHERE NOT EXISTS (
    SELECT 1 FROM public.monitoring_null_group target
    WHERE target.category_id = category.id
      AND target.check_name = seed.check_name
);

CREATE TEMP TABLE _sem_null_column_seed (
    category_name text, check_column text,
    PRIMARY KEY (category_name, check_column)
) ON COMMIT DROP;
INSERT INTO _sem_null_column_seed VALUES
    ('sem_tv_retail', 'country'), ('sem_tv_retail', 'account_name'),
    ('sem_tv_retail', 'item'), ('sem_tv_retail', 'retailer_sku_name'),
    ('sem_tv_retail', 'product_url'), ('sem_tv_retail', 'final_sku_price'),
    ('sem_tv_retail', 'screen_size'),
    ('sem_ref_retail', 'country'), ('sem_ref_retail', 'account_name'),
    ('sem_ref_retail', 'item'), ('sem_ref_retail', 'retailer_sku_name'),
    ('sem_ref_retail', 'product_url'), ('sem_ref_retail', 'final_sku_price'),
    ('sem_ref_retail', 'ref_capacity'),
    ('sem_ldy_retail', 'country'), ('sem_ldy_retail', 'account_name'),
    ('sem_ldy_retail', 'item'), ('sem_ldy_retail', 'retailer_sku_name'),
    ('sem_ldy_retail', 'product_url'), ('sem_ldy_retail', 'final_sku_price'),
    ('sem_ldy_retail', 'ldy_capacity');

UPDATE public.monitoring_null_column target
SET check_type = 'both', query_days = 0, is_active = TRUE, is_del = FALSE,
    updated_at = NOW(), updated_id = 'setup_sem_liverpool'
FROM _sem_null_column_seed seed
JOIN _sem_null_group_seed group_seed
  ON group_seed.category_name = seed.category_name
JOIN public.monitoring_null_category category
  ON category.category_name = seed.category_name
JOIN public.monitoring_null_group null_group
  ON null_group.category_id = category.id
 AND null_group.check_name = group_seed.check_name
WHERE target.group_id = null_group.id
  AND target.check_column = seed.check_column;

INSERT INTO public.monitoring_null_column (
    group_id, check_column, check_type, display_columns, query_columns,
    query_days, is_active, is_del, created_at, created_id
)
SELECT null_group.id, seed.check_column, 'both',
       'id|item|sku|retailer_sku_name|crawl_datetime|product_url',
       'id|item|sku|retailer_sku_name|crawl_datetime|product_url',
       0, TRUE, FALSE, NOW(), 'setup_sem_liverpool'
FROM _sem_null_column_seed seed
JOIN _sem_null_group_seed group_seed
  ON group_seed.category_name = seed.category_name
JOIN public.monitoring_null_category category
  ON category.category_name = seed.category_name
JOIN public.monitoring_null_group null_group
  ON null_group.category_id = category.id
 AND null_group.check_name = group_seed.check_name
WHERE NOT EXISTS (
    SELECT 1 FROM public.monitoring_null_column target
    WHERE target.group_id = null_group.id
      AND target.check_column = seed.check_column
);

COMMIT;

SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_schema = 'dx_sem' AND RIGHT(table_name, 7) = '_backup'
ORDER BY table_name;

SELECT check_type, category, retailer, country, view_table_name, is_active
FROM public.monitoring_collection_schedule
WHERE check_type = 'sem_retail'
ORDER BY category;
