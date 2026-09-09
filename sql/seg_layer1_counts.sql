-- SELECT only. Generated from the Layer1 repository queries; no database connection used.

-- Replace every 2026-08-11 with the inspection date to compare.

-- seg_tv: selected daily batch and counts

WITH dated_rows AS (
            SELECT id, batch_id, account_name, page_type, main_rank, bsr_rank
                   , redirect
            FROM dx_seg.dx_seg_tv_retail_com
            WHERE LEFT(BTRIM(crawl_strdatetime), 10) = '2026-08-11'
              AND LOWER(BTRIM(account_name)) IN ('mediamarkt', 'otto', 'amazon')
        ), latest_main_batches AS (
            SELECT DISTINCT ON (LOWER(BTRIM(account_name)))
                   LOWER(BTRIM(account_name)) AS retailer_key,
                   account_name, batch_id
            FROM dated_rows
            WHERE LOWER(BTRIM(page_type)) = 'main'
            ORDER BY LOWER(BTRIM(account_name)), id DESC
        )
        SELECT latest.account_name AS retailer, latest.batch_id,
               COUNT(*) AS actual_count,
               COUNT(rows.main_rank) AS main_count,
               COUNT(rows.bsr_rank) AS bsr_count,
               COUNT(*) FILTER (WHERE latest.retailer_key = 'amazon' AND rows.redirect IS TRUE) AS redirect_count
        FROM latest_main_batches latest
        JOIN dated_rows rows
          ON LOWER(BTRIM(rows.account_name)) = latest.retailer_key
         AND rows.batch_id IS NOT DISTINCT FROM latest.batch_id
        WHERE LOWER(BTRIM(rows.page_type)) IN ('main', 'bsr')
        GROUP BY latest.retailer_key, latest.account_name, latest.batch_id
        ORDER BY latest.retailer_key;

-- seg_tv: prior positive MAIN days used for integer average

WITH dated_rows AS (
            SELECT id, batch_id, LOWER(BTRIM(account_name)) AS retailer,
                   LOWER(BTRIM(page_type)) AS page_type, main_rank,
                   LEFT(BTRIM(crawl_strdatetime), 10) AS source_date
            FROM dx_seg.dx_seg_tv_retail_com
            WHERE LEFT(BTRIM(crawl_strdatetime), 10) < '2026-08-11'
              AND LEFT(BTRIM(crawl_strdatetime), 10)
                  ~ '^\d{4}-\d{2}-\d{2}$'
              AND LOWER(BTRIM(account_name)) IN ('mediamarkt', 'otto', 'amazon')
        ), latest_main_batches AS (
            SELECT DISTINCT ON (retailer, source_date)
                   retailer, source_date, batch_id
            FROM dated_rows
            WHERE page_type = 'main'
            ORDER BY retailer, source_date, id DESC
        ), daily_counts AS (
            SELECT latest.retailer, latest.source_date,
                   COUNT(rows.main_rank) AS main_count
            FROM latest_main_batches latest
            JOIN dated_rows rows
              ON rows.retailer = latest.retailer
             AND rows.source_date = latest.source_date
             AND rows.batch_id IS NOT DISTINCT FROM latest.batch_id
            WHERE rows.page_type IN ('main', 'bsr')
            GROUP BY latest.retailer, latest.source_date
            HAVING COUNT(rows.main_rank) > 0
        ), ranked_days AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY retailer ORDER BY source_date DESC
            ) AS day_rank
            FROM daily_counts
        )
        SELECT retailer, source_date, main_count
        FROM ranked_days
        WHERE day_rank <= 7
        ORDER BY retailer, source_date DESC;

-- seg_ref: selected daily batch and counts

WITH dated_rows AS (
            SELECT id, batch_id, account_name, page_type, main_rank, bsr_rank
                   , redirect
            FROM dx_seg.dx_seg_ref_retail_com
            WHERE LEFT(BTRIM(crawl_strdatetime), 10) = '2026-08-11'
              AND LOWER(BTRIM(account_name)) IN ('mediamarkt', 'otto', 'amazon')
        ), latest_main_batches AS (
            SELECT DISTINCT ON (LOWER(BTRIM(account_name)))
                   LOWER(BTRIM(account_name)) AS retailer_key,
                   account_name, batch_id
            FROM dated_rows
            WHERE LOWER(BTRIM(page_type)) = 'main'
            ORDER BY LOWER(BTRIM(account_name)), id DESC
        )
        SELECT latest.account_name AS retailer, latest.batch_id,
               COUNT(*) AS actual_count,
               COUNT(rows.main_rank) AS main_count,
               COUNT(rows.bsr_rank) AS bsr_count,
               COUNT(*) FILTER (WHERE latest.retailer_key = 'amazon' AND rows.redirect IS TRUE) AS redirect_count
        FROM latest_main_batches latest
        JOIN dated_rows rows
          ON LOWER(BTRIM(rows.account_name)) = latest.retailer_key
         AND rows.batch_id IS NOT DISTINCT FROM latest.batch_id
        WHERE LOWER(BTRIM(rows.page_type)) IN ('main', 'bsr')
        GROUP BY latest.retailer_key, latest.account_name, latest.batch_id
        ORDER BY latest.retailer_key;

-- seg_ref: prior positive MAIN days used for integer average

WITH dated_rows AS (
            SELECT id, batch_id, LOWER(BTRIM(account_name)) AS retailer,
                   LOWER(BTRIM(page_type)) AS page_type, main_rank,
                   LEFT(BTRIM(crawl_strdatetime), 10) AS source_date
            FROM dx_seg.dx_seg_ref_retail_com
            WHERE LEFT(BTRIM(crawl_strdatetime), 10) < '2026-08-11'
              AND LEFT(BTRIM(crawl_strdatetime), 10)
                  ~ '^\d{4}-\d{2}-\d{2}$'
              AND LOWER(BTRIM(account_name)) IN ('mediamarkt', 'otto', 'amazon')
        ), latest_main_batches AS (
            SELECT DISTINCT ON (retailer, source_date)
                   retailer, source_date, batch_id
            FROM dated_rows
            WHERE page_type = 'main'
            ORDER BY retailer, source_date, id DESC
        ), daily_counts AS (
            SELECT latest.retailer, latest.source_date,
                   COUNT(rows.main_rank) AS main_count
            FROM latest_main_batches latest
            JOIN dated_rows rows
              ON rows.retailer = latest.retailer
             AND rows.source_date = latest.source_date
             AND rows.batch_id IS NOT DISTINCT FROM latest.batch_id
            WHERE rows.page_type IN ('main', 'bsr')
            GROUP BY latest.retailer, latest.source_date
            HAVING COUNT(rows.main_rank) > 0
        ), ranked_days AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY retailer ORDER BY source_date DESC
            ) AS day_rank
            FROM daily_counts
        )
        SELECT retailer, source_date, main_count
        FROM ranked_days
        WHERE day_rank <= 7
        ORDER BY retailer, source_date DESC;

-- seg_ldy: selected daily batch and counts

WITH dated_rows AS (
            SELECT id, batch_id, account_name, page_type, main_rank, bsr_rank

            FROM dx_seg.dx_seg_ldy_retail_com
            WHERE LEFT(BTRIM(crawl_strdatetime), 10) = '2026-08-11'
              AND LOWER(BTRIM(account_name)) IN ('mediamarkt', 'otto')
        ), latest_main_batches AS (
            SELECT DISTINCT ON (LOWER(BTRIM(account_name)))
                   LOWER(BTRIM(account_name)) AS retailer_key,
                   account_name, batch_id
            FROM dated_rows
            WHERE LOWER(BTRIM(page_type)) = 'main'
            ORDER BY LOWER(BTRIM(account_name)), id DESC
        )
        SELECT latest.account_name AS retailer, latest.batch_id,
               COUNT(*) AS actual_count,
               COUNT(rows.main_rank) AS main_count,
               COUNT(rows.bsr_rank) AS bsr_count,
               0 AS redirect_count
        FROM latest_main_batches latest
        JOIN dated_rows rows
          ON LOWER(BTRIM(rows.account_name)) = latest.retailer_key
         AND rows.batch_id IS NOT DISTINCT FROM latest.batch_id
        WHERE LOWER(BTRIM(rows.page_type)) IN ('main', 'bsr')
        GROUP BY latest.retailer_key, latest.account_name, latest.batch_id
        ORDER BY latest.retailer_key;

-- seg_ldy: prior positive MAIN days used for integer average

WITH dated_rows AS (
            SELECT id, batch_id, LOWER(BTRIM(account_name)) AS retailer,
                   LOWER(BTRIM(page_type)) AS page_type, main_rank,
                   LEFT(BTRIM(crawl_strdatetime), 10) AS source_date
            FROM dx_seg.dx_seg_ldy_retail_com
            WHERE LEFT(BTRIM(crawl_strdatetime), 10) < '2026-08-11'
              AND LEFT(BTRIM(crawl_strdatetime), 10)
                  ~ '^\d{4}-\d{2}-\d{2}$'
              AND LOWER(BTRIM(account_name)) IN ('mediamarkt', 'otto')
        ), latest_main_batches AS (
            SELECT DISTINCT ON (retailer, source_date)
                   retailer, source_date, batch_id
            FROM dated_rows
            WHERE page_type = 'main'
            ORDER BY retailer, source_date, id DESC
        ), daily_counts AS (
            SELECT latest.retailer, latest.source_date,
                   COUNT(rows.main_rank) AS main_count
            FROM latest_main_batches latest
            JOIN dated_rows rows
              ON rows.retailer = latest.retailer
             AND rows.source_date = latest.source_date
             AND rows.batch_id IS NOT DISTINCT FROM latest.batch_id
            WHERE rows.page_type IN ('main', 'bsr')
            GROUP BY latest.retailer, latest.source_date
            HAVING COUNT(rows.main_rank) > 0
        ), ranked_days AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY retailer ORDER BY source_date DESC
            ) AS day_rank
            FROM daily_counts
        )
        SELECT retailer, source_date, main_count
        FROM ranked_days
        WHERE day_rank <= 7
        ORDER BY retailer, source_date DESC;
