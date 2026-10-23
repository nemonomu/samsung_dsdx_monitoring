-- SEUK Currys Layer 2 중복 키 및 수정 가능한 컬럼 메타데이터.
-- setup_seuk_layer1.sql / setup_seuk_null.sql 실행 후 적용하세요.
-- 형식 규칙 38개(TV 8, REF/LDY/LDY_DRYER 각 10)는 코드에서 관리합니다.
-- 제외 컬럼: item, product_url, crawl_datetime, calendar_week, main_rank,
-- bsr_rank, screen_size. 기존 NULL 검증 컬럼/수정 권한은 유지합니다.
-- 원본 데이터, 수집 시작일 및 검수 이력은 변경하지 않습니다.
BEGIN;
DO $seuk_format_duplicate$
DECLARE
    prefix text := ''; -- 운영 ''. 테스트는 'test_'.
    metadata_table text;
    source record;
    registered integer;
    editable text[];
BEGIN
    IF prefix NOT IN ('', 'test_') THEN RAISE EXCEPTION 'Invalid prefix'; END IF;
    metadata_table := prefix || 'monitoring_retail_columns';
    EXECUTE format('LOCK TABLE public.%I IN SHARE ROW EXCLUSIVE MODE', metadata_table);
    FOR source IN SELECT * FROM (VALUES
        ('tv',19,'screen_size'),('ref',20,'ref_capacity'),
        ('ldy',20,'capacity'),('ldy_dryer',20,'capacity')
    ) AS entries(product, column_count, required_extra) LOOP
        IF to_regclass('dx_seuk.dx_seuk_' || source.product || '_retail_com') IS NULL THEN
            RAISE EXCEPTION 'Missing SEUK source: %', source.product;
        END IF;
        EXECUTE format('SELECT COUNT(DISTINCT column_name) FROM public.%I
            WHERE product_line=$1 AND LOWER(BTRIM(retailer))=''currys'' AND is_active AND NOT is_del', metadata_table)
        INTO registered USING 'seuk_' || source.product;
        IF registered <> source.column_count THEN
            RAISE EXCEPTION 'Run setup_seuk_layer1.sql first: %', source.product;
        END IF;
        editable := ARRAY['country','account_name','item','sku','retailer_sku_name',
            'product_url','final_sku_price','original_sku_price','savings',
            'count_of_reviews','count_of_star_ratings','star_rating',source.required_extra];
        IF source.product='ref' THEN
            editable := editable || ARRAY['ref_refrigerator_type'];
        ELSIF source.product IN ('ldy','ldy_dryer') THEN
            editable := editable || ARRAY['loading_type'];
        END IF;
        EXECUTE format('UPDATE public.%I SET duplicate_key=(column_name=''item''),
            is_editable=(column_name=ANY($2)), updated_at=NOW(),updated_id=''setup_seuk_format_duplicate''
            WHERE product_line=$1 AND LOWER(BTRIM(retailer))=''currys'' AND is_active AND NOT is_del', metadata_table)
        USING 'seuk_' || source.product, editable;
    END LOOP;
END
$seuk_format_duplicate$;
COMMIT;

-- 테스트 설정은 아래 테이블에도 test_를 붙이세요.
SELECT product_line, column_name, duplicate_key, is_editable, skip_missing_check
FROM public.monitoring_retail_columns
WHERE product_line IN ('seuk_tv','seuk_ref','seuk_ldy','seuk_ldy_dryer')
  AND LOWER(BTRIM(retailer))='currys' AND is_active AND NOT is_del
ORDER BY product_line, column_name;
