-- SEDA Layer 1 daily collection schedule registration.
-- Run this on the monitoring database after deploying the application code.

BEGIN;

WITH source(category, retailer, table_name) AS (
    VALUES
        ('TV',  'Magalu',      'dx_seda.dx_seda_tv_retail_com'),
        ('TV',  'Casas Bahia', 'dx_seda.dx_seda_tv_retail_com'),
        ('REF', 'Magalu',      'dx_seda.dx_seda_ref_retail_com'),
        ('REF', 'Casas Bahia', 'dx_seda.dx_seda_ref_retail_com'),
        ('LDY', 'Magalu',      'dx_seda.dx_seda_ldy_retail_com'),
        ('LDY', 'Casas Bahia', 'dx_seda.dx_seda_ldy_retail_com')
), updated AS (
    UPDATE public.monitoring_collection_schedule target
    SET check_group = 'Retail',
        check_name = 'SEDA ' || source.category || ' 수집',
        schedule_type = 'daily',
        schedule_value = NULL,
        us_start_hour = NULL,
        expected_count = 300,
        country = 'SEDA',
        collection_duration_min = 600,
        view_table_name = source.table_name,
        sort_order = 1,
        description = 'SEDA 브라질 ' || source.retailer || ' ' ||
                      source.category || ' 전날(D-1) 수집',
        is_active = TRUE,
        is_del = 0,
        updated_at = NOW(),
        updated_id = 'setup_seda_layer1'
    FROM source
    WHERE target.check_type = 'seda_retail'
      AND target.category = source.category
      AND LOWER(REPLACE(BTRIM(target.retailer), ' ', '')) =
          LOWER(REPLACE(source.retailer, ' ', ''))
    RETURNING target.id
)
INSERT INTO public.monitoring_collection_schedule (
    check_group, check_type, check_name, category, schedule_type,
    schedule_value, us_start_hour, retailer, expected_count, country,
    collection_duration_min, view_table_name, sort_order, description,
    is_active, is_del, created_at, created_id, updated_at, updated_id
)
SELECT
    'Retail', 'seda_retail', 'SEDA ' || source.category || ' 수집',
    source.category, 'daily', NULL, NULL, source.retailer, 300, 'SEDA', 600,
    source.table_name, 1,
    'SEDA 브라질 ' || source.retailer || ' ' || source.category ||
    ' 전날(D-1) 수집',
    TRUE, 0, NOW(), 'setup_seda_layer1', NOW(), 'setup_seda_layer1'
FROM source
WHERE NOT EXISTS (
    SELECT 1
    FROM public.monitoring_collection_schedule target
    WHERE target.check_type = 'seda_retail'
      AND target.category = source.category
      AND LOWER(REPLACE(BTRIM(target.retailer), ' ', '')) =
          LOWER(REPLACE(source.retailer, ' ', ''))
);

COMMIT;

SELECT check_type, category, retailer, country, view_table_name, is_active
FROM public.monitoring_collection_schedule
WHERE check_type = 'seda_retail' AND is_del = 0
ORDER BY category, retailer;
