-- SIEL Layer3 cross-field configuration (TV/REF/LDY).
-- PostgreSQL only. Review and run manually in DBeaver.
-- Application code evaluates these allow-listed rule keys; stored query text
-- is informational and is never executed.
-- Exact expected active seed rows: 48 (16 per product line).

BEGIN;

CREATE TEMP TABLE _siel_crossfield_source_seed (
    product_line text PRIMARY KEY,
    section_code text NOT NULL,
    section_name text NOT NULL,
    table_name text NOT NULL,
    date_column text NOT NULL
) ON COMMIT DROP;

INSERT INTO _siel_crossfield_source_seed
    (product_line, section_code, section_name, table_name, date_column)
VALUES
    ('siel_tv', 'siel_tv_retail', 'SIEL TV',
     'dx_siel.dx_siel_tv_retail_com', 'crawl_datetime'),
    ('siel_ref', 'siel_ref_retail', 'SIEL REF',
     'dx_siel.dx_siel_ref_retail_com', 'crawl_datetime'),
    ('siel_ldy', 'siel_ldy_retail', 'SIEL LDY',
     'dx_siel.dx_siel_ldy_retail_com', 'crawl_datetime');

CREATE TEMP TABLE _siel_crossfield_rule_seed (
    retailer text NOT NULL,
    rule_key text NOT NULL,
    detail_name text NOT NULL,
    field1 text NOT NULL,
    field2 text,
    error_message text NOT NULL,
    select_fields text NOT NULL,
    sort_order integer NOT NULL,
    PRIMARY KEY (retailer, rule_key)
) ON COMMIT DROP;

INSERT INTO _siel_crossfield_rule_seed
    (retailer, rule_key, detail_name, field1, field2,
     error_message, select_fields, sort_order)
VALUES
    ('Amazon', 'rating_count_presence', '별점과 별점 수 존재 일치',
     'star_rating', 'count_of_star_ratings',
     'star_rating의 0 여부와 count_of_star_ratings의 NULL·빈값·0 여부가 일치하지 않습니다.',
     'star_rating|count_of_star_ratings|count_of_reviews', 10),
    ('Amazon', 'no_review_rating_count', '리뷰 없음 문구와 별점 수 일치',
     'star_rating', 'count_of_star_ratings',
     'star_rating이 No customer reviews인데 count_of_star_ratings가 1 이상입니다.',
     'star_rating|count_of_star_ratings', 20),
    ('Amazon', 'rating_range', '별점 숫자 형식 및 5점 이하',
     'star_rating', NULL,
     'star_rating이 숫자가 아니거나 허용 범위 0~5를 벗어났습니다.',
     'star_rating|count_of_star_ratings', 30),
    ('Amazon', 'rank_page_type', '페이지 유형과 순위 필드 일치',
     'page_type', 'main_rank|bsr_rank',
     'MAIN/BSR page_type에 해당하는 순위 필드가 없습니다.',
     'page_type|main_rank|bsr_rank', 40),
    ('Amazon', 'final_original_price', '최종가와 원가 순서',
     'final_sku_price', 'original_sku_price',
     'final_sku_price가 original_sku_price보다 큽니다.',
     'final_sku_price|original_sku_price|savings', 50),
    ('Amazon', 'discount_rate_90', '90% 이상 할인 검증',
     'final_sku_price', 'original_sku_price',
     '최종가와 원가로 계산한 할인율이 90% 이상입니다.',
     'final_sku_price|original_sku_price|savings', 60),

    ('Flipkart', 'rating_count_presence', '별점과 별점 수 존재 일치',
     'star_rating', 'count_of_star_ratings',
     'star_rating의 0 여부와 count_of_star_ratings의 NULL·빈값·0 여부가 일치하지 않습니다.',
     'star_rating|count_of_star_ratings|count_of_reviews', 10),
    ('Flipkart', 'rating_range', '별점 숫자 형식 및 5점 이하',
     'star_rating', NULL,
     'star_rating이 숫자가 아니거나 허용 범위 0~5를 벗어났습니다.',
     'star_rating|count_of_star_ratings', 30),
    ('Flipkart', 'review_body_missing', '리뷰 수 존재 시 리뷰본문 확인',
     'count_of_reviews', 'detailed_review_content',
     'count_of_reviews가 1 이상인데 detailed_review_content가 NULL 또는 빈값입니다.',
     'count_of_reviews|count_of_star_ratings|detailed_review_content', 70),
    ('Flipkart', 'review_count_missing', '리뷰본문 존재 시 리뷰 수 확인',
     'detailed_review_content', 'count_of_reviews',
     'detailed_review_content가 있는데 count_of_reviews가 NULL·빈값 또는 0입니다.',
     'count_of_reviews|count_of_star_ratings|detailed_review_content', 80),
    ('Flipkart', 'review_star_count_missing', '리뷰 수 존재 시 별점 수 확인',
     'count_of_reviews', 'count_of_star_ratings',
     'count_of_reviews가 1 이상인데 count_of_star_ratings가 NULL·빈값 또는 0입니다.',
     'count_of_reviews|count_of_star_ratings|star_rating', 90),
    ('Flipkart', 'review_gt_star_count', '리뷰 수가 별점 수 이하',
     'count_of_reviews', 'count_of_star_ratings',
     'count_of_reviews가 count_of_star_ratings보다 큽니다.',
     'count_of_reviews|count_of_star_ratings|star_rating', 100),
    ('Flipkart', 'final_original_price', '최종가와 원가 순서',
     'final_sku_price', 'original_sku_price',
     'final_sku_price가 original_sku_price보다 큽니다.',
     'final_sku_price|original_sku_price|savings', 50),
    ('Flipkart', 'savings_missing', '최종가·원가 존재 시 할인율 확인',
     'savings', 'final_sku_price|original_sku_price',
     '최종가와 원가가 있는데 savings가 NULL 또는 빈값입니다.',
     'final_sku_price|original_sku_price|savings', 110),
    ('Flipkart', 'original_missing', '최종가·할인율 존재 시 원가 확인',
     'original_sku_price', 'final_sku_price|savings',
     '최종가와 savings가 있는데 original_sku_price가 NULL 또는 빈값입니다.',
     'final_sku_price|original_sku_price|savings', 120),
    ('Flipkart', 'savings_rate_match', '표시 할인율과 가격 차이 일치',
     'savings', 'original_sku_price|final_sku_price',
     'savings와 (원가-최종가)/원가의 차이가 1%p를 초과합니다.',
     'final_sku_price|original_sku_price|savings', 130);

CREATE TEMP TABLE _siel_crossfield_seed AS
SELECT
    source.product_line,
    source.section_code,
    source.section_name,
    source.table_name,
    source.date_column,
    rule.retailer,
    source.product_line || '_' || rule.rule_key AS detail_code,
    rule.rule_key,
    rule.detail_name,
    rule.field1,
    rule.field2,
    rule.error_message,
    rule.select_fields,
    rule.sort_order
FROM _siel_crossfield_source_seed source
CROSS JOIN _siel_crossfield_rule_seed rule;

UPDATE public.monitoring_validation_rules target
SET section_name = seed.section_name,
    detail_name = seed.detail_name,
    date_column = seed.date_column,
    product_line = seed.product_line,
    field1 = seed.field1,
    field2 = seed.field2,
    validation_type = seed.rule_key,
    error_message = seed.error_message,
    select_fields = seed.select_fields,
    query = 'Application-enforced SIEL rule; copy query generated at runtime.',
    sort_order = seed.sort_order,
    is_active = TRUE
FROM _siel_crossfield_seed seed
WHERE target.rule_type = 'crossfield'
  AND target.section_code = seed.section_code
  AND target.table_name = seed.table_name
  AND target.detail_code = seed.detail_code
  AND LOWER(BTRIM(target.retailer)) = LOWER(BTRIM(seed.retailer));

INSERT INTO public.monitoring_validation_rules (
    rule_type,
    section_code,
    section_name,
    detail_code,
    detail_name,
    table_name,
    date_column,
    product_line,
    retailer,
    field1,
    field2,
    validation_type,
    error_message,
    select_fields,
    query,
    sort_order,
    is_active,
    created_at,
    created_id
)
SELECT
    'crossfield',
    seed.section_code,
    seed.section_name,
    seed.detail_code,
    seed.detail_name,
    seed.table_name,
    seed.date_column,
    seed.product_line,
    seed.retailer,
    seed.field1,
    seed.field2,
    seed.rule_key,
    seed.error_message,
    seed.select_fields,
    'Application-enforced SIEL rule; copy query generated at runtime.',
    seed.sort_order,
    TRUE,
    NOW(),
    'seed_siel_layer3_crossfield'
FROM _siel_crossfield_seed seed
WHERE NOT EXISTS (
    SELECT 1
    FROM public.monitoring_validation_rules target
    WHERE target.rule_type = 'crossfield'
      AND target.section_code = seed.section_code
      AND target.table_name = seed.table_name
      AND target.detail_code = seed.detail_code
      AND LOWER(BTRIM(target.retailer)) = LOWER(BTRIM(seed.retailer))
);

DO $$
DECLARE
    active_seed_count integer;
BEGIN
    SELECT COUNT(*)
    INTO active_seed_count
    FROM public.monitoring_validation_rules target
    JOIN _siel_crossfield_seed seed
      ON target.rule_type = 'crossfield'
     AND target.section_code = seed.section_code
     AND target.table_name = seed.table_name
     AND target.detail_code = seed.detail_code
     AND LOWER(BTRIM(target.retailer)) = LOWER(BTRIM(seed.retailer))
    WHERE target.is_active IS TRUE;

    IF active_seed_count <> 48 THEN
        RAISE EXCEPTION
            'Expected 48 active SIEL cross-field rules, found %',
            active_seed_count;
    END IF;
END $$;

COMMIT;

-- Verification: three rows, each with 16 active configured rules.
SELECT
    section_code,
    table_name,
    COUNT(*) AS configured_rules,
    STRING_AGG(
        retailer || ':' || validation_type,
        ', ' ORDER BY sort_order, retailer, validation_type
    ) AS rules
FROM public.monitoring_validation_rules
WHERE rule_type = 'crossfield'
  AND section_code IN (
      'siel_tv_retail', 'siel_ref_retail', 'siel_ldy_retail'
  )
  AND is_active IS TRUE
GROUP BY section_code, table_name
ORDER BY section_code;
