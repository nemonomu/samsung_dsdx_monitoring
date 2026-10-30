-- 운영 PostgreSQL용: SEUK AO REF / LDY / LDY_DRYER 모니터링 등록.
-- 전체 스크립트를 실행합니다. 재실행해도 같은 AO 설정을 갱신합니다.
-- public.monitoring_*만 변경합니다. Currys, 원본 데이터, 형식/크로스필드 규칙은 변경하지 않습니다.
-- feat/ao-monitoring-casas-dday 코드와 함께 적용합니다.
-- 운영 시작 2026-11-01; 시험 데이터는 확인용, 삭제되면 수집 예정으로 표시합니다.
-- AO 수집 시간 KST 01:00~04:00. 제품별 널 검증 11개, 중복 키 item.
-- SEDA Casas Bahia D-DAY(KST 09:00~15:00)는 코드로 적용되므로 별도 SQL이 없습니다.

BEGIN;

DO $registration$
DECLARE
    target record;
    field_name text;
    category_id_value bigint;
    group_id_value bigint;
    matches integer;
    distinct_fields integer;
    required_field boolean;
    editable_field boolean;
    duplicate_field boolean;
    description_value text;
    check_name_value text;
    display_value text;
    source_columns_sql text;
    required_columns text[];
    all_columns text[];
    common_required CONSTANT text[] := ARRAY[
        'country', 'account_name', 'item', 'sku', 'retailer_sku_name',
        'product_url', 'final_sku_price', 'count_of_reviews', 'star_rating',
        'count_of_star_ratings'
    ];
    common_columns CONSTANT text[] := ARRAY[
        'id', 'country', 'account_name', 'item', 'sku', 'retailer_sku_name',
        'product_url', 'count_of_reviews', 'star_rating', 'count_of_star_ratings',
        'final_sku_price', 'original_sku_price', 'savings', 'main_rank',
        'bsr_rank', 'calendar_week', 'crawl_datetime', 'batch_id'
    ];
BEGIN
    FOR target IN
        SELECT * FROM (VALUES
            ('SEUK', 'AO', 'seuk_ref', 'seuk_retail',
             'dx_seuk.dx_seuk_ref_retail_com', 'REF', 'ref_capacity', 'ref_refrigerator_type'),
            ('SEUK', 'AO', 'seuk_ldy', 'seuk_retail',
             'dx_seuk.dx_seuk_ldy_retail_com', 'LDY', 'capacity', 'loading_type'),
            ('SEUK', 'AO', 'seuk_ldy_dryer', 'seuk_retail',
             'dx_seuk.dx_seuk_ldy_dryer_retail_com', 'LDY_DRYER', 'capacity', 'loading_type')
        ) AS targets(country, retailer, product_line, check_type,
                     source_table, product, capacity_column, optional_column)
    LOOP
        required_columns := common_required || ARRAY[target.capacity_column];
        all_columns := common_columns || ARRAY[target.capacity_column, target.optional_column];
        SELECT string_agg(quote_ident(name), ', ' ORDER BY ordinal)
          INTO source_columns_sql
          FROM unnest(all_columns) WITH ORDINALITY AS fields(name, ordinal);

        -- 실제 컬럼 존재 여부만 확인하며 원본 데이터는 수정하지 않습니다.
        EXECUTE format('SELECT %s FROM %I.%I LIMIT 0', source_columns_sql,
                       split_part(target.source_table, '.', 1),
                       split_part(target.source_table, '.', 2));

        description_value := format(
            '%s %s %s; D; KST 01:00~04:00; operating from 2026-11-01; earlier rows are preview only',
            target.country, target.retailer, target.product);

        UPDATE public.monitoring_collection_schedule
           SET check_name = target.country || ' ' || target.product,
               check_group = 'Retail', schedule_type = 'daily', schedule_value = NULL,
               us_start_hour = NULL, expected_count = 0, country = target.country,
               collection_duration_min = 180,
               view_table_name = target.source_table, sort_order = 6,
               description = description_value, is_active = TRUE, is_del = 0,
               updated_at = NOW(), updated_id = 'setup_seuk_ao'
         WHERE check_type = target.check_type AND category = target.product
           AND LOWER(BTRIM(retailer)) = LOWER(target.retailer);

        IF NOT FOUND THEN
            INSERT INTO public.monitoring_collection_schedule (
                check_group, check_type, check_name, category, schedule_type,
                retailer, expected_count, country, collection_duration_min,
                view_table_name, sort_order, description, is_active, is_del,
                created_at, created_id, updated_at, updated_id
            ) VALUES (
                'Retail', target.check_type, target.country || ' ' || target.product,
                target.product, 'daily', target.retailer, 0, target.country,
                180, target.source_table, 6, description_value,
                TRUE, 0, NOW(), 'setup_seuk_ao', NOW(), 'setup_seuk_ao'
            );
        END IF;

        FOREACH field_name IN ARRAY all_columns LOOP
            required_field := field_name = ANY(required_columns);
            editable_field := required_field OR field_name IN ('original_sku_price', 'savings');
            duplicate_field := field_name = 'item';

            UPDATE public.monitoring_retail_columns
               SET duplicate_key = duplicate_field, skip_missing_check = NOT required_field,
                   is_editable = editable_field, is_active = TRUE, is_del = FALSE,
                   updated_at = NOW(), updated_id = 'setup_seuk_ao'
             WHERE product_line = target.product_line
               AND LOWER(BTRIM(retailer)) = LOWER(target.retailer)
               AND column_name = field_name;

            IF NOT FOUND THEN
                INSERT INTO public.monitoring_retail_columns (
                    product_line, column_name, retailer, duplicate_key,
                    skip_missing_check, is_editable, is_active, is_del,
                    created_at, created_id, updated_at, updated_id
                ) VALUES (
                    target.product_line, field_name, target.retailer, duplicate_field,
                    NOT required_field, editable_field, TRUE, FALSE,
                    NOW(), 'setup_seuk_ao', NOW(), 'setup_seuk_ao'
                );
            END IF;
        END LOOP;

        -- 기존 업체도 사용하는 카테고리의 표시 설정은 덮어쓰지 않습니다.
        SELECT COUNT(*), MIN(id) INTO matches, category_id_value
          FROM public.monitoring_null_category
         WHERE category_name = target.product_line || '_retail';
        IF matches > 1 THEN
            RAISE EXCEPTION 'Duplicate NULL category for %', target.product_line;
        ELSIF matches = 0 THEN
            INSERT INTO public.monitoring_null_category (
                category_name, display_name, display_order, has_retailer,
                is_active, is_del, created_at, created_id
            ) VALUES (
                target.product_line || '_retail', target.country || ' ' || target.product,
                40, TRUE, TRUE, FALSE, NOW(), 'setup_seuk_ao'
            ) RETURNING id INTO category_id_value;
        END IF;

        check_name_value := LOWER(target.retailer) || '_' || target.product_line;
        UPDATE public.monitoring_null_group
           SET display_name = target.retailer, table_name = target.source_table,
               date_column = 'crawl_datetime', display_order = 3,
               is_active = TRUE, is_del = FALSE,
               updated_at = NOW(), updated_id = 'setup_seuk_ao'
         WHERE category_id = category_id_value AND check_name = check_name_value
         RETURNING id INTO group_id_value;

        IF NOT FOUND THEN
            INSERT INTO public.monitoring_null_group (
                category_id, check_name, display_name, table_name, date_column,
                display_order, is_active, is_del, created_at, created_id
            ) VALUES (
                category_id_value, check_name_value, target.retailer, target.source_table,
                'crawl_datetime', 3, TRUE, FALSE, NOW(), 'setup_seuk_ao'
            ) RETURNING id INTO group_id_value;
        END IF;

        UPDATE public.monitoring_null_column
           SET is_active = FALSE, updated_at = NOW(), updated_id = 'setup_seuk_ao'
         WHERE group_id = group_id_value AND NOT (check_column = ANY(required_columns));

        FOREACH field_name IN ARRAY required_columns LOOP
            SELECT array_to_string(ARRAY(
                SELECT name
                  FROM unnest(ARRAY[
                      'id', 'crawl_datetime', 'item', 'sku', 'retailer_sku_name', field_name,
                      'star_rating', 'count_of_star_ratings', 'count_of_reviews',
                      'final_sku_price', 'original_sku_price', 'savings', 'product_url'
                  ]) WITH ORDINALITY AS fields(name, ordinal)
                 GROUP BY name ORDER BY MIN(ordinal)
            ), '|') INTO display_value;

            UPDATE public.monitoring_null_column
               SET check_type = 'both', display_columns = display_value,
                   query_columns = display_value, query_days = 0,
                   is_active = TRUE, is_del = FALSE,
                   updated_at = NOW(), updated_id = 'setup_seuk_ao'
             WHERE group_id = group_id_value AND check_column = field_name;

            IF NOT FOUND THEN
                INSERT INTO public.monitoring_null_column (
                    group_id, check_column, check_type, display_columns, query_columns,
                    query_days, is_active, is_del, created_at, created_id
                ) VALUES (
                    group_id_value, field_name, 'both', display_value, display_value,
                    0, TRUE, FALSE, NOW(), 'setup_seuk_ao'
                );
            END IF;
        END LOOP;

        SELECT COUNT(*), COUNT(DISTINCT check_column) INTO matches, distinct_fields
          FROM public.monitoring_null_column
         WHERE group_id = group_id_value AND is_active AND NOT is_del;
        IF matches <> 11 OR distinct_fields <> 11 THEN
            RAISE EXCEPTION '% %: expected 11 unique NULL checks; got % rows / % fields',
                target.country, target.retailer, matches, distinct_fields;
        END IF;
    END LOOP;
END;
$registration$;

-- 정상 실행 시 아래 세 행이 각각 11을 반환합니다.
SELECT category.category_name, null_group.display_name AS retailer,
       COUNT(*) AS active_null_columns
  FROM public.monitoring_null_category category
  JOIN public.monitoring_null_group null_group ON null_group.category_id = category.id
  JOIN public.monitoring_null_column checks ON checks.group_id = null_group.id
 WHERE (category.category_name, null_group.check_name) IN (
           ('seuk_ref_retail', 'ao_seuk_ref'),
           ('seuk_ldy_retail', 'ao_seuk_ldy'),
           ('seuk_ldy_dryer_retail', 'ao_seuk_ldy_dryer')
       )
   AND checks.is_active AND NOT checks.is_del
 GROUP BY category.category_name, null_group.display_name
 ORDER BY category.category_name;

COMMIT;
