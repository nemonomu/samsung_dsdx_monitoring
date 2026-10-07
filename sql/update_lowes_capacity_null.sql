-- Enable Lowes REF/LDY capacity NULL checks. Safe to run repeatedly.
BEGIN;

CREATE TEMP TABLE _lowes_capacity_null ON COMMIT DROP AS
SELECT g.id AS group_id, seed.check_column,
       'crawl_strdatetime|item|account_name|country|sku|retailer_sku_name|'
           || seed.check_column || '|product_url' AS display_columns,
       'id|crawl_strdatetime|batch_id|account_name|country|page_type|item|sku|retailer_sku_name|'
           || seed.check_column || '|product_url' AS query_columns
FROM public.monitoring_null_group g
JOIN public.monitoring_null_category c ON c.id = g.category_id
JOIN (VALUES
    ('sea_ref_retail', 'lowes_ref', 'ref_retail_com', 'ref_capacity'),
    ('sea_ldy_retail', 'lowes_ldy', 'ldy_retail_com', 'ldy_capacity')
) AS seed(category_name, check_name, table_name, check_column)
  ON c.category_name = seed.category_name
 AND g.check_name = seed.check_name
 AND REGEXP_REPLACE(LOWER(g.table_name), '^.*\.', '') = seed.table_name;

UPDATE public.monitoring_null_column target
SET check_type = 'both', display_columns = seed.display_columns,
    query_columns = seed.query_columns, query_days = 0,
    is_active = TRUE, is_del = FALSE
FROM _lowes_capacity_null seed
WHERE target.group_id = seed.group_id
  AND target.check_column = seed.check_column;

INSERT INTO public.monitoring_null_column
    (group_id, check_column, check_type, display_columns,
     query_columns, query_days, is_active, is_del)
SELECT group_id, check_column, 'both', display_columns,
       query_columns, 0, TRUE, FALSE
FROM _lowes_capacity_null seed
WHERE NOT EXISTS (
    SELECT 1 FROM public.monitoring_null_column target
    WHERE target.group_id = seed.group_id
      AND target.check_column = seed.check_column
);

COMMIT;
