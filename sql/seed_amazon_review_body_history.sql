-- Apply after deploying the Amazon history cross-field implementation.
-- PostgreSQL: run manually against the monitoring database.
-- Scope: SEG TV/REF and SIEL TV/REF/LDY Amazon (SEG LDY has no Amazon).
-- Only current NULL/empty review bodies are checked, using the previous
-- 10 source days, excluding the current day, for the same country/product/item.
-- Past body exists -> anomaly. Past rows exist but no body -> normal.
-- No past rows + rating > 0 + rating/review count >= 1 -> anomaly.
-- Idempotent: changes only this rule; existing rules remain untouched.

BEGIN;

CREATE TEMP TABLE _amazon_review_history_seed ON COMMIT DROP AS
SELECT
    source.*,
    product_line || '_amazon_review_body_history' AS detail_code,
    'amazon_review_body_history'::text AS rule_key,
    'Amazon 최근 10일 이력 기준 리뷰본문 누락'::text AS detail_name,
    'detailed_review_content'::text AS field1,
    'star_rating|count_of_star_ratings|count_of_reviews'::text AS field2,
    '최근 10일 내 리뷰본문이 있었으나 현재 누락되었거나, 과거 수집 이력 없이 별점·평가/리뷰 수만 있습니다.'::text AS error_message,
    'issue_type|star_rating|count_of_star_ratings|count_of_reviews|detailed_review_content|review_history_days|review_history_start|review_history_end|previous_source_date'::text AS select_fields
FROM (VALUES
    ('seg_tv', 'seg_tv_retail', 'SEG TV',
     'dx_seg.dx_seg_tv_retail_com', 'crawl_strdatetime'),
    ('seg_ref', 'seg_ref_retail', 'SEG REF',
     'dx_seg.dx_seg_ref_retail_com', 'crawl_strdatetime'),
    ('siel_tv', 'siel_tv_retail', 'SIEL TV',
     'dx_siel.dx_siel_tv_retail_com', 'crawl_datetime'),
    ('siel_ref', 'siel_ref_retail', 'SIEL REF',
     'dx_siel.dx_siel_ref_retail_com', 'crawl_datetime'),
    ('siel_ldy', 'siel_ldy_retail', 'SIEL LDY',
     'dx_siel.dx_siel_ldy_retail_com', 'crawl_datetime')
) AS source(product_line, section_code, section_name, table_name, date_column);

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
    query = 'Application-enforced Amazon history rule; copy query generated at runtime.',
    sort_order = 200,
    is_active = TRUE
FROM _amazon_review_history_seed seed
WHERE target.rule_type = 'crossfield'
  AND target.section_code = seed.section_code
  AND target.table_name = seed.table_name
  AND target.detail_code = seed.detail_code
  AND LOWER(BTRIM(target.retailer)) = 'amazon';

INSERT INTO public.monitoring_validation_rules (
    rule_type, section_code, section_name, detail_code, detail_name,
    table_name, date_column, product_line, retailer, field1, field2,
    validation_type, error_message, select_fields, query, sort_order,
    is_active, created_at, created_id
)
SELECT
    'crossfield', seed.section_code, seed.section_name,
    seed.detail_code, seed.detail_name, seed.table_name, seed.date_column,
    seed.product_line, 'Amazon', seed.field1, seed.field2, seed.rule_key,
    seed.error_message, seed.select_fields,
    'Application-enforced Amazon history rule; copy query generated at runtime.',
    200, TRUE, NOW(), 'seed_amazon_review_body_history'
FROM _amazon_review_history_seed seed
WHERE NOT EXISTS (
    SELECT 1 FROM public.monitoring_validation_rules target
    WHERE target.rule_type = 'crossfield'
      AND target.section_code = seed.section_code
      AND target.table_name = seed.table_name
      AND target.detail_code = seed.detail_code
      AND LOWER(BTRIM(target.retailer)) = 'amazon'
);

DO $$
DECLARE active_seed_count integer;
BEGIN
    SELECT COUNT(*) INTO active_seed_count
    FROM public.monitoring_validation_rules target
    JOIN _amazon_review_history_seed seed
      ON target.rule_type = 'crossfield'
     AND target.section_code = seed.section_code
     AND target.table_name = seed.table_name
     AND target.detail_code = seed.detail_code
     AND LOWER(BTRIM(target.retailer)) = 'amazon'
    WHERE target.is_active IS TRUE;
    IF active_seed_count <> 5 THEN
        RAISE EXCEPTION 'Expected 5 active Amazon history rules, found %', active_seed_count;
    END IF;
END $$;

COMMIT;

SELECT section_code, table_name, retailer, detail_name, is_active
FROM public.monitoring_validation_rules
WHERE rule_type = 'crossfield'
  AND validation_type = 'amazon_review_body_history'
  AND LOWER(BTRIM(retailer)) = 'amazon'
ORDER BY section_code;
