-- SEM HomeDepot LDY_DRYER: Layer 1 schedule and Layer 2 NULL configuration.
-- Run in the monitoring PostgreSQL database. Idempotent; source rows are untouched.
-- The collection date is the original text date of crawl_datetime (D, from 2026-10-18).
BEGIN;

UPDATE public.monitoring_collection_schedule
SET check_group = 'Retail', check_name = 'SEM LDY_DRYER collection',
    schedule_type = 'daily', schedule_value = NULL, us_start_hour = NULL,
    expected_count = 0, country = 'SEM', collection_duration_min = 270,
    view_table_name = 'dx_sem.dx_sem_ldy_dryer_retail_com', sort_order = 4,
    description = 'SEM HomeDepot LDY_DRYER, D, KST 09:00-13:30; volume uses latest MAIN batch',
    is_active = TRUE, is_del = 0, updated_at = NOW(),
    updated_id = 'setup_sem_homedepot_dryer'
WHERE check_type = 'sem_retail' AND category = 'LDY_DRYER'
  AND LOWER(BTRIM(retailer)) = 'homedepot';

INSERT INTO public.monitoring_collection_schedule (
    check_group, check_type, check_name, category, schedule_type,
    schedule_value, us_start_hour, retailer, expected_count, country,
    collection_duration_min, view_table_name, sort_order, description,
    is_active, is_del, created_at, created_id, updated_at, updated_id
)
SELECT 'Retail', 'sem_retail', 'SEM LDY_DRYER collection', 'LDY_DRYER',
       'daily', NULL, NULL, 'HomeDepot', 0, 'SEM', 270,
       'dx_sem.dx_sem_ldy_dryer_retail_com', 4,
       'SEM HomeDepot LDY_DRYER, D, KST 09:00-13:30; volume uses latest MAIN batch',
       TRUE, 0, NOW(), 'setup_sem_homedepot_dryer', NOW(), 'setup_sem_homedepot_dryer'
WHERE NOT EXISTS (
    SELECT 1 FROM public.monitoring_collection_schedule
    WHERE check_type = 'sem_retail' AND category = 'LDY_DRYER'
      AND LOWER(BTRIM(retailer)) = 'homedepot'
);

CREATE TEMP TABLE _sem_dryer_columns (
    column_name text PRIMARY KEY, required boolean NOT NULL,
    editable boolean NOT NULL
) ON COMMIT DROP;
INSERT INTO _sem_dryer_columns VALUES
    ('country', TRUE, TRUE), ('account_name', TRUE, TRUE),
    ('item', TRUE, TRUE), ('sku', TRUE, TRUE),
    ('retailer_sku_name', TRUE, TRUE), ('product_url', TRUE, TRUE),
    ('count_of_reviews', TRUE, TRUE), ('star_rating', TRUE, TRUE),
    ('count_of_star_ratings', TRUE, TRUE), ('final_sku_price', TRUE, TRUE),
    ('capacity', TRUE, TRUE), ('original_sku_price', FALSE, TRUE),
    ('savings', FALSE, TRUE), ('loading_type', FALSE, TRUE),
    ('main_rank', FALSE, FALSE), ('bsr_rank', FALSE, FALSE),
    ('crawl_datetime', FALSE, FALSE), ('calendar_week', FALSE, TRUE);

UPDATE public.monitoring_retail_columns target
SET duplicate_key = (seed.column_name = 'item'),
    skip_missing_check = NOT seed.required, is_editable = seed.editable,
    is_active = TRUE, is_del = FALSE,
    updated_at = NOW(), updated_id = 'setup_sem_homedepot_dryer'
FROM _sem_dryer_columns seed
WHERE LOWER(BTRIM(target.product_line)) = 'sem_ldy_dryer'
  AND LOWER(BTRIM(target.retailer)) = 'homedepot'
  AND target.column_name = seed.column_name;

INSERT INTO public.monitoring_retail_columns (
    product_line, column_name, retailer, duplicate_key, skip_missing_check,
    is_editable, is_active, is_del, created_at, created_id, updated_at, updated_id
)
SELECT 'sem_ldy_dryer', seed.column_name, 'HomeDepot',
       seed.column_name = 'item', NOT seed.required, seed.editable,
       TRUE, FALSE, NOW(), 'setup_sem_homedepot_dryer',
       NOW(), 'setup_sem_homedepot_dryer'
FROM _sem_dryer_columns seed
WHERE NOT EXISTS (
    SELECT 1 FROM public.monitoring_retail_columns target
    WHERE LOWER(BTRIM(target.product_line)) = 'sem_ldy_dryer'
      AND LOWER(BTRIM(target.retailer)) = 'homedepot'
      AND target.column_name = seed.column_name
);

UPDATE public.monitoring_retail_columns target
SET is_active = FALSE, updated_at = NOW(),
    updated_id = 'setup_sem_homedepot_dryer'
WHERE LOWER(BTRIM(target.product_line)) = 'sem_ldy_dryer'
  AND LOWER(BTRIM(target.retailer)) = 'homedepot'
  AND NOT EXISTS (
      SELECT 1 FROM _sem_dryer_columns seed
      WHERE seed.column_name = target.column_name
  );

UPDATE public.monitoring_null_category
SET display_name = 'SEM LDY_DRYER', display_order = 10,
    has_retailer = TRUE, is_active = TRUE, is_del = FALSE,
    updated_at = NOW(), updated_id = 'setup_sem_homedepot_dryer'
WHERE category_name = 'sem_ldy_dryer_retail';

INSERT INTO public.monitoring_null_category (
    category_name, display_name, display_order, has_retailer,
    is_active, is_del, created_at, created_id
)
SELECT 'sem_ldy_dryer_retail', 'SEM LDY_DRYER', 10,
       TRUE, TRUE, FALSE, NOW(), 'setup_sem_homedepot_dryer'
WHERE NOT EXISTS (
    SELECT 1 FROM public.monitoring_null_category
    WHERE category_name = 'sem_ldy_dryer_retail'
);

UPDATE public.monitoring_null_group target
SET display_name = 'HomeDepot',
    table_name = 'dx_sem.dx_sem_ldy_dryer_retail_com',
    date_column = 'crawl_datetime', display_order = 1,
    is_active = TRUE, is_del = FALSE,
    updated_at = NOW(), updated_id = 'setup_sem_homedepot_dryer'
FROM public.monitoring_null_category category
WHERE category.category_name = 'sem_ldy_dryer_retail'
  AND target.category_id = category.id
  AND target.check_name = 'homedepot_sem_ldy_dryer';

INSERT INTO public.monitoring_null_group (
    category_id, check_name, display_name, table_name, date_column,
    display_order, is_active, is_del, created_at, created_id
)
SELECT category.id, 'homedepot_sem_ldy_dryer', 'HomeDepot',
       'dx_sem.dx_sem_ldy_dryer_retail_com', 'crawl_datetime',
       1, TRUE, FALSE, NOW(), 'setup_sem_homedepot_dryer'
FROM public.monitoring_null_category category
WHERE category.category_name = 'sem_ldy_dryer_retail'
  AND NOT EXISTS (
      SELECT 1 FROM public.monitoring_null_group target
      WHERE target.category_id = category.id
        AND target.check_name = 'homedepot_sem_ldy_dryer'
  );

-- Only the eleven required fields are active. loading_type remains statistical.
UPDATE public.monitoring_null_column target
SET is_active = FALSE, updated_at = NOW(),
    updated_id = 'setup_sem_homedepot_dryer'
FROM public.monitoring_null_group null_group
WHERE target.group_id = null_group.id
  AND null_group.check_name = 'homedepot_sem_ldy_dryer'
  AND target.check_column NOT IN (
      SELECT column_name FROM _sem_dryer_columns WHERE required
  );

CREATE TEMP TABLE _sem_dryer_null ON COMMIT DROP AS
SELECT seed.column_name AS check_column,
       'id|crawl_datetime|item|sku|retailer_sku_name' ||
       CASE WHEN seed.column_name IN
               ('star_rating', 'count_of_star_ratings', 'count_of_reviews')
            THEN '|star_rating|count_of_star_ratings|count_of_reviews'
            WHEN seed.column_name IN
               ('item', 'sku', 'retailer_sku_name', 'product_url')
            THEN '' ELSE '|' || seed.column_name END || '|product_url'
       AS display_columns
FROM _sem_dryer_columns seed WHERE seed.required;

UPDATE public.monitoring_null_column target
SET check_type = 'both', display_columns = seed.display_columns,
    query_columns = seed.display_columns, query_days = 0,
    is_active = TRUE, is_del = FALSE,
    updated_at = NOW(), updated_id = 'setup_sem_homedepot_dryer'
FROM _sem_dryer_null seed
JOIN public.monitoring_null_group null_group
  ON null_group.check_name = 'homedepot_sem_ldy_dryer'
JOIN public.monitoring_null_category category
  ON category.id = null_group.category_id
 AND category.category_name = 'sem_ldy_dryer_retail'
WHERE target.group_id = null_group.id
  AND target.check_column = seed.check_column;

INSERT INTO public.monitoring_null_column (
    group_id, check_column, check_type, display_columns, query_columns,
    query_days, is_active, is_del, created_at, created_id
)
SELECT null_group.id, seed.check_column, 'both', seed.display_columns,
       seed.display_columns, 0, TRUE, FALSE, NOW(), 'setup_sem_homedepot_dryer'
FROM _sem_dryer_null seed
JOIN public.monitoring_null_group null_group
  ON null_group.check_name = 'homedepot_sem_ldy_dryer'
JOIN public.monitoring_null_category category
  ON category.id = null_group.category_id
 AND category.category_name = 'sem_ldy_dryer_retail'
WHERE NOT EXISTS (
    SELECT 1 FROM public.monitoring_null_column target
    WHERE target.group_id = null_group.id
      AND target.check_column = seed.check_column
);

DO $$
BEGIN
    IF (SELECT COUNT(*) FROM _sem_dryer_null) <> 11 THEN
        RAISE EXCEPTION 'Expected eleven SEM dryer NULL fields';
    END IF;
    IF (
        SELECT COUNT(*)
        FROM public.monitoring_null_column col
        JOIN public.monitoring_null_group null_group ON null_group.id = col.group_id
        JOIN public.monitoring_null_category category ON category.id = null_group.category_id
        WHERE category.category_name = 'sem_ldy_dryer_retail'
          AND null_group.check_name = 'homedepot_sem_ldy_dryer'
          AND col.is_active IS TRUE AND col.is_del IS FALSE
    ) <> 11 THEN
        RAISE EXCEPTION 'Expected exactly eleven active SEM dryer NULL checks';
    END IF;
END $$;
COMMIT;

SELECT product_line, retailer, COUNT(*) AS configured_columns,
       COUNT(*) FILTER (WHERE skip_missing_check IS FALSE) AS required_columns
FROM public.monitoring_retail_columns
WHERE LOWER(BTRIM(product_line)) = 'sem_ldy_dryer'
  AND LOWER(BTRIM(retailer)) = 'homedepot'
  AND is_active IS TRUE AND is_del IS FALSE
GROUP BY product_line, retailer;

SELECT category.category_name, null_group.check_name,
       COUNT(*) AS active_null_columns
FROM public.monitoring_null_column col
JOIN public.monitoring_null_group null_group ON null_group.id = col.group_id
JOIN public.monitoring_null_category category ON category.id = null_group.category_id
WHERE category.category_name = 'sem_ldy_dryer_retail'
  AND null_group.check_name = 'homedepot_sem_ldy_dryer'
  AND col.is_active IS TRUE AND col.is_del IS FALSE
GROUP BY category.category_name, null_group.check_name;
