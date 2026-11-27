-- Register Walmart and Sam's Club TV in collection schedule and column settings.
-- Run after setup_sem_liverpool_monitoring.sql. Use 'test_' for a test registry.
BEGIN;

DO $sem_tv$
DECLARE
    prefix CONSTANT text := '';
    source_table CONSTANT text := 'dx_sem.dx_sem_tv_retail_com';
    marker CONSTANT text := 'setup_sem_tv_monitoring';
    required CONSTANT text[] := ARRAY['country', 'account_name', 'item', 'sku',
        'retailer_sku_name', 'product_url', 'crawl_datetime', 'calendar_week',
        'final_sku_price', 'screen_size'];
    editable CONSTANT text[] := ARRAY['country', 'account_name', 'item', 'sku',
        'retailer_sku_name', 'product_url', 'calendar_week', 'final_sku_price',
        'screen_size', 'original_sku_price', 'savings', 'star_rating',
        'count_of_star_ratings', 'count_of_reviews'];
    schedules text := prefix || 'monitoring_collection_schedule';
    categories text := prefix || 'monitoring_null_category';
    groups text := prefix || 'monitoring_null_group';
    null_columns text := prefix || 'monitoring_null_column';
    retail_columns text := prefix || 'monitoring_retail_columns';
    seller text;
    check_key text;
    field text;
    display_columns text;
    category_id bigint;
    group_id bigint;
    valid boolean;
    physical_columns CONSTANT text[] := editable || ARRAY['id', 'batch_id', 'crawl_datetime',
        'main_rank', 'bsr_rank'];
BEGIN
    IF prefix NOT IN ('', 'test_') THEN
        RAISE EXCEPTION 'prefix must be empty or test_';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'dx_sem' AND table_name = 'dx_sem_tv_retail_com'
          AND column_name = 'crawl_datetime' AND data_type = 'text') THEN
        RAISE EXCEPTION 'SEM TV crawl_datetime must retain the source timestamp text';
    END IF;
    IF (SELECT count(*) FROM information_schema.columns
        WHERE table_schema = 'dx_sem' AND table_name = 'dx_sem_tv_retail_com'
          AND column_name = ANY(physical_columns)) <> cardinality(physical_columns) THEN
        RAISE EXCEPTION 'Required SEM TV source columns are missing';
    END IF;
    EXECUTE format('LOCK TABLE public.%I, public.%I, public.%I, public.%I, public.%I
                    IN SHARE ROW EXCLUSIVE MODE',
                   schedules, categories, groups, null_columns, retail_columns);
    EXECUTE format('SELECT id FROM public.%I WHERE category_name = ''sem_tv_retail''
                    AND is_active AND NOT is_del', categories) INTO STRICT category_id;

    FOREACH seller IN ARRAY ARRAY['Walmart', 'Sam''s Club'] LOOP
        EXECUTE format('INSERT INTO public.%I (check_group, check_type, check_name,
            category, schedule_type, retailer, expected_count, country,
            collection_duration_min, view_table_name, sort_order, description,
            is_active, is_del, created_at, created_id, updated_at, updated_id)
            SELECT ''Retail'', ''sem_retail'', ''SEM TV 수집'', ''TV'', ''daily'', $1,
                   0, ''SEM'', 270, $2, 4, $3, TRUE, 0, NOW(), $4, NOW(), $4
            WHERE NOT EXISTS (SELECT 1 FROM public.%I WHERE check_type = ''sem_retail''
                AND category = ''TV'' AND lower(btrim(retailer)) = lower($1))',
            schedules, schedules)
        USING seller, source_table,
            'SEM TV ' || seller || ' 당일(D) · KST 09:00~13:30 · 2026-11-27 시작', marker;
        EXECUTE format('SELECT count(*) = 1 AND bool_and(is_active AND is_del = 0
                AND view_table_name = $2) FROM public.%I WHERE check_type = ''sem_retail''
                AND category = ''TV'' AND lower(btrim(retailer)) = lower($1)', schedules)
        INTO valid USING seller, source_table;
        IF valid IS NOT TRUE THEN RAISE EXCEPTION 'Invalid SEM TV schedule for %', seller; END IF;

        check_key := CASE seller WHEN 'Walmart' THEN 'walmart_sem_tv' ELSE 'sams_club_sem_tv' END;
        EXECUTE format('INSERT INTO public.%I (category_id, check_name, display_name,
            table_name, date_column, display_order, is_active, is_del, created_at, created_id)
            SELECT $1, $2, $3, $4, ''crawl_datetime'', $5, TRUE, FALSE, NOW(), $6
            WHERE NOT EXISTS (SELECT 1 FROM public.%I WHERE category_id = $1 AND check_name = $2)',
            groups, groups)
        USING category_id, check_key, seller, source_table,
            CASE seller WHEN 'Walmart' THEN 2 ELSE 3 END, marker;
        EXECUTE format('SELECT id, is_active AND NOT is_del AND table_name = $3
                AND date_column = ''crawl_datetime'' FROM public.%I
                WHERE category_id = $1 AND check_name = $2', groups)
        INTO STRICT group_id, valid USING category_id, check_key, source_table;
        IF valid IS NOT TRUE THEN RAISE EXCEPTION 'Invalid SEM TV NULL group for %', seller; END IF;

        FOREACH field IN ARRAY required LOOP
            SELECT string_agg(name, '|' ORDER BY first_position) INTO display_columns
            FROM (SELECT name, min(position) AS first_position
                  FROM unnest(ARRAY['id', 'crawl_datetime', 'item', 'sku', 'retailer_sku_name',
                      field, 'product_url']) WITH ORDINALITY AS cols(name, position)
                  GROUP BY name) AS ordered;
            EXECUTE format('INSERT INTO public.%I (group_id, check_column, check_type,
                display_columns, query_columns, query_days, is_active, is_del, created_at, created_id)
                SELECT $1, $2, ''both'', $3, $3, 0, TRUE, FALSE, NOW(), $4
                WHERE NOT EXISTS (SELECT 1 FROM public.%I WHERE group_id = $1 AND check_column = $2)',
                null_columns, null_columns)
            USING group_id, field, display_columns, marker;
            EXECUTE format('SELECT count(*) = 1 AND bool_and(is_active AND NOT is_del)
                FROM public.%I WHERE group_id = $1 AND check_column = $2', null_columns)
            INTO valid USING group_id, field;
            IF valid IS NOT TRUE THEN
                RAISE EXCEPTION 'Invalid SEM TV NULL field %.%', seller, field;
            END IF;
        END LOOP;

        FOREACH field IN ARRAY editable || ARRAY['crawl_datetime', 'main_rank', 'bsr_rank'] LOOP
            EXECUTE format('INSERT INTO public.%I (product_line, column_name, retailer,
                duplicate_key, skip_missing_check, is_editable, is_active, is_del, created_at, created_id)
                SELECT ''sem_tv'', $1, $2, $3, $4, $5, TRUE, FALSE, NOW(), $6
                WHERE NOT EXISTS (SELECT 1 FROM public.%I WHERE product_line = ''sem_tv''
                    AND column_name = $1 AND lower(btrim(retailer)) = lower($2))',
                retail_columns, retail_columns)
            USING field, seller, field = 'item', NOT (field = ANY(required)),
                field = ANY(editable), marker;
            EXECUTE format('SELECT count(*) = 1 AND bool_and(is_active AND NOT is_del
                AND duplicate_key = $3 AND skip_missing_check = $4 AND is_editable = $5)
                FROM public.%I WHERE product_line = ''sem_tv''
                    AND column_name = $1 AND lower(btrim(retailer)) = lower($2)', retail_columns)
            INTO valid USING field, seller, field = 'item', NOT (field = ANY(required)),
                field = ANY(editable);
            IF valid IS NOT TRUE THEN
                RAISE EXCEPTION 'Invalid SEM TV column settings %.%', seller, field;
            END IF;
        END LOOP;
    END LOOP;
END
$sem_tv$;

COMMIT;
