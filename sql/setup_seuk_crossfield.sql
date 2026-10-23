-- SEUK Currys: 4개 제품군 × 7개 크로스필드 규칙. savings는 GBP 할인 금액입니다.
-- setup_seuk_layer1.sql 및 setup_seuk_null.sql 실행 후 적용하세요.
-- 원본 수집 데이터를 변경하지 않습니다. 앱 운영 시작일은 2026-10-25입니다.
-- prefix='' 운영, prefix='test_' DEBUG 규칙 설정. 배포 후 웹 프로세스를 재시작하세요.
BEGIN;
DO $seuk_crossfield$
DECLARE
    prefix text := '';
    rules_table text;
    product text;
    definition record;
    source_table text;
    key text;
    affected integer;
BEGIN
    IF prefix NOT IN ('','test_') THEN RAISE EXCEPTION 'Invalid prefix'; END IF;
    rules_table := prefix || 'monitoring_validation_rules';
    EXECUTE format('LOCK TABLE public.%I IN SHARE ROW EXCLUSIVE MODE',rules_table);
    FOREACH product IN ARRAY ARRAY['tv','ref','ldy','ldy_dryer'] LOOP
        key := 'seuk_' || product;
        source_table := 'dx_seuk.dx_seuk_' || product || '_retail_com';
        IF to_regclass(source_table) IS NULL THEN RAISE EXCEPTION 'Missing source table: %',source_table; END IF;
        FOR definition IN SELECT * FROM (VALUES
        ('review_count_match','리뷰 수와 별점 수 일치','count_of_reviews','count_of_star_ratings','리뷰 수와 별점 수가 다릅니다.','count_of_reviews|count_of_star_ratings|star_rating',10),
        ('rating_count_presence','별점과 건수의 0 여부 일치','star_rating','count_of_star_ratings|count_of_reviews','별점과 별점 수 또는 리뷰 수의 0 여부가 다릅니다.','star_rating|count_of_star_ratings|count_of_reviews',20),
        ('final_original_price','판매가와 원가 순서','final_sku_price','original_sku_price','판매가가 원가보다 크거나 같습니다.','final_sku_price|original_sku_price|savings',30),
        ('savings_missing','할인 금액 누락','savings','original_sku_price|final_sku_price','원가가 판매가보다 큰데 할인 금액(savings)이 없습니다.','final_sku_price|original_sku_price|savings',40),
        ('original_missing','원가 누락','original_sku_price','final_sku_price|savings','판매가와 savings가 있는데 원가가 없습니다.','final_sku_price|original_sku_price|savings',50),
        ('final_missing','판매가 누락','final_sku_price','original_sku_price|savings','원가 또는 savings가 있는데 판매가가 없습니다.','final_sku_price|original_sku_price|savings',60),
        ('savings_amount_match','할인 금액 일치','savings','original_sku_price|final_sku_price','원가에서 판매가를 뺀 금액과 할인 금액(savings)이 다릅니다.','final_sku_price|original_sku_price|savings',70)
        ) AS entries(rule_key,detail_name,field1,field2,error_message,select_fields,sort_order) LOOP
            EXECUTE format('UPDATE public.%I SET section_name=$1,detail_name=$2,
                date_column=''crawl_datetime'',product_line=$3,retailer=''Currys'',
                field1=$4,field2=$5,validation_type=$6,check_type=''cross_field'',
                error_message=$7,display_columns=$8,select_fields=$8,query='''',query_detail='''',
                sort_order=$9,is_active=TRUE
                WHERE rule_type=''crossfield'' AND section_code=$10 AND table_name=$11
                  AND detail_code=$12 AND LOWER(BTRIM(retailer))=''currys''',rules_table)
            USING 'SEUK ' || upper(product),definition.detail_name,key,definition.field1,definition.field2,
                definition.rule_key,definition.error_message,definition.select_fields,definition.sort_order,
                key || '_retail',source_table,key || '_' || definition.rule_key;
            GET DIAGNOSTICS affected = ROW_COUNT;
            IF affected > 1 THEN RAISE EXCEPTION 'Duplicate rule: % %',key,definition.rule_key;
            ELSIF affected = 0 THEN
                EXECUTE format('INSERT INTO public.%I
                    (rule_type,section_code,section_name,detail_code,detail_name,table_name,date_column,
                     product_line,retailer,field1,field2,validation_type,check_type,error_message,
                     display_columns,select_fields,query,query_detail,sort_order,is_active,created_at,created_id)
                    VALUES (''crossfield'',$1,$2,$3,$4,$5,''crawl_datetime'',$6,''Currys'',$7,$8,$9,
                            ''cross_field'',$10,$11,$11,'''','''',$12,TRUE,NOW(),''setup_seuk_crossfield'')',rules_table)
                USING key || '_retail','SEUK ' || upper(product),key || '_' || definition.rule_key,
                    definition.detail_name,source_table,key,definition.field1,definition.field2,
                    definition.rule_key,definition.error_message,definition.select_fields,definition.sort_order;
            END IF;
        END LOOP;
    END LOOP;
    RAISE NOTICE 'SEUK cross-field: 28 rules registered in public.%',rules_table;
END
$seuk_crossfield$;
COMMIT;

-- prefix='test_'를 사용했다면 아래 테이블에도 test_를 붙이세요.
SELECT section_code,retailer,COUNT(*) AS active_rules
FROM public.monitoring_validation_rules
WHERE rule_type='crossfield' AND is_active AND LOWER(BTRIM(retailer))='currys'
  AND section_code IN ('seuk_tv_retail','seuk_ref_retail','seuk_ldy_retail','seuk_ldy_dryer_retail')
GROUP BY section_code,retailer ORDER BY section_code;
