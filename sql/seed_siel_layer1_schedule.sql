-- SIEL Layer 1 schedule activation (DBeaver execution only).
--
-- Application policy:
--   inspection date D = source date D (Asia/Seoul)
--   expected count 300 / completed OK threshold 200
--   current-day collection completes after KST 09:00
--
-- The application uses these rows to activate the SIEL Retail card and
-- sidebar entry. SIEL collection-phase calculations themselves are handled
-- by the SIEL-only service and do not use us_start_hour.

BEGIN;

DO $$
DECLARE
    physical_count integer;
    exact_count integer;
BEGIN
    SELECT COUNT(DISTINCT (schedule.category, schedule.retailer))
    INTO physical_count
    FROM public.monitoring_collection_schedule
    WHERE check_type = 'siel_retail';

    WITH expected(
        category, retailer, view_table_name
    ) AS (
        VALUES
            ('TV',  'Amazon',   'dx_siel.dx_siel_tv_retail_com'),
            ('TV',  'Flipkart', 'dx_siel.dx_siel_tv_retail_com'),
            ('REF', 'Amazon',   'dx_siel.dx_siel_ref_retail_com'),
            ('REF', 'Flipkart', 'dx_siel.dx_siel_ref_retail_com'),
            ('LDY', 'Amazon',   'dx_siel.dx_siel_ldy_retail_com'),
            ('LDY', 'Flipkart', 'dx_siel.dx_siel_ldy_retail_com')
    )
    SELECT COUNT(DISTINCT (schedule.category, schedule.retailer))
    INTO exact_count
    FROM public.monitoring_collection_schedule schedule
    JOIN expected
      ON schedule.category = expected.category
     AND schedule.retailer = expected.retailer
     AND schedule.view_table_name = expected.view_table_name
    WHERE schedule.check_group = 'Retail'
      AND schedule.check_type = 'siel_retail'
      AND schedule.check_name = 'SIEL ' || expected.category || ' 수집'
      AND schedule.schedule_type = 'daily'
      AND schedule.schedule_value IS NULL
      AND schedule.us_start_hour IS NULL
      AND schedule.expected_count = 300
      AND schedule.country = 'SIEL'
      AND schedule.collection_duration_min = 540
      AND schedule.sort_order = 3
      AND schedule.is_active IS TRUE
      AND COALESCE(schedule.is_del, 0) = 0;

    IF physical_count NOT IN (0, 6) THEN
        RAISE EXCEPTION
            'Unexpected siel_retail schedule row count: % (expected 0 or 6)',
            physical_count;
    END IF;
    IF physical_count = 6 AND exact_count <> 6 THEN
        RAISE EXCEPTION
            'Existing siel_retail schedule rows do not match the exact policy';
    END IF;
END $$;

WITH expected(
    category, retailer, view_table_name
) AS (
    VALUES
        ('TV',  'Amazon',   'dx_siel.dx_siel_tv_retail_com'),
        ('TV',  'Flipkart', 'dx_siel.dx_siel_tv_retail_com'),
        ('REF', 'Amazon',   'dx_siel.dx_siel_ref_retail_com'),
        ('REF', 'Flipkart', 'dx_siel.dx_siel_ref_retail_com'),
        ('LDY', 'Amazon',   'dx_siel.dx_siel_ldy_retail_com'),
        ('LDY', 'Flipkart', 'dx_siel.dx_siel_ldy_retail_com')
)
INSERT INTO public.monitoring_collection_schedule (
    check_group,
    check_type,
    check_name,
    category,
    schedule_type,
    schedule_value,
    us_start_hour,
    retailer,
    expected_count,
    country,
    collection_duration_min,
    view_table_name,
    sort_order,
    description,
    is_active,
    is_del,
    created_at,
    created_id,
    updated_at,
    updated_id
)
SELECT
    'Retail',
    'siel_retail',
    'SIEL ' || expected.category || ' 수집',
    expected.category,
    'daily',
    NULL,
    NULL,
    expected.retailer,
    300,
    'SIEL',
    540,
    expected.view_table_name,
    3,
    'SIEL ' || expected.category || ' ' || expected.retailer
        || ' 당일(D) KST 수집',
    TRUE,
    0,
    NOW(),
    'seed_siel_layer1_schedule',
    NOW(),
    'seed_siel_layer1_schedule'
FROM expected
WHERE NOT EXISTS (
    SELECT 1
    FROM public.monitoring_collection_schedule existing
    WHERE existing.check_type = 'siel_retail'
      AND existing.category = expected.category
      AND existing.retailer = expected.retailer
);

DO $$
DECLARE
    physical_count integer;
    exact_count integer;
BEGIN
    SELECT COUNT(*)
    INTO physical_count
    FROM public.monitoring_collection_schedule
    WHERE check_type = 'siel_retail';

    WITH expected(
        category, retailer, view_table_name
    ) AS (
        VALUES
            ('TV',  'Amazon',   'dx_siel.dx_siel_tv_retail_com'),
            ('TV',  'Flipkart', 'dx_siel.dx_siel_tv_retail_com'),
            ('REF', 'Amazon',   'dx_siel.dx_siel_ref_retail_com'),
            ('REF', 'Flipkart', 'dx_siel.dx_siel_ref_retail_com'),
            ('LDY', 'Amazon',   'dx_siel.dx_siel_ldy_retail_com'),
            ('LDY', 'Flipkart', 'dx_siel.dx_siel_ldy_retail_com')
    )
    SELECT COUNT(*)
    INTO exact_count
    FROM public.monitoring_collection_schedule schedule
    JOIN expected
      ON schedule.category = expected.category
     AND schedule.retailer = expected.retailer
     AND schedule.view_table_name = expected.view_table_name
    WHERE schedule.check_group = 'Retail'
      AND schedule.check_type = 'siel_retail'
      AND schedule.check_name = 'SIEL ' || expected.category || ' 수집'
      AND schedule.schedule_type = 'daily'
      AND schedule.schedule_value IS NULL
      AND schedule.us_start_hour IS NULL
      AND schedule.expected_count = 300
      AND schedule.country = 'SIEL'
      AND schedule.collection_duration_min = 540
      AND schedule.sort_order = 3
      AND schedule.is_active IS TRUE
      AND COALESCE(schedule.is_del, 0) = 0;

    IF physical_count <> 6 OR exact_count <> 6 THEN
        RAISE EXCEPTION
            'SIEL Layer 1 schedule poststate failed: physical %, exact %',
            physical_count, exact_count;
    END IF;
END $$;

COMMIT;

SELECT
    id,
    check_type,
    check_name,
    category,
    retailer,
    expected_count,
    country,
    collection_duration_min,
    view_table_name,
    sort_order,
    is_active,
    is_del
FROM public.monitoring_collection_schedule
WHERE check_type = 'siel_retail'
ORDER BY category, retailer, id;
