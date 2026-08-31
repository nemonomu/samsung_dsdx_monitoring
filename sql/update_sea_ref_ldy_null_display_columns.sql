-- SEA REF/LDY Layer2 NULL detail visible columns
-- PostgreSQL only. Run in DBeaver against the monitoring database.
-- Safe to run repeatedly. Query columns and validation rules are unchanged.

BEGIN;

UPDATE public.monitoring_null_column null_column
SET display_columns = CASE
    WHEN null_column.check_column IN ('item', 'sku', 'retailer_sku_name')
        THEN 'item|sku|retailer_sku_name'
    ELSE 'item|sku|retailer_sku_name|' || null_column.check_column
END
FROM public.monitoring_null_group null_group
JOIN public.monitoring_null_category category
  ON category.id = null_group.category_id
WHERE null_column.group_id = null_group.id
  AND category.category_name IN ('sea_ref_retail', 'sea_ldy_retail')
  AND null_column.is_active = TRUE
  AND null_column.is_del = FALSE
  AND null_group.is_active = TRUE
  AND null_group.is_del = FALSE
  AND category.is_active = TRUE
  AND category.is_del = FALSE;

COMMIT;

SELECT
    category.category_name,
    null_group.display_name AS retailer,
    null_column.check_column,
    null_column.display_columns
FROM public.monitoring_null_column null_column
JOIN public.monitoring_null_group null_group
  ON null_group.id = null_column.group_id
JOIN public.monitoring_null_category category
  ON category.id = null_group.category_id
WHERE category.category_name IN ('sea_ref_retail', 'sea_ldy_retail')
  AND null_column.is_active = TRUE
  AND null_column.is_del = FALSE
ORDER BY category.category_name, retailer, null_column.check_column;
