-- SEUK TV Amazon 5개, Argos 7개 크로스필드 규칙을 등록합니다.
-- 운영은 prefix='', 테스트는 prefix='test_'를 사용합니다.
-- 기존 Currys·AO 규칙과 원본 수집 데이터는 유지합니다.
-- DBeaver의 입력값 팝업을 피하기 위해 동적 SQL의 값은 format의 %L로 전달합니다.
BEGIN;

DO $seuk_tv_crossfield$
DECLARE
    prefix text := '';
    rules_table text;
    source_table CONSTANT text := 'dx_seuk.dx_seuk_tv_retail_com';
    section CONSTANT text := 'seuk_tv_retail';
    price_fields CONSTANT text := 'final_sku_price|original_sku_price|savings';
    definition record;
    detail_key text;
    affected integer;
BEGIN
    IF prefix NOT IN ('', 'test_') THEN RAISE EXCEPTION 'Invalid prefix'; END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='dx_seuk' AND table_name='dx_seuk_tv_retail_com'
          AND column_name='is_redirect' AND data_type='boolean'
    ) THEN
        RAISE EXCEPTION 'SEUK TV requires is_redirect boolean';
    END IF;

    rules_table := prefix || 'monitoring_validation_rules';
    EXECUTE format('LOCK TABLE public.%I IN SHARE ROW EXCLUSIVE MODE', rules_table);

    FOR definition IN SELECT * FROM (VALUES
        ('Amazon', 'rating_count_presence', '별점과 별점 수 일치', 'star_rating', 'count_of_star_ratings',
            '숫자 별점이 있는데 별점 수가 없거나 0이거나, 별점 없음 문구와 양수 별점 수가 함께 있습니다.',
            'star_rating|count_of_star_ratings', 110),
        ('Amazon', 'final_original_price', '판매가와 원가 순서', 'final_sku_price', 'original_sku_price',
            '판매가가 원가보다 크거나 같거나 할인율이 90% 이상입니다.', price_fields, 120),
        ('Amazon', 'savings_missing', '할인값 누락', 'savings', 'original_sku_price|final_sku_price',
            '할인율이 0.5% 이상인데 할인값(savings)이 없습니다.', price_fields, 130),
        ('Amazon', 'original_missing', '원가 누락', 'original_sku_price', 'final_sku_price|savings',
            '판매가와 savings가 있는데 원가가 없습니다.', price_fields, 140),
        ('Amazon', 'final_missing', '판매가 누락', 'final_sku_price', 'original_sku_price|savings',
            '원가 또는 savings가 있는데 판매가가 없습니다.', price_fields, 150),
        ('Argos', 'review_count_match', '리뷰 수와 별점 수 일치', 'count_of_reviews', 'count_of_star_ratings',
            '리뷰 수와 별점 수가 다릅니다.', 'count_of_reviews|count_of_star_ratings|star_rating', 210),
        ('Argos', 'rating_count_presence', '별점과 건수의 0 여부 일치', 'star_rating',
            'count_of_star_ratings|count_of_reviews', '별점과 별점 수 또는 리뷰 수의 0 여부가 다릅니다.',
            'star_rating|count_of_star_ratings|count_of_reviews', 220),
        ('Argos', 'final_original_price', '판매가와 원가 순서', 'final_sku_price', 'original_sku_price',
            '판매가가 원가보다 크거나 같습니다.', price_fields, 230),
        ('Argos', 'savings_missing', '할인값 누락', 'savings', 'original_sku_price|final_sku_price',
            '원가가 판매가보다 큰데 할인값(savings)이 없습니다.', price_fields, 240),
        ('Argos', 'original_missing', '원가 누락', 'original_sku_price', 'final_sku_price|savings',
            '판매가와 savings가 있는데 원가가 없습니다.', price_fields, 250),
        ('Argos', 'final_missing', '판매가 누락', 'final_sku_price', 'original_sku_price|savings',
            '원가 또는 savings가 있는데 판매가가 없습니다.', price_fields, 260),
        ('Argos', 'savings_amount_match', '할인값 일치', 'savings', 'original_sku_price|final_sku_price',
            '£ 금액은 원가와 판매가의 차액, %는 정수로 반올림한 할인율과 일치해야 합니다.', price_fields, 270)
    ) AS entries(retailer, rule_key, detail_name, field1, field2, error_message, select_fields, sort_order)
    LOOP
        detail_key := 'seuk_tv_' || lower(definition.retailer) || '_' || definition.rule_key;
        EXECUTE format($statement$
            UPDATE public.%I
            SET section_name='SEUK TV', product_line='seuk_tv', date_column='crawl_datetime',
                detail_name=%L, field1=%L, field2=%L, validation_type=%L, check_type='cross_field',
                error_message=%L, display_columns=%L, select_fields=%L, query='', query_detail='',
                sort_order=%L, is_active=TRUE
            WHERE rule_type='crossfield' AND section_code=%L AND table_name=%L
              AND detail_code=%L AND LOWER(BTRIM(retailer))=lower(%L)
        $statement$, rules_table, definition.detail_name, definition.field1, definition.field2,
            definition.rule_key, definition.error_message, definition.select_fields, definition.select_fields,
            definition.sort_order, section, source_table, detail_key, definition.retailer);
        GET DIAGNOSTICS affected = ROW_COUNT;
        IF affected > 1 THEN
            RAISE EXCEPTION 'Duplicate SEUK TV cross-field rule: %', detail_key;
        ELSIF affected = 0 THEN
            EXECUTE format($statement$
                INSERT INTO public.%I
                    (rule_type, section_code, section_name, detail_code, detail_name, table_name, date_column,
                     product_line, retailer, field1, field2, validation_type, check_type, error_message,
                     display_columns, select_fields, query, query_detail, sort_order, is_active, created_at, created_id)
                VALUES ('crossfield', %L, 'SEUK TV', %L, %L, %L, 'crawl_datetime', 'seuk_tv', %L,
                        %L, %L, %L, 'cross_field', %L, %L, %L, '', '', %L, TRUE, NOW(), 'setup_seuk_tv_crossfield')
            $statement$, rules_table, section, detail_key, definition.detail_name, source_table,
                definition.retailer, definition.field1, definition.field2, definition.rule_key,
                definition.error_message, definition.select_fields, definition.select_fields, definition.sort_order);
        END IF;
    END LOOP;
    RAISE NOTICE 'SEUK TV cross-field: 12 rules registered in public.%', rules_table;
END
$seuk_tv_crossfield$;

COMMIT;
