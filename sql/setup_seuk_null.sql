-- SEUK Currys NULL 검증: 4개 제품군 × 11개 컬럼.
-- setup_seuk_layer1.sql 실행 후 이 파일 전체를 DX PostgreSQL에서 실행하세요.
-- prefix='' 운영, prefix='test_' 테스트 설정. 원본 수집 데이터는 변경하지 않습니다.
-- 현재 10/23 데이터 미리보기이며, 최종 운영 시작일은 추후 10/25로 복원합니다.
-- 검수 이력은 기존 공통 public.monitoring_null_review_evidence 테이블을 사용합니다.
-- 실행 후 웹 프로세스를 재시작하여 설정 캐시를 갱신하세요.
BEGIN;
DO $seuk_null$
DECLARE
    prefix text := '';
    source record;
    definition record;
    key text;
    required text[];
    common_required text[] := ARRAY['country','account_name','item','sku','retailer_sku_name',
        'product_url','final_sku_price','count_of_reviews','star_rating','count_of_star_ratings'];
    field text;
    display text;
    category_id bigint;
    group_id bigint;
    affected integer;
    category_table text;
    group_table text;
    column_table text;
    retail_table text;
    evidence regclass := to_regclass('public.monitoring_null_review_evidence');
BEGIN
    IF prefix NOT IN ('','test_') THEN RAISE EXCEPTION 'Invalid prefix'; END IF;
    IF evidence IS NULL THEN
        RAISE EXCEPTION 'Run sql/create_null_review_evidence.sql first';
    END IF;
    category_table := prefix || 'monitoring_null_category';
    group_table := prefix || 'monitoring_null_group';
    column_table := prefix || 'monitoring_null_column';
    retail_table := prefix || 'monitoring_retail_columns';
    EXECUTE format('LOCK TABLE public.%I, public.%I, public.%I, public.%I IN SHARE ROW EXCLUSIVE MODE',
                   category_table, group_table, column_table, retail_table);

    FOR source IN SELECT * FROM (VALUES
        ('tv','TV','screen_size',34,19), ('ref','REF','ref_capacity',35,20),
        ('ldy','LDY','capacity',36,20), ('ldy_dryer','LDY_DRYER','capacity',37,20)
    ) AS entries(product,category,extra,sort_order,column_count) LOOP
        key := 'seuk_' || source.product;
        required := common_required || ARRAY[source.extra];
        EXECUTE format('SELECT COUNT(*) FROM public.%I
            WHERE product_line=$1 AND LOWER(BTRIM(retailer))=''currys'' AND is_active AND NOT is_del', retail_table)
        INTO affected USING key;
        IF affected <> source.column_count THEN
            RAISE EXCEPTION '%: run setup_seuk_layer1.sql first (expected % columns)', key, source.column_count;
        END IF;
        EXECUTE format('UPDATE public.%I SET skip_missing_check=NOT (column_name=ANY($2)),
            is_editable=(column_name=ANY($2) OR column_name IN (''original_sku_price'',''savings'')),
            updated_at=NOW(),updated_id=''setup_seuk_null''
            WHERE product_line=$1 AND LOWER(BTRIM(retailer))=''currys'' AND is_active AND NOT is_del', retail_table)
        USING key, required;

        EXECUTE format('UPDATE public.%I SET display_name=$1,display_order=$2,
            has_retailer=TRUE,is_active=TRUE,is_del=FALSE
            WHERE category_name=$3 RETURNING id',category_table)
        INTO category_id USING 'SEUK ' || source.category,source.sort_order,key || '_retail';
        GET DIAGNOSTICS affected = ROW_COUNT;
        IF affected > 1 THEN RAISE EXCEPTION 'Duplicate NULL category: %',key; END IF;
        IF category_id IS NULL THEN
            EXECUTE format('INSERT INTO public.%I
                (category_name,display_name,display_order,has_retailer,is_active,is_del,created_at,created_id)
                VALUES ($1,$2,$3,TRUE,TRUE,FALSE,NOW(),''setup_seuk_null'') RETURNING id',category_table)
            INTO category_id USING key || '_retail','SEUK ' || source.category,source.sort_order;
        END IF;
        EXECUTE format('UPDATE public.%I SET display_name=''Currys'',table_name=$1,date_column=''crawl_datetime'',
            display_order=1,is_active=TRUE,is_del=FALSE,updated_at=NOW(),updated_id=''setup_seuk_null''
            WHERE category_id=$2 AND check_name=$3 RETURNING id',group_table)
        INTO group_id USING 'dx_seuk.dx_seuk_' || source.product || '_retail_com',category_id,'currys_' || key;
        GET DIAGNOSTICS affected = ROW_COUNT;
        IF affected > 1 THEN RAISE EXCEPTION 'Duplicate NULL group: %',key; END IF;
        IF group_id IS NULL THEN
            EXECUTE format('INSERT INTO public.%I
                (category_id,check_name,display_name,table_name,date_column,display_order,is_active,is_del,created_at,created_id)
                VALUES ($1,$2,''Currys'',$3,''crawl_datetime'',1,TRUE,FALSE,NOW(),''setup_seuk_null'') RETURNING id',group_table)
            INTO group_id USING category_id,'currys_' || key,'dx_seuk.dx_seuk_' || source.product || '_retail_com';
        END IF;
        EXECUTE format('UPDATE public.%I SET is_active=FALSE,updated_at=NOW(),updated_id=''setup_seuk_null''
            WHERE group_id=$1 AND NOT (check_column=ANY($2))',column_table) USING group_id,required;
        FOREACH field IN ARRAY required LOOP
            SELECT string_agg(value,'|' ORDER BY first_position) INTO display
            FROM (SELECT value,MIN(position) AS first_position
                FROM unnest(ARRAY['id','crawl_datetime','item','sku','retailer_sku_name',field,
                    'star_rating','count_of_star_ratings','count_of_reviews',
                    'final_sku_price','original_sku_price','savings','product_url']) WITH ORDINALITY AS cols(value,position)
                GROUP BY value) ordered;
            EXECUTE format('UPDATE public.%I SET check_type=''both'',display_columns=$1,query_columns=$1,
                query_days=0,is_active=TRUE,is_del=FALSE,updated_at=NOW(),updated_id=''setup_seuk_null''
                WHERE group_id=$2 AND check_column=$3',column_table) USING display,group_id,field;
            GET DIAGNOSTICS affected = ROW_COUNT;
            IF affected > 1 THEN RAISE EXCEPTION 'Duplicate NULL column: %.%',key,field;
            ELSIF affected = 0 THEN
                EXECUTE format('INSERT INTO public.%I
                    (group_id,check_column,check_type,display_columns,query_columns,query_days,is_active,is_del,created_at,created_id)
                    VALUES ($1,$2,''both'',$3,$3,0,TRUE,FALSE,NOW(),''setup_seuk_null'')',column_table)
                USING group_id,field,display;
            END IF;
        END LOOP;
        EXECUTE format('SELECT COUNT(*) FROM public.%I WHERE group_id=$1 AND is_active AND NOT is_del',column_table)
        INTO affected USING group_id;
        IF affected <> 11 THEN RAISE EXCEPTION '%: expected 11 NULL fields',key; END IF;
    END LOOP;

    -- Preserve existing permitted values and other constraints; only widen the
    -- single-column country/product checks. Re-execution does not nest ORs.
    FOR definition IN
        SELECT c.conname, a.attname, pg_get_expr(c.conbin,c.conrelid) AS expression
        FROM pg_constraint c JOIN pg_attribute a
          ON a.attrelid=c.conrelid AND c.conkey=ARRAY[a.attnum]::smallint[]
        WHERE c.conrelid=evidence AND c.contype='c' AND a.attname IN ('country','product_line')
    LOOP
        IF (definition.attname='country' AND position('SEUK' IN definition.expression)=0)
           OR (definition.attname='product_line' AND position('LDY_DRYER' IN definition.expression)=0) THEN
            EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I',evidence,definition.conname);
            EXECUTE format('ALTER TABLE %s ADD CONSTRAINT %I CHECK ((%s) OR %I=%L)',
                evidence,definition.conname,definition.expression,definition.attname,
                CASE WHEN definition.attname='country' THEN 'SEUK' ELSE 'LDY_DRYER' END);
        END IF;
    END LOOP;
    RAISE NOTICE 'SEUK NULL registration complete: four products, 44 fields. Source data unchanged.';
END
$seuk_null$;
COMMIT;

-- prefix='test_'를 사용했다면 아래 3개 테이블에도 test_를 붙이세요.
SELECT category.category_name, groups.display_name,COUNT(*) AS null_columns
FROM public.monitoring_null_category category
JOIN public.monitoring_null_group groups ON groups.category_id=category.id
JOIN public.monitoring_null_column columns ON columns.group_id=groups.id
WHERE category.category_name IN ('seuk_tv_retail','seuk_ref_retail','seuk_ldy_retail','seuk_ldy_dryer_retail')
  AND category.is_active AND NOT category.is_del AND groups.is_active AND NOT groups.is_del
  AND columns.is_active AND NOT columns.is_del
GROUP BY category.category_name,groups.display_name ORDER BY category.category_name;
