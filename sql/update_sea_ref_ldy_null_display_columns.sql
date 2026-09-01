-- SEA REF/LDY Layer2 NULL identity checks and detail columns
-- PostgreSQL only. Run in DBeaver against the monitoring database.
-- Safe to run repeatedly. No explicit BEGIN is used so it also works when
-- DBeaver already owns the transaction.

WITH required_columns(category_name, check_column) AS (
    VALUES
        ('sea_ref_retail', 'item'),
        ('sea_ref_retail', 'product_url'),
        ('sea_ref_retail', 'account_name'),
        ('sea_ref_retail', 'country'),
        ('sea_ldy_retail', 'item'),
        ('sea_ldy_retail', 'product_url'),
        ('sea_ldy_retail', 'account_name'),
        ('sea_ldy_retail', 'country')
)
INSERT INTO public.monitoring_null_column
    (group_id, check_column, check_type, display_columns,
     query_columns, query_days, is_active, is_del)
SELECT
    null_group.id,
    required.check_column,
    'both',
    'crawl_strdatetime|item|account_name|country|sku|retailer_sku_name|product_url',
    CASE
        WHEN required.category_name = 'sea_ref_retail'
            THEN 'id|crawl_strdatetime|batch_id|account_name|country|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|ref_capacity|ref_refrigerator_type|product_url'
        ELSE 'id|crawl_strdatetime|batch_id|account_name|country|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|product_url'
    END,
    0,
    TRUE,
    FALSE
FROM required_columns required
JOIN public.monitoring_null_category category
  ON category.category_name = required.category_name
JOIN public.monitoring_null_group null_group
  ON null_group.category_id = category.id
WHERE null_group.is_active IS TRUE
  AND null_group.is_del IS FALSE
  AND NOT EXISTS (
      SELECT 1
      FROM public.monitoring_null_column existing
      WHERE existing.group_id = null_group.id
        AND existing.check_column = required.check_column
  );

UPDATE public.monitoring_null_column null_column
SET check_type = CASE
        WHEN null_column.check_column IN (
            'item', 'product_url', 'account_name', 'country'
        ) THEN 'both'
        ELSE null_column.check_type
    END,
    display_columns = CASE
        WHEN null_column.check_column IN (
            'item', 'account_name', 'country', 'sku',
            'retailer_sku_name', 'product_url'
        )
            THEN 'crawl_strdatetime|item|account_name|country|sku|retailer_sku_name|product_url'
        ELSE 'crawl_strdatetime|item|account_name|country|sku|retailer_sku_name|'
             || null_column.check_column || '|product_url'
    END,
    query_columns = CASE
        WHEN category.category_name = 'sea_ref_retail'
            THEN 'id|crawl_strdatetime|batch_id|account_name|country|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|ref_capacity|ref_refrigerator_type|product_url'
        ELSE 'id|crawl_strdatetime|batch_id|account_name|country|page_type|item|sku|retailer_sku_name|final_sku_price|star_rating|count_of_star_ratings|count_of_reviews|product_url'
    END,
    is_active = TRUE,
    is_del = FALSE
FROM public.monitoring_null_group null_group
JOIN public.monitoring_null_category category
  ON category.id = null_group.category_id
WHERE null_column.group_id = null_group.id
  AND category.category_name IN ('sea_ref_retail', 'sea_ldy_retail')
  AND null_group.is_active IS TRUE
  AND null_group.is_del IS FALSE
  AND category.is_active IS TRUE
  AND category.is_del IS FALSE;

-- Expected: REF 12 checks per retailer, LDY 10 checks per retailer.
SELECT
    category.category_name,
    null_group.display_name AS retailer,
    COUNT(*) AS configured_columns,
    STRING_AGG(
        null_column.check_column, ', '
        ORDER BY null_column.check_column
    ) AS check_columns
FROM public.monitoring_null_column null_column
JOIN public.monitoring_null_group null_group
  ON null_group.id = null_column.group_id
JOIN public.monitoring_null_category category
  ON category.id = null_group.category_id
WHERE category.category_name IN ('sea_ref_retail', 'sea_ldy_retail')
  AND null_column.is_active IS TRUE
  AND null_column.is_del IS FALSE
GROUP BY category.category_name, null_group.display_name
ORDER BY category.category_name, retailer;
