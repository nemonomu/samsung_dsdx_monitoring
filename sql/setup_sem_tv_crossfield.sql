-- Register stable correction-history IDs for the SEM TV rules.
-- Set prefix to 'test_' when preparing the test rule registry.
DO $sem_tv_crossfield$
DECLARE
    prefix CONSTANT text := '';
    rules_table CONSTANT text := prefix || 'monitoring_validation_rules';
    source_table CONSTANT text := 'dx_sem.dx_sem_tv_retail_com';
    section CONSTANT text := 'sem_tv_retail';
    rule record;
    affected integer;
BEGIN
    IF prefix NOT IN ('', 'test_') THEN RAISE EXCEPTION 'Invalid prefix'; END IF;
    EXECUTE format('LOCK TABLE public.%I IN SHARE ROW EXCLUSIVE MODE', rules_table);
    FOR rule IN SELECT * FROM (VALUES
        ('mx_tv_savings_amount_match', '할인금액 일치', 'savings', 'original_sku_price', 'all', 110),
        ('mx_tv_price_order', '가격 순서·할인율 확인', 'final_sku_price', 'original_sku_price', 'all', 120),
        ('mx_tv_final_missing', '할인 정보가 있는데 최종가 누락', 'final_sku_price', 'original_sku_price', 'all', 130),
        ('mx_tv_original_missing', '절감액이 있는데 할인 전 가격 누락', 'original_sku_price', 'savings', 'all', 140),
        ('mx_tv_savings_missing', '할인 가격이 있는데 절감액 누락', 'savings', 'original_sku_price', 'all', 150),
        ('mx_tv_rating_count', '별점과 평가 수의 0 여부', 'star_rating', 'count_of_star_ratings', 'Walmart', 160),
        ('mx_tv_written_review_count', '작성 리뷰 수와 전체 평가 수', 'count_of_reviews', 'count_of_star_ratings', 'Walmart', 170),
        ('mx_tv_rank_presence', '수집 목록 순위 누락', 'main_rank', 'bsr_rank', 'all', 180)
    ) AS entries(rule_key, name, field1, field2, retailer, sort_order)
    LOOP
        EXECUTE format($statement$
            UPDATE public.%I SET detail_name=$1, field1=$2, field2=$3,
                   retailer=$4, sort_order=$5, is_active=TRUE
            WHERE rule_type='crossfield' AND section_code=$6 AND table_name=$7
              AND detail_code='sem_tv_' || $8 AND validation_type=$8
        $statement$, rules_table)
        USING rule.name, rule.field1, rule.field2, rule.retailer, rule.sort_order,
              section, source_table, rule.rule_key;
        GET DIAGNOSTICS affected = ROW_COUNT;
        IF affected > 1 THEN
            RAISE EXCEPTION 'Duplicate SEM TV cross-field rule: %', rule.rule_key;
        ELSIF affected = 0 THEN
            EXECUTE format($statement$
                INSERT INTO public.%I
                    (rule_type, section_code, section_name, detail_code, detail_name, table_name, date_column,
                     product_line, retailer, field1, field2, validation_type, check_type, error_message,
                     display_columns, select_fields, query, query_detail, sort_order, is_active, created_at, created_id)
                VALUES ('crossfield', $1, 'SEM TV', 'sem_tv_' || $2, $3, $4, 'crawl_datetime', 'sem_tv',
                        $5, $6, $7, $2, 'cross_field', $3, $6 || '|' || $7, $6 || '|' || $7,
                        '', '', $8, TRUE, NOW(), 'setup_sem_tv_crossfield')
            $statement$, rules_table)
            USING section, rule.rule_key, rule.name, source_table, rule.retailer,
                  rule.field1, rule.field2, rule.sort_order;
        END IF;
    END LOOP;
END
$sem_tv_crossfield$;
