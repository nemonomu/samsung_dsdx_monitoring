-- SEDA Layer 2 NULL configuration only. Run in the monitoring DB with DBeaver.
-- TV: Casas Bahia 6 / Magalu 7; REF: 5 / 5; LDY: 6 / 5 (34 checks).
-- The application enforces calendar D-1, the latest MAIN batch per retailer,
-- and MAIN/BSR scope. Zero is a value; only NULL/empty/whitespace is missing.
-- Re-running repairs matching configuration without creating duplicates.
BEGIN;

-- The NULL evidence table predates SEDA. Extend its country constraint so a
-- SEDA manual confirmation and its automatic-review evidence commit together.
DO $seda_evidence$
DECLARE
    country_constraint text;
BEGIN
    IF to_regclass('public.monitoring_null_review_evidence') IS NULL THEN
        RAISE EXCEPTION
            'public.monitoring_null_review_evidence is missing; run sql/create_null_review_evidence.sql first';
    END IF;

    FOR country_constraint IN
        SELECT constraint_row.conname
        FROM pg_constraint AS constraint_row
        JOIN pg_attribute AS country_column
          ON country_column.attrelid = constraint_row.conrelid
         AND country_column.attname = 'country'
         AND country_column.attnum = ANY(constraint_row.conkey)
        WHERE constraint_row.conrelid =
              'public.monitoring_null_review_evidence'::regclass
          AND constraint_row.contype = 'c'
    LOOP
        EXECUTE format(
            'ALTER TABLE public.monitoring_null_review_evidence DROP CONSTRAINT %I',
            country_constraint
        );
    END LOOP;

    ALTER TABLE public.monitoring_null_review_evidence
        ADD CONSTRAINT monitoring_null_review_evidence_country_check
        CHECK (country IN ('SEA', 'SEDA', 'SEM', 'SIEL', 'TSE', 'SEG'));
END
$seda_evidence$;

CREATE TEMP TABLE _seda_null_fields (
    product_line text, retailer text, column_name text,
    PRIMARY KEY (product_line, retailer, column_name)
) ON COMMIT DROP;
INSERT INTO _seda_null_fields VALUES
    ('seda_tv', 'Casas Bahia', 'count_of_reviews'),
    ('seda_tv', 'Casas Bahia', 'count_of_star_ratings'),
    ('seda_tv', 'Casas Bahia', 'final_sku_price'),
    ('seda_tv', 'Casas Bahia', 'retailer_sku_name'),
    ('seda_tv', 'Casas Bahia', 'star_rating'),
    ('seda_tv', 'Casas Bahia', 'screen_size'),
    ('seda_tv', 'Magalu', 'count_of_reviews'),
    ('seda_tv', 'Magalu', 'count_of_star_ratings'),
    ('seda_tv', 'Magalu', 'final_sku_price'),
    ('seda_tv', 'Magalu', 'retailer_sku_name'),
    ('seda_tv', 'Magalu', 'star_rating'),
    ('seda_tv', 'Magalu', 'screen_size'),
    ('seda_tv', 'Magalu', 'sku'),
    ('seda_ref', 'Casas Bahia', 'count_of_reviews'),
    ('seda_ref', 'Casas Bahia', 'count_of_star_ratings'),
    ('seda_ref', 'Casas Bahia', 'final_sku_price'),
    ('seda_ref', 'Casas Bahia', 'retailer_sku_name'),
    ('seda_ref', 'Casas Bahia', 'star_rating'),
    ('seda_ref', 'Magalu', 'count_of_reviews'),
    ('seda_ref', 'Magalu', 'count_of_star_ratings'),
    ('seda_ref', 'Magalu', 'final_sku_price'),
    ('seda_ref', 'Magalu', 'retailer_sku_name'),
    ('seda_ref', 'Magalu', 'star_rating'),
    ('seda_ldy', 'Casas Bahia', 'count_of_reviews'),
    ('seda_ldy', 'Casas Bahia', 'count_of_star_ratings'),
    ('seda_ldy', 'Casas Bahia', 'final_sku_price'),
    ('seda_ldy', 'Casas Bahia', 'retailer_sku_name'),
    ('seda_ldy', 'Casas Bahia', 'star_rating'),
    ('seda_ldy', 'Casas Bahia', 'ldy_color'),
    ('seda_ldy', 'Magalu', 'count_of_reviews'),
    ('seda_ldy', 'Magalu', 'count_of_star_ratings'),
    ('seda_ldy', 'Magalu', 'final_sku_price'),
    ('seda_ldy', 'Magalu', 'retailer_sku_name'),
    ('seda_ldy', 'Magalu', 'star_rating');

CREATE TEMP TABLE _seda_null_sources (
    product_line text PRIMARY KEY, display_name text,
    table_name text, display_order integer
) ON COMMIT DROP;
INSERT INTO _seda_null_sources VALUES
    ('seda_tv', 'SEDA TV', 'dx_seda.dx_seda_tv_retail_com', 10),
    ('seda_ref', 'SEDA REF', 'dx_seda.dx_seda_ref_retail_com', 11),
    ('seda_ldy', 'SEDA LDY', 'dx_seda.dx_seda_ldy_retail_com', 12);

UPDATE public.monitoring_retail_columns AS target
SET skip_missing_check = FALSE, is_editable = TRUE,
    is_active = TRUE, is_del = FALSE,
    updated_at = NOW(), updated_id = 'setup_seda_null'
FROM _seda_null_fields seed
WHERE LOWER(BTRIM(target.product_line)) = seed.product_line
  AND LOWER(REPLACE(BTRIM(target.retailer), ' ', '')) =
      LOWER(REPLACE(seed.retailer, ' ', ''))
  AND target.column_name = seed.column_name;

INSERT INTO public.monitoring_retail_columns (
    product_line, retailer, column_name, duplicate_key, skip_missing_check,
    is_editable, is_active, is_del, created_at, created_id
)
SELECT seed.product_line, seed.retailer, seed.column_name, FALSE, FALSE,
       TRUE, TRUE, FALSE, NOW(), 'setup_seda_null'
FROM _seda_null_fields seed
WHERE NOT EXISTS (
    SELECT 1 FROM public.monitoring_retail_columns target
    WHERE LOWER(BTRIM(target.product_line)) = seed.product_line
      AND LOWER(REPLACE(BTRIM(target.retailer), ' ', '')) =
          LOWER(REPLACE(seed.retailer, ' ', ''))
      AND target.column_name = seed.column_name
);

UPDATE public.monitoring_null_category AS target
SET has_retailer = TRUE, is_active = TRUE, is_del = FALSE,
    updated_at = NOW(), updated_id = 'setup_seda_null'
FROM _seda_null_sources source
WHERE target.category_name = source.product_line || '_retail';

INSERT INTO public.monitoring_null_category (
    category_name, display_name, display_order, has_retailer,
    is_active, is_del, created_at, created_id
)
SELECT source.product_line || '_retail', source.display_name, source.display_order,
       TRUE, TRUE, FALSE, NOW(), 'setup_seda_null'
FROM _seda_null_sources source
WHERE NOT EXISTS (
    SELECT 1 FROM public.monitoring_null_category target
    WHERE target.category_name = source.product_line || '_retail'
);

CREATE TEMP TABLE _seda_null_groups ON COMMIT DROP AS
SELECT DISTINCT category.id AS category_id, seed.product_line, seed.retailer,
       seed.product_line || '_' || LOWER(REPLACE(seed.retailer, ' ', '')) AS check_name,
       source.table_name
FROM _seda_null_fields seed
JOIN _seda_null_sources source ON source.product_line = seed.product_line
JOIN public.monitoring_null_category category
  ON category.category_name = seed.product_line || '_retail';

UPDATE public.monitoring_null_group AS target
SET display_name = seed.retailer, table_name = seed.table_name,
    date_column = 'crawl_strdatetime',
    is_active = TRUE, is_del = FALSE,
    updated_at = NOW(), updated_id = 'setup_seda_null'
FROM _seda_null_groups seed
WHERE target.category_id = seed.category_id AND target.check_name = seed.check_name;

INSERT INTO public.monitoring_null_group (
    category_id, check_name, display_name, table_name, date_column,
    display_order, is_active, is_del, created_at, created_id
)
SELECT seed.category_id, seed.check_name, seed.retailer, seed.table_name,
       'crawl_strdatetime', CASE WHEN seed.retailer = 'Magalu' THEN 1 ELSE 2 END,
       TRUE, FALSE, NOW(), 'setup_seda_null'
FROM _seda_null_groups seed
WHERE NOT EXISTS (
    SELECT 1 FROM public.monitoring_null_group target
    WHERE target.category_id = seed.category_id AND target.check_name = seed.check_name
);

CREATE TEMP TABLE _seda_null_columns ON COMMIT DROP AS
SELECT null_group.id AS group_id, seed.column_name AS check_column,
       'id|crawl_strdatetime|item|sku|retailer_sku_name' ||
       CASE
           WHEN seed.column_name IN ('star_rating', 'count_of_star_ratings', 'count_of_reviews')
               THEN '|star_rating|count_of_star_ratings|count_of_reviews'
           WHEN seed.column_name IN ('sku', 'retailer_sku_name') THEN ''
           ELSE '|' || seed.column_name
       END || '|product_url' AS display_columns
FROM _seda_null_fields seed
JOIN _seda_null_groups group_seed
  ON group_seed.product_line = seed.product_line AND group_seed.retailer = seed.retailer
JOIN public.monitoring_null_group null_group
  ON null_group.category_id = group_seed.category_id AND null_group.check_name = group_seed.check_name;

-- Only these six SEDA groups are reconciled to the approved column list.
UPDATE public.monitoring_null_column AS target
SET is_active = FALSE, updated_at = NOW(), updated_id = 'setup_seda_null'
WHERE target.group_id IN (SELECT group_id FROM _seda_null_columns)
  AND NOT EXISTS (
      SELECT 1 FROM _seda_null_columns seed
      WHERE seed.group_id = target.group_id AND seed.check_column = target.check_column
  );

UPDATE public.monitoring_null_column AS target
SET check_type = 'both', display_columns = seed.display_columns,
    query_columns = seed.display_columns, query_days = 0,
    is_active = TRUE, is_del = FALSE,
    updated_at = NOW(), updated_id = 'setup_seda_null'
FROM _seda_null_columns seed
WHERE target.group_id = seed.group_id AND target.check_column = seed.check_column;

INSERT INTO public.monitoring_null_column (
    group_id, check_column, check_type, display_columns, query_columns,
    query_days, is_active, is_del, created_at, created_id
)
SELECT seed.group_id, seed.check_column, 'both', seed.display_columns,
       seed.display_columns, 0, TRUE, FALSE, NOW(), 'setup_seda_null'
FROM _seda_null_columns seed
WHERE NOT EXISTS (
    SELECT 1 FROM public.monitoring_null_column target
    WHERE target.group_id = seed.group_id AND target.check_column = seed.check_column
);

COMMIT;

-- Expected six groups / 34 active checks: LDY 6+5, REF 5+5, TV 6+7.
SELECT category.category_name, null_group.display_name AS retailer, COUNT(*) AS null_checks
FROM public.monitoring_null_column col
JOIN public.monitoring_null_group null_group ON null_group.id = col.group_id
JOIN public.monitoring_null_category category ON category.id = null_group.category_id
WHERE null_group.check_name IN (
    'seda_tv_magalu', 'seda_tv_casasbahia',
    'seda_ref_magalu', 'seda_ref_casasbahia',
    'seda_ldy_magalu', 'seda_ldy_casasbahia'
)
  AND col.is_active IS TRUE AND col.is_del IS FALSE
  AND null_group.is_active IS TRUE AND null_group.is_del IS FALSE
  AND category.is_active IS TRUE AND category.is_del IS FALSE
GROUP BY category.category_name, null_group.display_name
ORDER BY category.category_name, null_group.display_name;
