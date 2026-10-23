-- 영국 Currys: Layer 1 수집 모니터링 / 컬럼별 수집데이터 통계 등록.
-- 실행 대상: DX PostgreSQL. 운영은 prefix = '', 테스트 설정은 prefix = 'test_'.
-- 코드 배포와 함께 실행 후 웹/통계 작업 프로세스를 재시작하여 스케줄 캐시를 갱신하세요.
-- 최초 수집일 2026-10-23, 매일 당일(D), KST 01:00~04:00.
-- BSR은 5일 관찰 후 별도 결정: 100건 고정 기대값을 등록하지 않습니다.
-- 원본/시험 데이터를 삭제하거나 변경하지 않습니다. NULL/형식/중복/크로스필드 규칙은 등록하지 않습니다.
-- 재실행 가능. 기존 후속 검증 설정의 skip_missing_check/is_editable 값은 보존합니다.
BEGIN;

DO $seuk$
DECLARE
    prefix text := '';  -- 테스트 설정에만 적용할 때 'test_'로 변경
    schedules text;
    columns_table text;
    source record;
    column_name text;
    all_columns text[];
    common_columns text[] := ARRAY[
        'id','batch_id','country','account_name','item','crawl_datetime','calendar_week',
        'sku','retailer_sku_name','product_url','count_of_reviews','star_rating',
        'count_of_star_ratings','final_sku_price','original_sku_price','savings','main_rank','bsr_rank'];
    registered integer;
BEGIN
    IF prefix NOT IN ('', 'test_') THEN
        RAISE EXCEPTION 'prefix must be empty or test_';
    END IF;
    schedules := prefix || 'monitoring_collection_schedule';
    columns_table := prefix || 'monitoring_retail_columns';
    EXECUTE format('LOCK TABLE public.%I, public.%I IN SHARE ROW EXCLUSIVE MODE', schedules, columns_table);

    FOR source IN
        SELECT * FROM (VALUES
            ('tv', 'TV', ARRAY['screen_size']),
            ('ref', 'REF', ARRAY['ref_capacity','ref_refrigerator_type']),
            ('ldy', 'LDY', ARRAY['loading_type','capacity']),
            ('ldy_dryer', 'LDY_DRYER', ARRAY['loading_type','capacity'])
        ) AS entries(product, category, extras)
    LOOP
        all_columns := common_columns || source.extras;
        -- Supplied source contract must exist before any registration is committed.
        SELECT COUNT(*) INTO registered
        FROM information_schema.columns c
        WHERE c.table_schema = 'dx_seuk'
          AND c.table_name = 'dx_seuk_' || source.product || '_retail_com'
          AND c.column_name = ANY(all_columns);
        IF registered <> cardinality(all_columns) THEN
            RAISE EXCEPTION 'SEUK %: source table/columns differ from the supplied schema', source.product;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns c
            WHERE c.table_schema='dx_seuk' AND c.table_name='dx_seuk_' || source.product || '_retail_com'
              AND c.column_name='crawl_datetime' AND c.data_type='text') THEN
            RAISE EXCEPTION 'SEUK %: crawl_datetime must retain original timestamp text', source.product;
        END IF;

        EXECUTE format('UPDATE public.%I SET check_name=$1, check_group=''Retail'',
            schedule_type=''daily'', schedule_value=NULL, us_start_hour=NULL,
            expected_count=0, country=''SEUK'', collection_duration_min=180,
            view_table_name=$2, sort_order=7, description=$3, is_active=TRUE, is_del=0,
            updated_at=NOW(), updated_id=''setup_seuk_layer1''
            WHERE check_type=''seuk_retail'' AND category=$4 AND LOWER(BTRIM(retailer))=''currys''', schedules)
        USING 'SEUK ' || source.category, 'dx_seuk.dx_seuk_' || source.product || '_retail_com',
              '영국 Currys 당일(D) · KST 01:00~04:00 · 최초 2026-10-23 · BSR 5일 관찰 후 기준 결정', source.category;
        GET DIAGNOSTICS registered = ROW_COUNT;
        IF registered > 1 THEN
            RAISE EXCEPTION 'Duplicate SEUK % schedules; transaction rolled back', source.category;
        ELSIF registered = 0 THEN
            EXECUTE format('INSERT INTO public.%I
                (check_group,check_type,check_name,category,schedule_type,retailer,expected_count,country,
                 collection_duration_min,view_table_name,sort_order,description,is_active,is_del,
                 created_at,created_id,updated_at,updated_id)
                VALUES (''Retail'',''seuk_retail'',$1,$2,''daily'',''Currys'',0,''SEUK'',180,$3,7,$4,
                        TRUE,0,NOW(),''setup_seuk_layer1'',NOW(),''setup_seuk_layer1'')', schedules)
            USING 'SEUK ' || source.category, source.category, 'dx_seuk.dx_seuk_' || source.product || '_retail_com',
                  '영국 Currys 당일(D) · KST 01:00~04:00 · 최초 2026-10-23 · BSR 5일 관찰 후 기준 결정';
        END IF;

        FOREACH column_name IN ARRAY all_columns LOOP
            EXECUTE format('UPDATE public.%I SET is_active=TRUE, is_del=FALSE,
                updated_at=NOW(), updated_id=''setup_seuk_layer1''
                WHERE product_line=$1 AND LOWER(BTRIM(retailer))=''currys'' AND column_name=$2', columns_table)
            USING 'seuk_' || source.product, column_name;
            GET DIAGNOSTICS registered = ROW_COUNT;
            IF registered > 1 THEN
                RAISE EXCEPTION 'Duplicate SEUK % column %; transaction rolled back', source.product, column_name;
            ELSIF registered = 0 THEN
                EXECUTE format('INSERT INTO public.%I
                    (product_line,column_name,retailer,duplicate_key,skip_missing_check,is_editable,
                     is_active,is_del,created_at,created_id,updated_at,updated_id)
                    VALUES ($1,$2,''Currys'',FALSE,TRUE,FALSE,TRUE,FALSE,
                            NOW(),''setup_seuk_layer1'',NOW(),''setup_seuk_layer1'')', columns_table)
                USING 'seuk_' || source.product, column_name;
            END IF;
        END LOOP;
    END LOOP;
    RAISE NOTICE 'SEUK Layer 1 registered: 4 schedules / 79 column definitions in public.% and public.%. Source data unchanged.', schedules, columns_table;
END
$seuk$;

COMMIT;

-- 운영 등록 결과 확인. prefix='test_'를 사용했다면 아래 테이블에도 test_를 붙이세요.
SELECT check_type, category, retailer, country, schedule_type, view_table_name, description
FROM public.monitoring_collection_schedule
WHERE check_type='seuk_retail' AND is_active=TRUE AND is_del=0
ORDER BY category;

SELECT product_line, retailer, COUNT(*) AS registered_columns
FROM public.monitoring_retail_columns
WHERE product_line IN ('seuk_tv','seuk_ref','seuk_ldy','seuk_ldy_dryer')
  AND LOWER(BTRIM(retailer))='currys' AND is_active=TRUE AND is_del=FALSE
GROUP BY product_line, retailer ORDER BY product_line;
