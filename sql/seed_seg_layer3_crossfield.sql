-- SEG Layer3 cross-field configuration (TV/REF/LDY).
-- PostgreSQL only. Review and run manually in DBeaver.
-- Application code evaluates these allow-listed rule keys; stored query text
-- is informational and is never executed.
-- Exact expected active seed rows: 39 (13 per product line).

BEGIN;

CREATE TEMP TABLE _seg_crossfield_source_seed (
    product_line text PRIMARY KEY,
    section_code text NOT NULL,
    section_name text NOT NULL,
    table_name text NOT NULL,
    date_column text NOT NULL
) ON COMMIT DROP;

INSERT INTO _seg_crossfield_source_seed
    (product_line, section_code, section_name, table_name, date_column)
VALUES
    ('seg_tv', 'seg_tv_retail', 'SEG TV',
     'dx_seg.dx_seg_tv_retail_com', 'crawl_strdatetime'),
    ('seg_ref', 'seg_ref_retail', 'SEG REF',
     'dx_seg.dx_seg_ref_retail_com', 'crawl_strdatetime'),
    ('seg_ldy', 'seg_ldy_retail', 'SEG LDY',
     'dx_seg.dx_seg_ldy_retail_com', 'crawl_strdatetime');

CREATE TEMP TABLE _seg_crossfield_rule_seed (
    rule_key text PRIMARY KEY,
    detail_name text NOT NULL,
    field1 text NOT NULL,
    field2 text,
    error_message text NOT NULL,
    select_fields text NOT NULL,
    sort_order integer NOT NULL
) ON COMMIT DROP;

INSERT INTO _seg_crossfield_rule_seed
    (rule_key, detail_name, field1, field2,
     error_message, select_fields, sort_order)
VALUES
    ('rating_count_presence', '별점과 별점 수 존재 일치',
     'star_rating', 'count_of_star_ratings',
     '별점과 별점 수의 0값 관계 불일치. Mediamarkt·OTTO는 리뷰 수도 비교합니다.',
     'star_rating|count_of_star_ratings|count_of_reviews', 10),
    ('no_review_rating_count', '리뷰 없음 문구와 별점 수 일치',
     'star_rating', 'count_of_star_ratings',
     'star_rating이 No customer reviews인데 count_of_star_ratings가 1 이상입니다.',
     'star_rating|count_of_star_ratings', 20),
    ('rating_range', '별점 숫자 형식 및 5점 이하',
     'star_rating', NULL,
     'star_rating이 숫자가 아니거나 허용 범위 0~5를 벗어났습니다.',
     'star_rating|count_of_star_ratings', 30),
    ('rank_page_type', '페이지 유형과 순위 필드 일치',
     'page_type', 'main_rank|bsr_rank',
     'MAIN/BSR page_type에 해당하는 순위 필드가 없습니다.',
     'page_type|main_rank|bsr_rank', 40),
    ('final_original_price', '최종가와 원가 순서',
     'final_sku_price', 'original_sku_price',
     'final_sku_price가 original_sku_price보다 크거나 같습니다.',
     'final_sku_price|original_sku_price|savings', 50),
    ('discount_rate_90', '90% 이상 할인 검증',
     'final_sku_price', 'original_sku_price',
     '최종가와 원가로 계산한 할인율이 90% 이상입니다.',
     'final_sku_price|original_sku_price|savings', 60),
    ('savings_missing', '할인 가격 존재 시 savings 확인',
     'savings', 'final_sku_price|original_sku_price',
     '할인 가격인데 savings가 없습니다. Mediamarkt는 할인율 10% 이하를 제외합니다.',
     'final_sku_price|original_sku_price|savings', 70),
    ('original_missing', '판매가·savings 존재 시 원가 확인',
     'original_sku_price', 'final_sku_price|savings',
     '판매가와 savings가 있는데 original_sku_price가 NULL 또는 빈값입니다.',
     'final_sku_price|original_sku_price|savings', 80),
    ('final_missing', '원가·savings 존재 시 판매가 확인',
     'final_sku_price', 'original_sku_price|savings',
     '원가 또는 savings가 있는데 final_sku_price가 NULL 또는 빈값입니다.',
     'final_sku_price|original_sku_price|savings', 90),
    ('savings_amount_match', 'Amazon 할인 금액 일치',
     'savings', 'original_sku_price|final_sku_price',
     'savings가 original_sku_price-final_sku_price와 센트 단위까지 일치하지 않습니다.',
     'final_sku_price|original_sku_price|savings', 100),
    ('review_count_match', '리뷰 수와 별점 수 일치',
     'count_of_reviews', 'count_of_star_ratings',
     'count_of_reviews와 count_of_star_ratings가 다릅니다.',
     'count_of_reviews|count_of_star_ratings|star_rating', 110),
    ('review_body_count', '리뷰 수와 본문 확인',
     'count_of_reviews', 'detailed_review_content',
     '두 카운트가 0인데 본문이 남았는지 확인합니다. OTTO는 기존 본문 네 가지 조건도 확인합니다.',
     'count_of_reviews|count_of_star_ratings|detailed_review_content|review_body_count|issue_type', 120),
    ('review_body_decrease', '전날 대비 리뷰본문 감소',
     'detailed_review_content', NULL,
     '수집 완료 후 카운트 변화와 최대 20개 수집 기준으로 설명되지 않는 전날 대비 리뷰본문 감소입니다.',
     'count_of_reviews|count_of_star_ratings|detailed_review_content|review_body_count|previous_review_body_count|previous_source_date', 130);

CREATE TEMP TABLE _seg_crossfield_seed AS
SELECT
    source.product_line,
    source.section_code,
    source.section_name,
    source.table_name,
    source.date_column,
    'ALL'::text AS retailer,
    source.product_line || '_' || rule.rule_key AS detail_code,
    rule.rule_key,
    rule.detail_name,
    rule.field1,
    rule.field2,
    rule.error_message,
    rule.select_fields,
    rule.sort_order
FROM _seg_crossfield_source_seed source
CROSS JOIN _seg_crossfield_rule_seed rule;

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
    query = 'Application-enforced SEG rule; copy query generated at runtime.',
    sort_order = seed.sort_order,
    is_active = TRUE
FROM _seg_crossfield_seed seed
WHERE target.rule_type = 'crossfield'
  AND target.section_code = seed.section_code
  AND target.table_name = seed.table_name
  AND target.detail_code = seed.detail_code
  AND UPPER(BTRIM(target.retailer)) = 'ALL';

INSERT INTO public.monitoring_validation_rules (
    rule_type, section_code, section_name, detail_code, detail_name,
    table_name, date_column, product_line, retailer, field1, field2,
    validation_type, error_message, select_fields, query, sort_order,
    is_active, created_at, created_id
)
SELECT
    'crossfield', seed.section_code, seed.section_name, seed.detail_code,
    seed.detail_name, seed.table_name, seed.date_column, seed.product_line,
    seed.retailer, seed.field1, seed.field2, seed.rule_key,
    seed.error_message, seed.select_fields,
    'Application-enforced SEG rule; copy query generated at runtime.',
    seed.sort_order, TRUE, NOW(), 'seed_seg_layer3_crossfield'
FROM _seg_crossfield_seed seed
WHERE NOT EXISTS (
    SELECT 1
    FROM public.monitoring_validation_rules target
    WHERE target.rule_type = 'crossfield'
      AND target.section_code = seed.section_code
      AND target.table_name = seed.table_name
      AND target.detail_code = seed.detail_code
      AND UPPER(BTRIM(target.retailer)) = 'ALL'
);

DO $$
DECLARE
    active_seed_count integer;
BEGIN
    SELECT COUNT(*)
    INTO active_seed_count
    FROM public.monitoring_validation_rules target
    JOIN _seg_crossfield_seed seed
      ON target.rule_type = 'crossfield'
     AND target.section_code = seed.section_code
     AND target.table_name = seed.table_name
     AND target.detail_code = seed.detail_code
     AND UPPER(BTRIM(target.retailer)) = 'ALL'
    WHERE target.is_active IS TRUE;

    IF active_seed_count <> 39 THEN
        RAISE EXCEPTION
            'Expected 39 active SEG cross-field rules, found %',
            active_seed_count;
    END IF;
END $$;

COMMIT;

SELECT section_code, table_name, COUNT(*) AS configured_rules
FROM public.monitoring_validation_rules
WHERE rule_type = 'crossfield'
  AND section_code IN ('seg_tv_retail', 'seg_ref_retail', 'seg_ldy_retail')
  AND is_active IS TRUE
GROUP BY section_code, table_name
ORDER BY section_code;
