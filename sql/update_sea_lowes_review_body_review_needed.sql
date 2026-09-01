-- SEA REF/LDY Lowes review/body rule metadata only.
-- This does not change source data and can be run directly in DBeaver.

UPDATE public.monitoring_validation_rules
SET detail_name = '리뷰 수·본문 확인 필요',
    error_message = 'Lowes 사이트 특성 후보이며 이상치가 아닌 확인 필요 항목입니다.'
WHERE rule_type = 'crossfield'
  AND section_code IN ('sea_ref_retail', 'sea_ldy_retail')
  AND table_name IN ('public.ref_retail_com', 'public.ldy_retail_com')
  AND validation_type = 'review_body_count'
  AND LOWER(BTRIM(retailer)) = 'lowes';

SELECT
    section_code,
    retailer,
    validation_type,
    detail_name,
    error_message,
    is_active
FROM public.monitoring_validation_rules
WHERE rule_type = 'crossfield'
  AND section_code IN ('sea_ref_retail', 'sea_ldy_retail')
  AND validation_type = 'review_body_count'
  AND LOWER(BTRIM(retailer)) = 'lowes'
ORDER BY section_code;
