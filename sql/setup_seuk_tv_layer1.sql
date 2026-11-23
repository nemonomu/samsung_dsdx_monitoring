-- Layer 1 only. Apply to DX PostgreSQL at deployment. Set prefix to 'test_' for test settings.
BEGIN;

DO $seuk$
DECLARE
    prefix text := '';
    schedules text;
    account text;
    updated integer;
BEGIN
    IF prefix NOT IN ('', 'test_') THEN
        RAISE EXCEPTION 'prefix must be empty or test_';
    END IF;
    schedules := prefix || 'monitoring_collection_schedule';
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'dx_seuk' AND table_name = 'dx_seuk_tv_retail_com'
          AND column_name = 'crawl_datetime' AND data_type = 'text') THEN
        RAISE EXCEPTION 'SEUK TV crawl_datetime must retain the original timestamp text';
    END IF;

    EXECUTE format('LOCK TABLE public.%I IN SHARE ROW EXCLUSIVE MODE', schedules);
    EXECUTE format('UPDATE public.%I SET collection_duration_min = 300,
        description = REPLACE(description, ''01:00~04:00'', ''01:00~06:00''),
        updated_at = NOW(), updated_id = ''setup_seuk_tv_layer1''
        WHERE check_type = ''seuk_retail'' AND is_active = TRUE AND is_del = 0
          AND (LOWER(BTRIM(retailer)) = ''currys'' AND category IN (''TV'', ''REF'', ''LDY'', ''LDY_DRYER'')
              OR LOWER(BTRIM(retailer)) = ''ao'' AND category IN (''REF'', ''LDY'', ''LDY_DRYER''))', schedules);

    FOREACH account IN ARRAY ARRAY['Amazon', 'Argos'] LOOP
        EXECUTE format('UPDATE public.%I SET check_group = ''Retail'', check_name = ''SEUK TV'',
            schedule_type = ''daily'', schedule_value = NULL, us_start_hour = NULL,
            country = ''SEUK'', expected_count = 0, collection_duration_min = 300,
            view_table_name = ''dx_seuk.dx_seuk_tv_retail_com'', sort_order = 7, description = $2,
            is_active = TRUE, is_del = 0, updated_at = NOW(), updated_id = ''setup_seuk_tv_layer1''
            WHERE check_type = ''seuk_retail'' AND category = ''TV''
              AND LOWER(BTRIM(retailer)) = LOWER($1)', schedules)
        USING account, 'SEUK TV ' || account || ' 당일(D) · KST 01:00~06:00 · 2026-11-22 시작';
        GET DIAGNOSTICS updated = ROW_COUNT;
        IF updated > 1 THEN
            RAISE EXCEPTION 'Duplicate SEUK TV schedule for %', account;
        ELSIF updated = 0 THEN
            EXECUTE format('INSERT INTO public.%I
                (check_group, check_type, check_name, category, schedule_type, retailer, expected_count,
                 country, collection_duration_min, view_table_name, sort_order, description, is_active,
                 is_del, created_at, created_id, updated_at, updated_id)
                VALUES (''Retail'', ''seuk_retail'', ''SEUK TV'', ''TV'', ''daily'', $1, 0, ''SEUK'', 300,
                        ''dx_seuk.dx_seuk_tv_retail_com'', 7, $2, TRUE, 0,
                        NOW(), ''setup_seuk_tv_layer1'', NOW(), ''setup_seuk_tv_layer1'')', schedules)
            USING account, 'SEUK TV ' || account || ' 당일(D) · KST 01:00~06:00 · 2026-11-22 시작';
        END IF;
    END LOOP;
END
$seuk$;

COMMIT;
