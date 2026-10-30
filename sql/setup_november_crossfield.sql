-- 신규 크로스필드: OTTO 건조기 6 / Liverpool 건조기 4 / ECI 건조기 4 / AO REF·LDY·LDY_DRYER 각 7.
-- feat/dryer-otto-liverpool-eci-monitoring 최신 코드를 배포한 뒤 전체 실행합니다.
-- prefix=''는 운영, 'test_'는 개발 설정입니다. 원본 데이터와 기존 업체 규칙은 변경하지 않습니다.
-- 수집일: DB 원본 날짜, 업체별 최신 배치. 11/1 이전 데이터도 검수 확인용으로 조회합니다.
-- ECI의 조건·표시·수정 컬럼에 savings를 포함하지 않습니다.
BEGIN;
DO $november_crossfield$
DECLARE
    prefix text := '';
    rules_table text;
    target record;
    code text;
    affected integer;
BEGIN
    IF prefix NOT IN ('', 'test_') THEN RAISE EXCEPTION 'Invalid prefix'; END IF;
    rules_table := prefix || 'monitoring_validation_rules';
    EXECUTE format('LOCK TABLE public.%I IN SHARE ROW EXCLUSIVE MODE', rules_table);
    FOR target IN SELECT * FROM (VALUES
        ('seg_ldy_dryer', 'SEG LDY_DRYER', 'dx_seg.dx_seg_ldy_dryer_retail', 'OTTO', 'review_count_match', '리뷰 수와 별점 수 일치', 'count_of_reviews', 'count_of_star_ratings', 'count_of_reviews와 count_of_star_ratings가 다릅니다.', 'count_of_reviews|count_of_star_ratings|star_rating', 10),
        ('seg_ldy_dryer', 'SEG LDY_DRYER', 'dx_seg.dx_seg_ldy_dryer_retail', 'OTTO', 'rating_count_presence', '별점과 별점 수 존재 일치', 'star_rating', 'count_of_star_ratings', '별점과 별점 수의 0값 관계 불일치. Mediamarkt·OTTO는 리뷰 수도 비교합니다.', 'star_rating|count_of_star_ratings|count_of_reviews', 20),
        ('seg_ldy_dryer', 'SEG LDY_DRYER', 'dx_seg.dx_seg_ldy_dryer_retail', 'OTTO', 'final_original_price', '최종가와 원가 순서', 'final_sku_price', 'original_sku_price', 'final_sku_price가 original_sku_price보다 크거나 같습니다.', 'final_sku_price|original_sku_price|savings', 30),
        ('seg_ldy_dryer', 'SEG LDY_DRYER', 'dx_seg.dx_seg_ldy_dryer_retail', 'OTTO', 'savings_missing', '할인 가격 존재 시 savings 확인', 'savings', 'final_sku_price|original_sku_price', '할인 가격인데 savings가 없습니다. Amazon은 계산 할인율 0.5% 이상, Mediamarkt는 10% 초과일 때 검사합니다.', 'final_sku_price|original_sku_price|savings', 40),
        ('seg_ldy_dryer', 'SEG LDY_DRYER', 'dx_seg.dx_seg_ldy_dryer_retail', 'OTTO', 'original_missing', '판매가·savings 존재 시 원가 확인', 'original_sku_price', 'final_sku_price|savings', '판매가와 savings가 있는데 original_sku_price가 NULL 또는 빈값입니다.', 'final_sku_price|original_sku_price|savings', 50),
        ('seg_ldy_dryer', 'SEG LDY_DRYER', 'dx_seg.dx_seg_ldy_dryer_retail', 'OTTO', 'final_missing', '원가·savings 존재 시 판매가 확인', 'final_sku_price', 'original_sku_price|savings', '원가 또는 savings가 있는데 final_sku_price가 NULL 또는 빈값입니다.', 'final_sku_price|original_sku_price|savings', 60),
        ('sem_ldy_dryer', 'SEM LDY_DRYER', 'dx_sem.dx_sem_ldy_dryer_retail_com', 'Liverpool', 'rating_count_consistency', '평점과 평가 수 일치', 'star_rating', 'count_of_star_ratings', '평점과 평가 수 또는 리뷰 수의 0 여부가 다르거나 평점과 리뷰 수의 존재 여부가 다릅니다.', 'star_rating|count_of_star_ratings|count_of_reviews', 10),
        ('sem_ldy_dryer', 'SEM LDY_DRYER', 'dx_sem.dx_sem_ldy_dryer_retail_com', 'Liverpool', 'review_rating_count', '리뷰 수와 평가 수 일치', 'count_of_reviews', 'count_of_star_ratings', '리뷰 수와 평가 수가 일치하지 않습니다.', 'star_rating|count_of_star_ratings|count_of_reviews', 20),
        ('sem_ldy_dryer', 'SEM LDY_DRYER', 'dx_sem.dx_sem_ldy_dryer_retail_com', 'Liverpool', 'final_original_price', '최종가와 원가 순서', 'final_sku_price', 'original_sku_price', '두 가격이 숫자이고 원가가 0이 아닐 때 최종 판매가가 원가보다 크거나 같으면 이상입니다.', 'final_sku_price|original_sku_price', 30),
        ('sem_ldy_dryer', 'SEM LDY_DRYER', 'dx_sem.dx_sem_ldy_dryer_retail_com', 'Liverpool', 'original_price_zero', '원가 0 검사', 'original_sku_price', NULL, 'original_sku_price가 0입니다.', 'original_sku_price', 40),
        ('seib_ldy_dryer', 'SEIB LDY_DRYER', 'dx_seib.dx_seib_ldy_dryer_retail_com', 'ECI', 'review_count_match', '리뷰 수와 별점 수 일치', 'count_of_reviews', 'count_of_star_ratings', '리뷰 수와 별점 수가 다릅니다.', 'count_of_reviews|count_of_star_ratings|star_rating', 10),
        ('seib_ldy_dryer', 'SEIB LDY_DRYER', 'dx_seib.dx_seib_ldy_dryer_retail_com', 'ECI', 'rating_count_presence', '별점과 건수의 0 여부 일치', 'star_rating', 'count_of_star_ratings|count_of_reviews', '별점과 별점 수 또는 리뷰 수의 0 여부가 다릅니다.', 'star_rating|count_of_star_ratings|count_of_reviews', 20),
        ('seib_ldy_dryer', 'SEIB LDY_DRYER', 'dx_seib.dx_seib_ldy_dryer_retail_com', 'ECI', 'final_original_price', '판매가와 원가 순서', 'final_sku_price', 'original_sku_price', '판매가가 원가보다 크거나 같습니다.', 'final_sku_price|original_sku_price', 30),
        ('seib_ldy_dryer', 'SEIB LDY_DRYER', 'dx_seib.dx_seib_ldy_dryer_retail_com', 'ECI', 'final_missing', '판매가 누락', 'final_sku_price', 'original_sku_price', '원가가 있는데 판매가가 없습니다.', 'final_sku_price|original_sku_price', 40),
        ('seuk_ref', 'SEUK REF', 'dx_seuk.dx_seuk_ref_retail_com', 'AO', 'review_count_match', '리뷰 수와 별점 수 일치', 'count_of_reviews', 'count_of_star_ratings', '리뷰 수와 별점 수가 다릅니다.', 'count_of_reviews|count_of_star_ratings|star_rating', 10),
        ('seuk_ref', 'SEUK REF', 'dx_seuk.dx_seuk_ref_retail_com', 'AO', 'rating_count_presence', '별점과 건수의 0 여부 일치', 'star_rating', 'count_of_star_ratings|count_of_reviews', '별점과 별점 수 또는 리뷰 수의 0 여부가 다릅니다.', 'star_rating|count_of_star_ratings|count_of_reviews', 20),
        ('seuk_ref', 'SEUK REF', 'dx_seuk.dx_seuk_ref_retail_com', 'AO', 'final_original_price', '판매가와 원가 순서', 'final_sku_price', 'original_sku_price', '판매가가 원가보다 크거나 같습니다.', 'final_sku_price|original_sku_price|savings', 30),
        ('seuk_ref', 'SEUK REF', 'dx_seuk.dx_seuk_ref_retail_com', 'AO', 'savings_missing', '할인 금액 누락', 'savings', 'original_sku_price|final_sku_price', '원가가 판매가보다 큰데 할인 금액(savings)이 없습니다.', 'final_sku_price|original_sku_price|savings', 40),
        ('seuk_ref', 'SEUK REF', 'dx_seuk.dx_seuk_ref_retail_com', 'AO', 'original_missing', '원가 누락', 'original_sku_price', 'final_sku_price|savings', '판매가와 savings가 있는데 원가가 없습니다.', 'final_sku_price|original_sku_price|savings', 50),
        ('seuk_ref', 'SEUK REF', 'dx_seuk.dx_seuk_ref_retail_com', 'AO', 'final_missing', '판매가 누락', 'final_sku_price', 'original_sku_price|savings', '원가 또는 savings가 있는데 판매가가 없습니다.', 'final_sku_price|original_sku_price|savings', 60),
        ('seuk_ref', 'SEUK REF', 'dx_seuk.dx_seuk_ref_retail_com', 'AO', 'savings_amount_match', '할인 금액 일치', 'savings', 'original_sku_price|final_sku_price', '원가에서 판매가를 뺀 금액과 할인 금액(savings)이 다릅니다.', 'final_sku_price|original_sku_price|savings', 70),
        ('seuk_ldy', 'SEUK LDY', 'dx_seuk.dx_seuk_ldy_retail_com', 'AO', 'review_count_match', '리뷰 수와 별점 수 일치', 'count_of_reviews', 'count_of_star_ratings', '리뷰 수와 별점 수가 다릅니다.', 'count_of_reviews|count_of_star_ratings|star_rating', 10),
        ('seuk_ldy', 'SEUK LDY', 'dx_seuk.dx_seuk_ldy_retail_com', 'AO', 'rating_count_presence', '별점과 건수의 0 여부 일치', 'star_rating', 'count_of_star_ratings|count_of_reviews', '별점과 별점 수 또는 리뷰 수의 0 여부가 다릅니다.', 'star_rating|count_of_star_ratings|count_of_reviews', 20),
        ('seuk_ldy', 'SEUK LDY', 'dx_seuk.dx_seuk_ldy_retail_com', 'AO', 'final_original_price', '판매가와 원가 순서', 'final_sku_price', 'original_sku_price', '판매가가 원가보다 크거나 같습니다.', 'final_sku_price|original_sku_price|savings', 30),
        ('seuk_ldy', 'SEUK LDY', 'dx_seuk.dx_seuk_ldy_retail_com', 'AO', 'savings_missing', '할인 금액 누락', 'savings', 'original_sku_price|final_sku_price', '원가가 판매가보다 큰데 할인 금액(savings)이 없습니다.', 'final_sku_price|original_sku_price|savings', 40),
        ('seuk_ldy', 'SEUK LDY', 'dx_seuk.dx_seuk_ldy_retail_com', 'AO', 'original_missing', '원가 누락', 'original_sku_price', 'final_sku_price|savings', '판매가와 savings가 있는데 원가가 없습니다.', 'final_sku_price|original_sku_price|savings', 50),
        ('seuk_ldy', 'SEUK LDY', 'dx_seuk.dx_seuk_ldy_retail_com', 'AO', 'final_missing', '판매가 누락', 'final_sku_price', 'original_sku_price|savings', '원가 또는 savings가 있는데 판매가가 없습니다.', 'final_sku_price|original_sku_price|savings', 60),
        ('seuk_ldy', 'SEUK LDY', 'dx_seuk.dx_seuk_ldy_retail_com', 'AO', 'savings_amount_match', '할인 금액 일치', 'savings', 'original_sku_price|final_sku_price', '원가에서 판매가를 뺀 금액과 할인 금액(savings)이 다릅니다.', 'final_sku_price|original_sku_price|savings', 70),
        ('seuk_ldy_dryer', 'SEUK LDY_DRYER', 'dx_seuk.dx_seuk_ldy_dryer_retail_com', 'AO', 'review_count_match', '리뷰 수와 별점 수 일치', 'count_of_reviews', 'count_of_star_ratings', '리뷰 수와 별점 수가 다릅니다.', 'count_of_reviews|count_of_star_ratings|star_rating', 10),
        ('seuk_ldy_dryer', 'SEUK LDY_DRYER', 'dx_seuk.dx_seuk_ldy_dryer_retail_com', 'AO', 'rating_count_presence', '별점과 건수의 0 여부 일치', 'star_rating', 'count_of_star_ratings|count_of_reviews', '별점과 별점 수 또는 리뷰 수의 0 여부가 다릅니다.', 'star_rating|count_of_star_ratings|count_of_reviews', 20),
        ('seuk_ldy_dryer', 'SEUK LDY_DRYER', 'dx_seuk.dx_seuk_ldy_dryer_retail_com', 'AO', 'final_original_price', '판매가와 원가 순서', 'final_sku_price', 'original_sku_price', '판매가가 원가보다 크거나 같습니다.', 'final_sku_price|original_sku_price|savings', 30),
        ('seuk_ldy_dryer', 'SEUK LDY_DRYER', 'dx_seuk.dx_seuk_ldy_dryer_retail_com', 'AO', 'savings_missing', '할인 금액 누락', 'savings', 'original_sku_price|final_sku_price', '원가가 판매가보다 큰데 할인 금액(savings)이 없습니다.', 'final_sku_price|original_sku_price|savings', 40),
        ('seuk_ldy_dryer', 'SEUK LDY_DRYER', 'dx_seuk.dx_seuk_ldy_dryer_retail_com', 'AO', 'original_missing', '원가 누락', 'original_sku_price', 'final_sku_price|savings', '판매가와 savings가 있는데 원가가 없습니다.', 'final_sku_price|original_sku_price|savings', 50),
        ('seuk_ldy_dryer', 'SEUK LDY_DRYER', 'dx_seuk.dx_seuk_ldy_dryer_retail_com', 'AO', 'final_missing', '판매가 누락', 'final_sku_price', 'original_sku_price|savings', '원가 또는 savings가 있는데 판매가가 없습니다.', 'final_sku_price|original_sku_price|savings', 60),
        ('seuk_ldy_dryer', 'SEUK LDY_DRYER', 'dx_seuk.dx_seuk_ldy_dryer_retail_com', 'AO', 'savings_amount_match', '할인 금액 일치', 'savings', 'original_sku_price|final_sku_price', '원가에서 판매가를 뺀 금액과 할인 금액(savings)이 다릅니다.', 'final_sku_price|original_sku_price|savings', 70)
    ) AS definitions(product_line, section_name, source_table, retailer, rule_key,
                     detail_name, field1, field2, error_message, fields, sort_order)
    LOOP
        code := target.product_line || '_' || lower(target.retailer) || '_' || target.rule_key;
        -- 실제 원본 컬럼의 존재 여부만 확인합니다.
        EXECUTE format('SELECT %s FROM %I.%I LIMIT 0',
            (SELECT string_agg(quote_ident(field), ', ') FROM unnest(string_to_array(target.fields, '|')) field),
            split_part(target.source_table, '.', 1), split_part(target.source_table, '.', 2));
        EXECUTE format('UPDATE public.%I SET section_name=$1, detail_name=$2,
            date_column=''crawl_datetime'', product_line=$3, retailer=$4,
            field1=$5, field2=$6, validation_type=$7, check_type=''cross_field'',
            error_message=$8, display_columns=$9, select_fields=$9,
            query='''', query_detail='''', sort_order=$10, is_active=TRUE
            WHERE rule_type=''crossfield'' AND section_code=$11 AND table_name=$12
              AND detail_code=$13 AND LOWER(BTRIM(retailer))=LOWER($4)', rules_table)
        USING target.section_name, target.detail_name, target.product_line, target.retailer,
              target.field1, target.field2, target.rule_key, target.error_message,
              target.fields, target.sort_order, target.product_line || '_retail', target.source_table, code;
        GET DIAGNOSTICS affected = ROW_COUNT;
        IF affected > 1 THEN RAISE EXCEPTION 'Duplicate rule: %', code;
        ELSIF affected = 0 THEN
            EXECUTE format('INSERT INTO public.%I
                (rule_type,section_code,section_name,detail_code,detail_name,table_name,date_column,
                 product_line,retailer,field1,field2,validation_type,check_type,error_message,
                 display_columns,select_fields,query,query_detail,sort_order,is_active,created_at,created_id)
                VALUES (''crossfield'',$1,$2,$3,$4,$5,''crawl_datetime'',$6,$7,$8,$9,$10,
                        ''cross_field'',$11,$12,$12,'''','''',$13,TRUE,NOW(),''setup_november_crossfield'')',rules_table)
            USING target.product_line || '_retail', target.section_name, code, target.detail_name,
                  target.source_table, target.product_line, target.retailer, target.field1, target.field2,
                  target.rule_key, target.error_message, target.fields, target.sort_order;
        END IF;
    END LOOP;
    FOR target IN SELECT * FROM (VALUES
        ('seg_ldy_dryer_retail', 'OTTO', 6), ('sem_ldy_dryer_retail', 'Liverpool', 4),
        ('seib_ldy_dryer_retail', 'ECI', 4), ('seuk_ref_retail', 'AO', 7),
        ('seuk_ldy_retail', 'AO', 7), ('seuk_ldy_dryer_retail', 'AO', 7)
    ) AS expected(section_code, retailer, rule_count) LOOP
        EXECUTE format('SELECT COUNT(*) FROM public.%I WHERE rule_type=''crossfield''
            AND is_active AND section_code=$1 AND LOWER(BTRIM(retailer))=LOWER($2)',rules_table)
        INTO affected USING target.section_code,target.retailer;
        IF affected <> target.rule_count THEN
            RAISE EXCEPTION '% %: expected % active rules, found %',
                target.section_code,target.retailer,target.rule_count,affected;
        END IF;
        RAISE NOTICE '% / % / % rules',target.section_code,target.retailer,affected;
    END LOOP;
END;
$november_crossfield$;
COMMIT;
