-- Amazon savings: 1%..100% integer syntax; missing at >= 0.5% discount is an error.
-- Apply with the associated SEG/SIEL application changes. No source data writes.
-- SEA Amazon is registered for TV only; REF/LDY have no Amazon source.
BEGIN;

INSERT INTO public.monitoring_format_templates (
    name, description, check_type, pattern, is_active,
    created_id, created_at, updated_id, updated_at
)
SELECT 'AMAZON_SAVINGS_PERCENT', 'Amazon 1%~100% 정수 할인율 (0% 제외)',
       'regex', '^([1-9][0-9]?|100)%$', TRUE,
       'amazon_savings_percent', NOW(), 'amazon_savings_percent', NOW()
WHERE NOT EXISTS (
    SELECT 1 FROM public.monitoring_format_templates
    WHERE name = 'AMAZON_SAVINGS_PERCENT'
);

UPDATE public.monitoring_format_templates
SET check_type = 'regex', pattern = '^([1-9][0-9]?|100)%$', is_active = TRUE,
    description = 'Amazon 1%~100% 정수 할인율 (0% 제외)',
    updated_id = 'amazon_savings_percent', updated_at = NOW()
WHERE name = 'AMAZON_SAVINGS_PERCENT';

UPDATE public.monitoring_format_rules
SET template_id = (SELECT id FROM public.monitoring_format_templates
                   WHERE name = 'AMAZON_SAVINGS_PERCENT'),
    rule_value = NULL, extra_allowed = NULL, forbidden_chars = NULL,
    error_message = 'savings는 1%~100% 정수 할인율이어야 합니다. 0%는 허용하지 않습니다.',
    is_active = TRUE, is_del = FALSE,
    updated_id = 'amazon_savings_percent', updated_at = NOW()
WHERE table_name = 'tv_retail_com' AND column_name = 'savings'
  AND LOWER(BTRIM(account_name)) = 'amazon';

INSERT INTO public.monitoring_format_rules (
    table_name, column_name, account_name, template_id,
    rule_value, extra_allowed, forbidden_chars, error_message,
    is_active, is_del, created_id, created_at, updated_id, updated_at
)
SELECT 'tv_retail_com', 'savings', 'Amazon', id,
       NULL, NULL, NULL,
       'savings는 1%~100% 정수 할인율이어야 합니다. 0%는 허용하지 않습니다.',
       TRUE, FALSE, 'amazon_savings_percent', NOW(), 'amazon_savings_percent', NOW()
FROM public.monitoring_format_templates template
WHERE template.name = 'AMAZON_SAVINGS_PERCENT'
  AND NOT EXISTS (
      SELECT 1 FROM public.monitoring_format_rules
      WHERE table_name = 'tv_retail_com' AND column_name = 'savings'
        AND LOWER(BTRIM(account_name)) = 'amazon'
  );

-- New SEA TV query. CASE guards prevent malformed prices from causing cast errors.
-- Numeric multiplication preserves the exact 0.5% boundary without rounding.
CREATE TEMP TABLE _amazon_savings_rule ON COMMIT DROP AS
SELECT $query$
SELECT id, item, account_name, page_type, crawl_datetime,
       final_sku_price, original_sku_price, savings, product_url
FROM (
    SELECT source.*,
           CASE WHEN BTRIM(original_sku_price) ~ '^[$]?[0-9]+(,[0-9]{3})*([.][0-9]+)?$'
                THEN REPLACE(REPLACE(BTRIM(original_sku_price), '$', ''), ',', '')::numeric END AS original_price,
           CASE WHEN BTRIM(final_sku_price) ~ '^[$]?[0-9]+(,[0-9]{3})*([.][0-9]+)?$'
                THEN REPLACE(REPLACE(BTRIM(final_sku_price), '$', ''), ',', '')::numeric END AS final_price
    FROM {table} source
    WHERE DATE({date_col}) = %s
      AND account_name = 'Amazon'
      AND LOWER(BTRIM(COALESCE(savings::text, ''))) IN ('', '-', 'null', 'none', 'n/a')
) priced
WHERE original_price > 0 AND final_price >= 0
  AND (original_price - final_price) * 200 >= original_price
$query$::text AS query;

UPDATE public.monitoring_validation_rules
SET detail_name = '할인율 0.5% 이상 시 savings 확인',
    field1 = 'savings', field2 = 'final_sku_price|original_sku_price',
    validation_type = 'savings_missing',
    error_message = '계산 할인율이 0.5% 이상인데 savings가 없습니다. 표시된 할인율과 계산값의 일치는 검사하지 않습니다.',
    select_fields = 'final_sku_price|original_sku_price|savings',
    query = (SELECT query FROM _amazon_savings_rule), is_active = TRUE
WHERE rule_type = 'crossfield' AND section_code = 'tv_retail'
  AND table_name = 'tv_retail_com' AND retailer = 'Amazon'
  AND detail_code = 'amazon_savings_missing';

INSERT INTO public.monitoring_validation_rules (
    rule_type, section_code, section_name, detail_code, detail_name,
    table_name, date_column, product_line, retailer, field1, field2,
    validation_type, error_message, select_fields, query, sort_order,
    is_active, created_at, created_id
)
SELECT 'crossfield', 'tv_retail', 'TV Retail', 'amazon_savings_missing',
       '할인율 0.5% 이상 시 savings 확인', 'tv_retail_com', 'crawl_datetime', 'TV',
       'Amazon', 'savings', 'final_sku_price|original_sku_price', 'savings_missing',
       '계산 할인율이 0.5% 이상인데 savings가 없습니다. 표시된 할인율과 계산값의 일치는 검사하지 않습니다.',
       'final_sku_price|original_sku_price|savings', query, 140, TRUE, NOW(),
       'amazon_savings_percent'
FROM _amazon_savings_rule
WHERE NOT EXISTS (
    SELECT 1 FROM public.monitoring_validation_rules
    WHERE rule_type = 'crossfield' AND section_code = 'tv_retail'
      AND table_name = 'tv_retail_com' AND retailer = 'Amazon'
      AND detail_code = 'amazon_savings_missing'
);

-- SEG/SIEL execute application rules, so update their metadata only.
UPDATE public.monitoring_validation_rules
SET is_active = FALSE
WHERE rule_type = 'crossfield'
  AND (section_code, table_name) IN (
      ('seg_tv_retail', 'dx_seg.dx_seg_tv_retail_com'),
      ('seg_ref_retail', 'dx_seg.dx_seg_ref_retail_com'),
      ('seg_ldy_retail', 'dx_seg.dx_seg_ldy_retail_com')
  )
  AND LOWER(BTRIM(retailer)) IN ('amazon', 'all')
  AND validation_type IN ('savings_amount_match', 'savings_amount');

UPDATE public.monitoring_validation_rules
SET error_message = '할인 가격인데 savings가 없습니다. Amazon은 계산 할인율 0.5% 이상, Mediamarkt는 10% 초과일 때 검사합니다.'
WHERE rule_type = 'crossfield'
  AND (section_code, table_name) IN (
      ('seg_tv_retail', 'dx_seg.dx_seg_tv_retail_com'),
      ('seg_ref_retail', 'dx_seg.dx_seg_ref_retail_com'),
      ('seg_ldy_retail', 'dx_seg.dx_seg_ldy_retail_com')
  )
  AND LOWER(BTRIM(retailer)) IN ('amazon', 'all')
  AND validation_type IN ('savings_missing', 'savings_required');

UPDATE public.monitoring_validation_rules
SET error_message = '숫자 원가가 판매가보다 큰데 savings가 없습니다. Amazon은 계산 할인율 0.5% 이상일 때 검사합니다.'
WHERE rule_type = 'crossfield'
  AND (section_code, table_name) IN (
      ('siel_tv_retail', 'dx_siel.dx_siel_tv_retail_com'),
      ('siel_ref_retail', 'dx_siel.dx_siel_ref_retail_com'),
      ('siel_ldy_retail', 'dx_siel.dx_siel_ldy_retail_com')
  )
  AND LOWER(BTRIM(retailer)) IN ('amazon', 'all')
  AND validation_type IN ('savings_missing', 'savings_required');

COMMIT;
