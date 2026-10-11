-- SEG Expert cross-field rules only (4 products x 7 rules).
-- Apply manually in PostgreSQL after reviewing. No source-data updates.
BEGIN;
LOCK TABLE public.monitoring_validation_rules IN SHARE ROW EXCLUSIVE MODE;
CREATE TEMP TABLE seg_expert_crossfield_seed (
    section_code text, section_name text, detail_code text, detail_name text,
    table_name text, date_column text, product_line text, retailer text,
    field1 text, field2 text, validation_type text, error_message text,
    select_fields text, sort_order integer
) ON COMMIT DROP;
INSERT INTO seg_expert_crossfield_seed VALUES
    ('seg_tv_retail', 'SEG TV', 'seg_tv_expert_rating_count_presence', '별점과 별점 수 존재 일치', 'dx_seg.dx_seg_tv_retail_com', 'crawl_strdatetime', 'seg_tv', 'Expert', 'star_rating', 'count_of_star_ratings', 'rating_count_presence', '별점과 별점 수의 0값 관계 불일치. Mediamarkt·OTTO는 리뷰 수도 비교합니다.', 'star_rating|count_of_star_ratings|count_of_reviews', 200),
    ('seg_tv_retail', 'SEG TV', 'seg_tv_expert_review_count_match', '리뷰 수와 별점 수 일치', 'dx_seg.dx_seg_tv_retail_com', 'crawl_strdatetime', 'seg_tv', 'Expert', 'count_of_reviews', 'count_of_star_ratings', 'review_count_match', 'count_of_reviews와 count_of_star_ratings가 다릅니다.', 'count_of_reviews|count_of_star_ratings|star_rating', 201),
    ('seg_tv_retail', 'SEG TV', 'seg_tv_expert_final_original_price', '최종가와 원가 순서', 'dx_seg.dx_seg_tv_retail_com', 'crawl_strdatetime', 'seg_tv', 'Expert', 'final_sku_price', 'original_sku_price', 'final_original_price', 'final_sku_price가 original_sku_price보다 크거나 같습니다.', 'final_sku_price|original_sku_price|savings', 202),
    ('seg_tv_retail', 'SEG TV', 'seg_tv_expert_savings_missing', '할인 가격 존재 시 savings 확인', 'dx_seg.dx_seg_tv_retail_com', 'crawl_strdatetime', 'seg_tv', 'Expert', 'savings', 'final_sku_price|original_sku_price', 'savings_missing', '원가와 판매가가 있지만 savings가 없습니다. 할인율 크기와 관계없이 검수합니다.', 'final_sku_price|original_sku_price|savings', 203),
    ('seg_tv_retail', 'SEG TV', 'seg_tv_expert_original_missing', '판매가·savings 존재 시 원가 확인', 'dx_seg.dx_seg_tv_retail_com', 'crawl_strdatetime', 'seg_tv', 'Expert', 'original_sku_price', 'final_sku_price|savings', 'original_missing', '판매가와 savings가 있는데 original_sku_price가 NULL 또는 빈값입니다.', 'final_sku_price|original_sku_price|savings', 204),
    ('seg_tv_retail', 'SEG TV', 'seg_tv_expert_final_missing', '원가·savings 존재 시 판매가 확인', 'dx_seg.dx_seg_tv_retail_com', 'crawl_strdatetime', 'seg_tv', 'Expert', 'final_sku_price', 'original_sku_price|savings', 'final_missing', '원가 또는 savings가 있는데 final_sku_price가 NULL 또는 빈값입니다.', 'final_sku_price|original_sku_price|savings', 205),
    ('seg_tv_retail', 'SEG TV', 'seg_tv_expert_savings_rate_match', 'Expert 계산 할인율과 표시 할인율 일치', 'dx_seg.dx_seg_tv_retail_com', 'crawl_strdatetime', 'seg_tv', 'Expert', 'savings', 'final_sku_price|original_sku_price', 'savings_rate_match', '표시 할인율이 가격으로 계산한 할인율의 정수 버림값과 다릅니다.', 'final_sku_price|original_sku_price|savings', 206),
    ('seg_ref_retail', 'SEG REF', 'seg_ref_expert_rating_count_presence', '별점과 별점 수 존재 일치', 'dx_seg.dx_seg_ref_retail_com', 'crawl_strdatetime', 'seg_ref', 'Expert', 'star_rating', 'count_of_star_ratings', 'rating_count_presence', '별점과 별점 수의 0값 관계 불일치. Mediamarkt·OTTO는 리뷰 수도 비교합니다.', 'star_rating|count_of_star_ratings|count_of_reviews', 200),
    ('seg_ref_retail', 'SEG REF', 'seg_ref_expert_review_count_match', '리뷰 수와 별점 수 일치', 'dx_seg.dx_seg_ref_retail_com', 'crawl_strdatetime', 'seg_ref', 'Expert', 'count_of_reviews', 'count_of_star_ratings', 'review_count_match', 'count_of_reviews와 count_of_star_ratings가 다릅니다.', 'count_of_reviews|count_of_star_ratings|star_rating', 201),
    ('seg_ref_retail', 'SEG REF', 'seg_ref_expert_final_original_price', '최종가와 원가 순서', 'dx_seg.dx_seg_ref_retail_com', 'crawl_strdatetime', 'seg_ref', 'Expert', 'final_sku_price', 'original_sku_price', 'final_original_price', 'final_sku_price가 original_sku_price보다 크거나 같습니다.', 'final_sku_price|original_sku_price|savings', 202),
    ('seg_ref_retail', 'SEG REF', 'seg_ref_expert_savings_missing', '할인 가격 존재 시 savings 확인', 'dx_seg.dx_seg_ref_retail_com', 'crawl_strdatetime', 'seg_ref', 'Expert', 'savings', 'final_sku_price|original_sku_price', 'savings_missing', '원가와 판매가가 있지만 savings가 없습니다. 할인율 크기와 관계없이 검수합니다.', 'final_sku_price|original_sku_price|savings', 203),
    ('seg_ref_retail', 'SEG REF', 'seg_ref_expert_original_missing', '판매가·savings 존재 시 원가 확인', 'dx_seg.dx_seg_ref_retail_com', 'crawl_strdatetime', 'seg_ref', 'Expert', 'original_sku_price', 'final_sku_price|savings', 'original_missing', '판매가와 savings가 있는데 original_sku_price가 NULL 또는 빈값입니다.', 'final_sku_price|original_sku_price|savings', 204),
    ('seg_ref_retail', 'SEG REF', 'seg_ref_expert_final_missing', '원가·savings 존재 시 판매가 확인', 'dx_seg.dx_seg_ref_retail_com', 'crawl_strdatetime', 'seg_ref', 'Expert', 'final_sku_price', 'original_sku_price|savings', 'final_missing', '원가 또는 savings가 있는데 final_sku_price가 NULL 또는 빈값입니다.', 'final_sku_price|original_sku_price|savings', 205),
    ('seg_ref_retail', 'SEG REF', 'seg_ref_expert_savings_rate_match', 'Expert 계산 할인율과 표시 할인율 일치', 'dx_seg.dx_seg_ref_retail_com', 'crawl_strdatetime', 'seg_ref', 'Expert', 'savings', 'final_sku_price|original_sku_price', 'savings_rate_match', '표시 할인율이 가격으로 계산한 할인율의 정수 버림값과 다릅니다.', 'final_sku_price|original_sku_price|savings', 206),
    ('seg_ldy_retail', 'SEG LDY', 'seg_ldy_expert_rating_count_presence', '별점과 별점 수 존재 일치', 'dx_seg.dx_seg_ldy_retail_com', 'crawl_strdatetime', 'seg_ldy', 'Expert', 'star_rating', 'count_of_star_ratings', 'rating_count_presence', '별점과 별점 수의 0값 관계 불일치. Mediamarkt·OTTO는 리뷰 수도 비교합니다.', 'star_rating|count_of_star_ratings|count_of_reviews', 200),
    ('seg_ldy_retail', 'SEG LDY', 'seg_ldy_expert_review_count_match', '리뷰 수와 별점 수 일치', 'dx_seg.dx_seg_ldy_retail_com', 'crawl_strdatetime', 'seg_ldy', 'Expert', 'count_of_reviews', 'count_of_star_ratings', 'review_count_match', 'count_of_reviews와 count_of_star_ratings가 다릅니다.', 'count_of_reviews|count_of_star_ratings|star_rating', 201),
    ('seg_ldy_retail', 'SEG LDY', 'seg_ldy_expert_final_original_price', '최종가와 원가 순서', 'dx_seg.dx_seg_ldy_retail_com', 'crawl_strdatetime', 'seg_ldy', 'Expert', 'final_sku_price', 'original_sku_price', 'final_original_price', 'final_sku_price가 original_sku_price보다 크거나 같습니다.', 'final_sku_price|original_sku_price|savings', 202),
    ('seg_ldy_retail', 'SEG LDY', 'seg_ldy_expert_savings_missing', '할인 가격 존재 시 savings 확인', 'dx_seg.dx_seg_ldy_retail_com', 'crawl_strdatetime', 'seg_ldy', 'Expert', 'savings', 'final_sku_price|original_sku_price', 'savings_missing', '원가와 판매가가 있지만 savings가 없습니다. 할인율 크기와 관계없이 검수합니다.', 'final_sku_price|original_sku_price|savings', 203),
    ('seg_ldy_retail', 'SEG LDY', 'seg_ldy_expert_original_missing', '판매가·savings 존재 시 원가 확인', 'dx_seg.dx_seg_ldy_retail_com', 'crawl_strdatetime', 'seg_ldy', 'Expert', 'original_sku_price', 'final_sku_price|savings', 'original_missing', '판매가와 savings가 있는데 original_sku_price가 NULL 또는 빈값입니다.', 'final_sku_price|original_sku_price|savings', 204),
    ('seg_ldy_retail', 'SEG LDY', 'seg_ldy_expert_final_missing', '원가·savings 존재 시 판매가 확인', 'dx_seg.dx_seg_ldy_retail_com', 'crawl_strdatetime', 'seg_ldy', 'Expert', 'final_sku_price', 'original_sku_price|savings', 'final_missing', '원가 또는 savings가 있는데 final_sku_price가 NULL 또는 빈값입니다.', 'final_sku_price|original_sku_price|savings', 205),
    ('seg_ldy_retail', 'SEG LDY', 'seg_ldy_expert_savings_rate_match', 'Expert 계산 할인율과 표시 할인율 일치', 'dx_seg.dx_seg_ldy_retail_com', 'crawl_strdatetime', 'seg_ldy', 'Expert', 'savings', 'final_sku_price|original_sku_price', 'savings_rate_match', '표시 할인율이 가격으로 계산한 할인율의 정수 버림값과 다릅니다.', 'final_sku_price|original_sku_price|savings', 206),
    ('seg_ldy_dryer_retail', 'SEG LDY_DRYER', 'seg_ldy_dryer_expert_rating_count_presence', '별점과 별점 수 존재 일치', 'dx_seg.dx_seg_ldy_dryer_retail', 'crawl_datetime', 'seg_ldy_dryer', 'Expert', 'star_rating', 'count_of_star_ratings', 'rating_count_presence', '별점과 별점 수의 0값 관계 불일치. Mediamarkt·OTTO는 리뷰 수도 비교합니다.', 'star_rating|count_of_star_ratings|count_of_reviews', 200),
    ('seg_ldy_dryer_retail', 'SEG LDY_DRYER', 'seg_ldy_dryer_expert_review_count_match', '리뷰 수와 별점 수 일치', 'dx_seg.dx_seg_ldy_dryer_retail', 'crawl_datetime', 'seg_ldy_dryer', 'Expert', 'count_of_reviews', 'count_of_star_ratings', 'review_count_match', 'count_of_reviews와 count_of_star_ratings가 다릅니다.', 'count_of_reviews|count_of_star_ratings|star_rating', 201),
    ('seg_ldy_dryer_retail', 'SEG LDY_DRYER', 'seg_ldy_dryer_expert_final_original_price', '최종가와 원가 순서', 'dx_seg.dx_seg_ldy_dryer_retail', 'crawl_datetime', 'seg_ldy_dryer', 'Expert', 'final_sku_price', 'original_sku_price', 'final_original_price', 'final_sku_price가 original_sku_price보다 크거나 같습니다.', 'final_sku_price|original_sku_price|savings', 202),
    ('seg_ldy_dryer_retail', 'SEG LDY_DRYER', 'seg_ldy_dryer_expert_savings_missing', '할인 가격 존재 시 savings 확인', 'dx_seg.dx_seg_ldy_dryer_retail', 'crawl_datetime', 'seg_ldy_dryer', 'Expert', 'savings', 'final_sku_price|original_sku_price', 'savings_missing', '원가와 판매가가 있지만 savings가 없습니다. 할인율 크기와 관계없이 검수합니다.', 'final_sku_price|original_sku_price|savings', 203),
    ('seg_ldy_dryer_retail', 'SEG LDY_DRYER', 'seg_ldy_dryer_expert_original_missing', '판매가·savings 존재 시 원가 확인', 'dx_seg.dx_seg_ldy_dryer_retail', 'crawl_datetime', 'seg_ldy_dryer', 'Expert', 'original_sku_price', 'final_sku_price|savings', 'original_missing', '판매가와 savings가 있는데 original_sku_price가 NULL 또는 빈값입니다.', 'final_sku_price|original_sku_price|savings', 204),
    ('seg_ldy_dryer_retail', 'SEG LDY_DRYER', 'seg_ldy_dryer_expert_final_missing', '원가·savings 존재 시 판매가 확인', 'dx_seg.dx_seg_ldy_dryer_retail', 'crawl_datetime', 'seg_ldy_dryer', 'Expert', 'final_sku_price', 'original_sku_price|savings', 'final_missing', '원가 또는 savings가 있는데 final_sku_price가 NULL 또는 빈값입니다.', 'final_sku_price|original_sku_price|savings', 205),
    ('seg_ldy_dryer_retail', 'SEG LDY_DRYER', 'seg_ldy_dryer_expert_savings_rate_match', 'Expert 계산 할인율과 표시 할인율 일치', 'dx_seg.dx_seg_ldy_dryer_retail', 'crawl_datetime', 'seg_ldy_dryer', 'Expert', 'savings', 'final_sku_price|original_sku_price', 'savings_rate_match', '표시 할인율이 가격으로 계산한 할인율의 정수 버림값과 다릅니다.', 'final_sku_price|original_sku_price|savings', 206);

UPDATE public.monitoring_validation_rules target
SET section_name = seed.section_name, detail_name = seed.detail_name,
    date_column = seed.date_column, product_line = seed.product_line,
    field1 = seed.field1, field2 = seed.field2, validation_type = seed.validation_type,
    error_message = seed.error_message, select_fields = seed.select_fields,
    sort_order = seed.sort_order, is_active = TRUE
FROM seg_expert_crossfield_seed seed
WHERE target.rule_type = 'crossfield' AND target.detail_code = seed.detail_code
  AND target.table_name = seed.table_name AND lower(trim(target.retailer)) = 'expert';

INSERT INTO public.monitoring_validation_rules (
    rule_type, section_code, section_name, detail_code, detail_name,
    table_name, date_column, product_line, retailer, field1, field2,
    validation_type, error_message, select_fields, query, sort_order,
    is_active, created_at, created_id
)
SELECT 'crossfield', s.section_code, s.section_name, s.detail_code, s.detail_name,
       s.table_name, s.date_column, s.product_line, s.retailer, s.field1, s.field2,
       s.validation_type, s.error_message, s.select_fields,
       'Application-enforced SEG Expert cross-field rule.', s.sort_order,
       TRUE, NOW(), 'seed_seg_expert_crossfield'
FROM seg_expert_crossfield_seed s
WHERE NOT EXISTS (
    SELECT 1 FROM public.monitoring_validation_rules t
    WHERE t.rule_type = 'crossfield' AND t.detail_code = s.detail_code
      AND t.table_name = s.table_name AND lower(trim(t.retailer)) = 'expert'
);
DO $$
BEGIN
    IF (SELECT count(*) FROM public.monitoring_validation_rules t
        JOIN seg_expert_crossfield_seed s ON t.detail_code = s.detail_code
          AND t.table_name = s.table_name
        WHERE t.rule_type = 'crossfield' AND lower(trim(t.retailer)) = 'expert'
          AND t.is_active IS TRUE) <> 28 THEN
        RAISE EXCEPTION 'Expected exactly 28 active Expert rules; transaction aborted';
    END IF;
END $$;
COMMIT;
