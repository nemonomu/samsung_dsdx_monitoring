-- Read-only. No application startup or .env access required.
-- Compare production/development configuration in the selected monitoring DB.
-- Expected: a Lowes group with category/group active, not deleted,
-- active_columns=11 and loading_type_in_null=false in the environment in use.
SELECT 'production' AS environment, c.category_name,
       c.is_active AS category_active, c.is_del AS category_deleted,
       g.check_name, g.display_name, g.table_name, g.date_column,
       g.is_active AS group_active, g.is_del AS group_deleted,
       COUNT(n.id) FILTER (WHERE n.is_active AND NOT n.is_del) AS active_columns,
       COALESCE(BOOL_OR(n.check_column = 'loading_type'
                       AND n.is_active AND NOT n.is_del), FALSE) AS loading_type_in_null
FROM (VALUES ('sea_ldy_dryer_retail')) expected(category_name)
LEFT JOIN public.monitoring_null_category c ON c.category_name = expected.category_name
LEFT JOIN public.monitoring_null_group g ON g.category_id = c.id
 AND (g.check_name = 'lowes_sea_ldy_dryer' OR LOWER(BTRIM(g.display_name)) = 'lowes')
LEFT JOIN public.monitoring_null_column n ON n.group_id = g.id
GROUP BY c.id, g.id
UNION ALL
SELECT 'development', c.category_name, c.is_active, c.is_del,
       g.check_name, g.display_name, g.table_name, g.date_column, g.is_active, g.is_del,
       COUNT(n.id) FILTER (WHERE n.is_active AND NOT n.is_del),
       COALESCE(BOOL_OR(n.check_column = 'loading_type'
                       AND n.is_active AND NOT n.is_del), FALSE)
FROM (VALUES ('sea_ldy_dryer_retail')) expected(category_name)
LEFT JOIN public.test_monitoring_null_category c ON c.category_name = expected.category_name
LEFT JOIN public.test_monitoring_null_group g ON g.category_id = c.id
 AND (g.check_name = 'lowes_sea_ldy_dryer' OR LOWER(BTRIM(g.display_name)) = 'lowes')
LEFT JOIN public.test_monitoring_null_column n ON n.group_id = g.id
GROUP BY c.id, g.id;

-- Inspection 2026-10-19 is source date 2026-10-18 for SEA (D-1).
-- Raw dates only: no timezone conversion or batch-name-derived date.
SELECT batch_id, COUNT(*) AS rows, COUNT(main_rank) AS main_rows,
       COUNT(bsr_rank) AS bsr_rows, MAX(id) AS latest_id
FROM public.ldy_dryer_retail
WHERE LOWER(BTRIM(account_name)) = 'lowes'
  AND LEFT(BTRIM(CAST(crawl_datetime AS text)), 10) = '2026-10-18'
GROUP BY batch_id ORDER BY MAX(id) DESC;
