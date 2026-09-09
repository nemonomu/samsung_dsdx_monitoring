-- SEG Layer1 preflight. SELECT only; execute manually in DBeaver.
-- Replace every 2026-08-11 below with the inspection date to compare.
-- The server TimeZone does not establish the timezone used by the RDP collector.

SELECT table_schema, table_name, ordinal_position, column_name, data_type, udt_name
FROM information_schema.columns
WHERE table_schema = 'dx_seg'
  AND table_name IN ('dx_seg_tv_retail_com', 'dx_seg_ref_retail_com', 'dx_seg_ldy_retail_com',
                     'dx_seg_tv_retail_com_backup', 'dx_seg_ref_retail_com_backup', 'dx_seg_ldy_retail_com_backup')
ORDER BY table_name, ordinal_position;

SELECT tablename, indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'dx_seg'
  AND tablename IN ('dx_seg_tv_retail_com', 'dx_seg_ref_retail_com', 'dx_seg_ldy_retail_com',
                    'dx_seg_tv_retail_com_backup', 'dx_seg_ref_retail_com_backup', 'dx_seg_ldy_retail_com_backup')
ORDER BY tablename, indexname;

SELECT id, check_type, category, retailer, country, schedule_type,
       schedule_value, expected_count, us_start_hour, collection_duration_min,
       view_table_name, is_active, is_del
FROM public.monitoring_collection_schedule
WHERE check_type = 'seg_retail' OR UPPER(BTRIM(country)) = 'SEG'
ORDER BY check_type, category, retailer, id;

-- All batches are shown, including unexpected retailers/page types.
-- Rank counts may overlap; do not add MAIN + BSR to calculate raw_count.
SELECT 'TV' AS product, src.account_name, src.batch_id,
       LEFT(BTRIM(src.crawl_strdatetime), 10) AS source_date,
       COUNT(*) AS raw_count,
       COUNT(*) FILTER (WHERE LOWER(BTRIM(src.page_type)) = 'main') AS main_page_rows,
       COUNT(*) FILTER (WHERE LOWER(BTRIM(src.page_type)) = 'bsr') AS bsr_page_rows,
       COUNT(src.main_rank) AS main_rank_count,
       COUNT(src.bsr_rank) AS bsr_rank_count,
       COUNT(*) FILTER (WHERE src.main_rank IS NOT NULL AND src.bsr_rank IS NOT NULL) AS shared_rank_rows,
       COUNT(*) FILTER (WHERE LOWER(BTRIM(src.account_name)) = 'amazon' AND src.redirect IS TRUE) AS amazon_redirect_count,
       COUNT(*) FILTER (WHERE NOT EXISTS (
           SELECT 1 FROM dx_seg.dx_seg_tv_retail_com_backup bak WHERE bak.id = src.id
       )) AS backup_missing_count,
       MIN(src.id) AS min_id, MAX(src.id) AS max_id,
       MIN(src.crawl_strdatetime) AS first_recorded_time,
       MAX(src.crawl_strdatetime) AS last_recorded_time
FROM dx_seg.dx_seg_tv_retail_com src
WHERE LEFT(BTRIM(src.crawl_strdatetime), 10) = '2026-08-11'
GROUP BY src.account_name, src.batch_id, LEFT(BTRIM(src.crawl_strdatetime), 10)
UNION ALL
SELECT 'REF' AS product, src.account_name, src.batch_id,
       LEFT(BTRIM(src.crawl_strdatetime), 10) AS source_date,
       COUNT(*) AS raw_count,
       COUNT(*) FILTER (WHERE LOWER(BTRIM(src.page_type)) = 'main') AS main_page_rows,
       COUNT(*) FILTER (WHERE LOWER(BTRIM(src.page_type)) = 'bsr') AS bsr_page_rows,
       COUNT(src.main_rank) AS main_rank_count,
       COUNT(src.bsr_rank) AS bsr_rank_count,
       COUNT(*) FILTER (WHERE src.main_rank IS NOT NULL AND src.bsr_rank IS NOT NULL) AS shared_rank_rows,
       COUNT(*) FILTER (WHERE LOWER(BTRIM(src.account_name)) = 'amazon' AND src.redirect IS TRUE) AS amazon_redirect_count,
       COUNT(*) FILTER (WHERE NOT EXISTS (
           SELECT 1 FROM dx_seg.dx_seg_ref_retail_com_backup bak WHERE bak.id = src.id
       )) AS backup_missing_count,
       MIN(src.id) AS min_id, MAX(src.id) AS max_id,
       MIN(src.crawl_strdatetime) AS first_recorded_time,
       MAX(src.crawl_strdatetime) AS last_recorded_time
FROM dx_seg.dx_seg_ref_retail_com src
WHERE LEFT(BTRIM(src.crawl_strdatetime), 10) = '2026-08-11'
GROUP BY src.account_name, src.batch_id, LEFT(BTRIM(src.crawl_strdatetime), 10)
UNION ALL
SELECT 'LDY' AS product, src.account_name, src.batch_id,
       LEFT(BTRIM(src.crawl_strdatetime), 10) AS source_date,
       COUNT(*) AS raw_count,
       COUNT(*) FILTER (WHERE LOWER(BTRIM(src.page_type)) = 'main') AS main_page_rows,
       COUNT(*) FILTER (WHERE LOWER(BTRIM(src.page_type)) = 'bsr') AS bsr_page_rows,
       COUNT(src.main_rank) AS main_rank_count,
       COUNT(src.bsr_rank) AS bsr_rank_count,
       COUNT(*) FILTER (WHERE src.main_rank IS NOT NULL AND src.bsr_rank IS NOT NULL) AS shared_rank_rows,
       0 AS amazon_redirect_count,
       COUNT(*) FILTER (WHERE NOT EXISTS (
           SELECT 1 FROM dx_seg.dx_seg_ldy_retail_com_backup bak WHERE bak.id = src.id
       )) AS backup_missing_count,
       MIN(src.id) AS min_id, MAX(src.id) AS max_id,
       MIN(src.crawl_strdatetime) AS first_recorded_time,
       MAX(src.crawl_strdatetime) AS last_recorded_time
FROM dx_seg.dx_seg_ldy_retail_com src
WHERE LEFT(BTRIM(src.crawl_strdatetime), 10) = '2026-08-11'
GROUP BY src.account_name, src.batch_id, LEFT(BTRIM(src.crawl_strdatetime), 10)
ORDER BY product, account_name, max_id;
