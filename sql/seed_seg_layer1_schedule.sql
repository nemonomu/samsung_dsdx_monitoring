-- Run manually in DBeaver only after reviewing seg_layer1_preflight.sql results.
-- Activates SEG Layer1 only. No NULL/format/cross-field/email configuration.
-- The service uses KST 07:00-12:00 and integer historical MAIN averages.
-- expected_count=0 is an unused schedule placeholder, not the runtime baseline.
BEGIN;
LOCK TABLE public.monitoring_collection_schedule IN SHARE ROW EXCLUSIVE MODE;
DO $$
DECLARE physical_count integer; exact_count integer;
BEGIN
    IF (SELECT COUNT(*) FROM information_schema.columns
        WHERE table_schema = 'dx_seg' AND column_name = 'crawl_strdatetime'
          AND data_type = 'text'
          AND table_name IN ('dx_seg_tv_retail_com','dx_seg_ref_retail_com','dx_seg_ldy_retail_com')) <> 3 THEN
        RAISE EXCEPTION 'SEG date columns must first be verified as text';
    END IF;
    SELECT COUNT(*) INTO physical_count FROM public.monitoring_collection_schedule
    WHERE check_type = 'seg_retail';
    WITH expected(category, retailer, view_table_name) AS (VALUES
        ('TV', 'Mediamarkt', 'dx_seg.dx_seg_tv_retail_com'),
        ('TV', 'OTTO', 'dx_seg.dx_seg_tv_retail_com'),
        ('TV', 'Amazon', 'dx_seg.dx_seg_tv_retail_com'),
        ('REF', 'Mediamarkt', 'dx_seg.dx_seg_ref_retail_com'),
        ('REF', 'OTTO', 'dx_seg.dx_seg_ref_retail_com'),
        ('REF', 'Amazon', 'dx_seg.dx_seg_ref_retail_com'),
        ('LDY', 'Mediamarkt', 'dx_seg.dx_seg_ldy_retail_com'),
        ('LDY', 'OTTO', 'dx_seg.dx_seg_ldy_retail_com')
    )
    SELECT COUNT(*) INTO exact_count
    FROM public.monitoring_collection_schedule s
    JOIN expected e ON s.category = e.category AND s.retailer = e.retailer
      AND s.view_table_name = e.view_table_name
    WHERE s.check_type = 'seg_retail' AND s.check_group = 'Retail'
      AND s.check_name = 'SEG ' || e.category || ' 수집'
      AND s.country = 'SEG' AND s.schedule_type = 'daily'
      AND s.schedule_value IS NULL AND s.us_start_hour IS NULL
      AND s.expected_count = 0 AND s.collection_duration_min = 300
      AND s.sort_order = 5 AND s.is_active IS TRUE AND s.is_del = 0;
    IF physical_count <> 0 AND (physical_count <> 8 OR exact_count <> 8) THEN
        RAISE EXCEPTION 'Unexpected existing SEG schedule rows; stop and review preflight';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.monitoring_collection_schedule
        WHERE check_type = 'seg_retail' GROUP BY category, retailer HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'Duplicate SEG schedule rows';
    END IF;
END $$;

WITH expected(category, retailer, view_table_name) AS (VALUES
        ('TV', 'Mediamarkt', 'dx_seg.dx_seg_tv_retail_com'),
        ('TV', 'OTTO', 'dx_seg.dx_seg_tv_retail_com'),
        ('TV', 'Amazon', 'dx_seg.dx_seg_tv_retail_com'),
        ('REF', 'Mediamarkt', 'dx_seg.dx_seg_ref_retail_com'),
        ('REF', 'OTTO', 'dx_seg.dx_seg_ref_retail_com'),
        ('REF', 'Amazon', 'dx_seg.dx_seg_ref_retail_com'),
        ('LDY', 'Mediamarkt', 'dx_seg.dx_seg_ldy_retail_com'),
        ('LDY', 'OTTO', 'dx_seg.dx_seg_ldy_retail_com')
)
INSERT INTO public.monitoring_collection_schedule (
    check_group, check_type, check_name, category, schedule_type, schedule_value,
    us_start_hour, retailer, expected_count, country, collection_duration_min,
    view_table_name, sort_order, description, is_active, is_del,
    created_at, created_id, updated_at, updated_id
)
SELECT 'Retail', 'seg_retail', 'SEG ' || category || ' 수집', category,
       'daily', NULL, NULL, retailer, 0, 'SEG', 300, view_table_name, 5,
       'SEG Layer1 KST 07:00-12:00 / previous 7 positive MAIN days, integer average',
       TRUE, 0, NOW(), 'seed_seg_layer1_schedule', NOW(), 'seed_seg_layer1_schedule'
FROM expected
WHERE NOT EXISTS (
    SELECT 1 FROM public.monitoring_collection_schedule WHERE check_type = 'seg_retail'
);

DO $$
DECLARE physical_count integer; exact_count integer;
BEGIN
    SELECT COUNT(*) INTO physical_count FROM public.monitoring_collection_schedule
    WHERE check_type = 'seg_retail';
    WITH expected(category, retailer, view_table_name) AS (VALUES
        ('TV', 'Mediamarkt', 'dx_seg.dx_seg_tv_retail_com'),
        ('TV', 'OTTO', 'dx_seg.dx_seg_tv_retail_com'),
        ('TV', 'Amazon', 'dx_seg.dx_seg_tv_retail_com'),
        ('REF', 'Mediamarkt', 'dx_seg.dx_seg_ref_retail_com'),
        ('REF', 'OTTO', 'dx_seg.dx_seg_ref_retail_com'),
        ('REF', 'Amazon', 'dx_seg.dx_seg_ref_retail_com'),
        ('LDY', 'Mediamarkt', 'dx_seg.dx_seg_ldy_retail_com'),
        ('LDY', 'OTTO', 'dx_seg.dx_seg_ldy_retail_com')
    )
    SELECT COUNT(*) INTO exact_count
    FROM public.monitoring_collection_schedule s
    JOIN expected e ON s.category = e.category AND s.retailer = e.retailer
      AND s.view_table_name = e.view_table_name
    WHERE s.check_type = 'seg_retail' AND s.check_group = 'Retail'
      AND s.check_name = 'SEG ' || e.category || ' 수집'
      AND s.country = 'SEG' AND s.schedule_type = 'daily'
      AND s.schedule_value IS NULL AND s.us_start_hour IS NULL
      AND s.expected_count = 0 AND s.collection_duration_min = 300
      AND s.sort_order = 5 AND s.is_active IS TRUE AND s.is_del = 0;
    IF physical_count <> 8 OR exact_count <> 8 THEN
        RAISE EXCEPTION 'SEG schedule poststate mismatch';
    END IF;
END $$;
SELECT 'SEG_LAYER1_PRECOMMIT_VERIFIED' AS marker;
COMMIT;

SELECT 'SEG_LAYER1_POSTCOMMIT_VERIFY' AS marker, id, category, retailer,
       view_table_name, is_active, is_del, created_id
FROM public.monitoring_collection_schedule WHERE check_type = 'seg_retail'
ORDER BY category, retailer;
