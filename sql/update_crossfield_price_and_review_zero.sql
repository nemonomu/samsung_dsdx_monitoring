-- Run manually in DBeaver after deploying the associated application code.
-- Updates existing metadata/SEA TV SQL only; no source data writes or new rules.
-- SEA TV IDs/conditions were inspected in the production rule UI on 2026-09-10.
BEGIN;

DO $$
DECLARE
    existing_query text;
    predicate_start integer;
    old_price_comparison text := $expr$CAST(REPLACE(REPLACE(SPLIT_PART(final_sku_price, '/', 1), '$', ''), ',', '') AS DECIMAL(10,2)) > CAST(REPLACE(REPLACE(SPLIT_PART(original_sku_price, '/', 1), '$', ''), ',', '') AS DECIMAL(10,2))$expr$;
    new_price_comparison text := $expr$CAST(REPLACE(REPLACE(SPLIT_PART(final_sku_price, '/', 1), '$', ''), ',', '') AS DECIMAL(10,2)) >= CAST(REPLACE(REPLACE(SPLIT_PART(original_sku_price, '/', 1), '$', ''), ',', '') AS DECIMAL(10,2))$expr$;
    bestbuy_zero_condition text := $condition$
        account_name = 'Bestbuy' AND (
            ((CASE WHEN BTRIM(star_rating) ~ '^[0-9,]+([.][0-9]+)?$'
                   THEN REPLACE(BTRIM(star_rating), ',', '')::numeric END = 0)
             <> (CASE WHEN BTRIM(count_of_reviews) ~ '^[0-9,]+([.][0-9]+)?$'
                      THEN REPLACE(BTRIM(count_of_reviews), ',', '')::numeric END = 0))
            OR
            ((CASE WHEN BTRIM(star_rating) ~ '^[0-9,]+([.][0-9]+)?$'
                   THEN REPLACE(BTRIM(star_rating), ',', '')::numeric END = 0)
             <> (CASE WHEN BTRIM(count_of_star_ratings) ~ '^[0-9,]+([.][0-9]+)?$'
                      THEN REPLACE(BTRIM(count_of_star_ratings), ',', '')::numeric END = 0))
        )
    $condition$;
BEGIN
    SELECT query INTO STRICT existing_query
    FROM public.monitoring_validation_rules
    WHERE id = 12 AND rule_type = 'crossfield' AND is_active IS TRUE
      AND section_code = 'tv_retail' AND table_name = 'tv_retail_com'
      AND field1 = 'final_sku_price' AND field2 = 'original_sku_price'
    FOR UPDATE;
    IF strpos(existing_query, old_price_comparison) > 0 THEN
        UPDATE public.monitoring_validation_rules
        SET query = replace(existing_query, old_price_comparison, new_price_comparison),
            error_message = '가격 이상 (final >= original 또는 할인율 90% 이상)'
        WHERE id = 12;
    ELSIF strpos(existing_query, new_price_comparison) = 0 THEN
        RAISE EXCEPTION 'SEA TV price SQL differs from the reviewed version; inspect rule 12';
    END IF;

    SELECT query INTO STRICT existing_query
    FROM public.monitoring_validation_rules
    WHERE id = 10 AND rule_type = 'crossfield' AND is_active IS TRUE
      AND section_code = 'tv_retail' AND table_name = 'tv_retail_com'
      AND field1 = 'star_rating'
    FOR UPDATE;
    IF strpos(existing_query, 'crossfield-20260910-bestbuy-zero') = 0 THEN
        -- Preserve the original date placeholder and all existing retailer cases.
        existing_query := regexp_replace(existing_query, ';[[:space:]]*$', '');
        predicate_start := strpos(existing_query, 'AND ((star_rating IS NOT NULL');
        IF predicate_start = 0 OR strpos(existing_query, 'star_rating, count_of_star_ratings,') = 0 THEN
            RAISE EXCEPTION 'SEA TV rating SQL differs from the reviewed version; inspect rule 10';
        END IF;
        existing_query := left(existing_query, predicate_start - 1)
            || 'AND (' || substr(existing_query, predicate_start + 4)
            || ' OR (' || bestbuy_zero_condition || ')) /* crossfield-20260910-bestbuy-zero */';
        existing_query := replace(existing_query,
            'star_rating, count_of_star_ratings,',
            'star_rating, count_of_star_ratings, count_of_reviews,');
        UPDATE public.monitoring_validation_rules
        SET query = existing_query,
            error_message = '별점·별점 수 관계 불일치. Bestbuy는 리뷰 수의 0 여부도 비교합니다.',
            select_fields = concat_ws('|', nullif(select_fields, ''),
                CASE WHEN NOT ('count_of_reviews' = ANY(string_to_array(coalesce(select_fields, ''), '|')))
                     THEN 'count_of_reviews' END)
        WHERE id = 10;
    END IF;
END $$;

UPDATE public.monitoring_validation_rules
SET error_message = 'final_sku_price가 original_sku_price보다 크거나 같습니다.'
WHERE rule_type = 'crossfield'
  AND section_code IN ('sea_ref_retail', 'sea_ldy_retail',
      'siel_tv_retail', 'siel_ref_retail', 'siel_ldy_retail',
      'seg_tv_retail', 'seg_ref_retail', 'seg_ldy_retail',
      'tse_tv_retail', 'tse_ref_retail', 'tse_ldy_retail')
  AND validation_type IN ('final_original_price', 'price_order', 'price_reverse');

UPDATE public.monitoring_validation_rules
SET error_message = '별점과 별점 수 또는 리뷰 수의 0 여부가 다릅니다.'
WHERE rule_type = 'crossfield'
  AND section_code IN ('sea_ref_retail', 'sea_ldy_retail')
  AND validation_type IN ('rating_count_presence', 'rating_count_required');

UPDATE public.monitoring_validation_rules
SET error_message = '별점과 별점 수 또는 리뷰 수의 0 여부가 다르거나 별점과 리뷰 수의 존재 여부가 다릅니다.'
WHERE rule_type = 'crossfield'
  AND section_code IN ('tse_tv_retail', 'tse_ref_retail', 'tse_ldy_retail')
  AND validation_type IN ('review_zero_pair', 'rating_count_presence', 'rating_count_required');

COMMIT;

SELECT id, section_code, retailer, validation_type, error_message
FROM public.monitoring_validation_rules
WHERE rule_type = 'crossfield' AND is_active IS TRUE
  AND (id IN (10, 12) OR section_code IN (
      'sea_ref_retail', 'sea_ldy_retail',
      'siel_tv_retail', 'siel_ref_retail', 'siel_ldy_retail',
      'seg_tv_retail', 'seg_ref_retail', 'seg_ldy_retail',
      'tse_tv_retail', 'tse_ref_retail', 'tse_ldy_retail'))
ORDER BY section_code, id;
