-- SEA REF/LDY 크로스필드 상세에서 리뷰본문을 바로 수정할 수 있도록 활성화합니다.
-- 운영 DB에서는 DBeaver로 실행하세요. 애플리케이션은 이 설정을 읽어
-- 현재 검수 대상 데이터일(D-1)의 detailed_review_content 셀만 편집 허용합니다.

UPDATE public.monitoring_retail_columns
SET is_editable = TRUE,
    updated_id = 'enable_sea_review_body_editing',
    updated_at = NOW()
WHERE product_line IN ('sea_ref', 'sea_ldy')
  AND LOWER(BTRIM(retailer)) IN ('bestbuy', 'lowes')
  AND column_name = 'detailed_review_content'
  AND is_active IS TRUE
  AND COALESCE(is_del, FALSE) IS FALSE;

-- 4개 행(SEA REF/LDY × Bestbuy/Lowes)이 모두 TRUE인지 확인합니다.
SELECT
    product_line,
    retailer,
    column_name,
    is_editable,
    is_active,
    COALESCE(is_del, FALSE) AS is_deleted
FROM public.monitoring_retail_columns
WHERE product_line IN ('sea_ref', 'sea_ldy')
  AND LOWER(BTRIM(retailer)) IN ('bestbuy', 'lowes')
  AND column_name = 'detailed_review_content'
ORDER BY product_line, LOWER(BTRIM(retailer));
