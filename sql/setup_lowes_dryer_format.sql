-- Monitoring metadata only: SEA Lowes LDY_DRYER format rules.
-- Deploy application code first. This does not update public.ldy_dryer_retail.
-- Re-run safely after reviewing collected Lowes value shapes.
BEGIN;

SELECT setval(pg_get_serial_sequence('public.monitoring_format_templates', 'id'),
              COALESCE((SELECT MAX(id) + 1 FROM public.monitoring_format_templates), 1), FALSE);
SELECT setval(pg_get_serial_sequence('public.monitoring_format_rules', 'id'),
              COALESCE((SELECT MAX(id) + 1 FROM public.monitoring_format_rules), 1), FALSE);

CREATE TEMP TABLE _lowes_dryer_templates (
    name text PRIMARY KEY, check_type text, pattern text, description text
) ON COMMIT DROP;
INSERT INTO _lowes_dryer_templates VALUES
 ('SEA_LOWES_DRYER_ENUM', 'enum', NULL, 'Allowed Lowes dryer value'),
 ('SEA_LOWES_DRYER_ITEM', 'regex', '^[1-9][0-9]*$', 'Positive numeric item'),
 ('SEA_LOWES_DRYER_URL', 'regex',
  '^https?://([A-Za-z0-9-]+\.)*lowes\.com(/|$)', 'Lowes product URL'),
 ('SEA_LOWES_DRYER_WEEK', 'regex',
  '^[wW]0?([1-9]|[1-4][0-9]|5[0-3])$', 'Week W1 through W53'),
 ('SEA_LOWES_DRYER_TIMESTAMP', 'regex',
  '^[0-9]{4}-[0-9]{2}-[0-9]{2}(?:[T ][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})?)?$',
  'Original collection date or ISO timestamp'),
 ('SEA_LOWES_DRYER_USD', 'regex',
  '^\$[0-9]+(,[0-9]{3})*(\.[0-9]{1,2})?$', 'US dollar amount'),
 ('SEA_LOWES_DRYER_COUNT', 'regex',
  '^(0|[1-9][0-9]*|[1-9][0-9]{0,2}(,[0-9]{3})+)$', 'Nonnegative integer count'),
 ('SEA_LOWES_DRYER_RATING', 'range_float', NULL, 'Rating between zero and five'),
 ('SEA_LOWES_DRYER_CAPACITY', 'regex',
  '^(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+) (?:Cu\.Feet|cu ft)$',
  'Dryer capacity in cubic feet');

UPDATE public.monitoring_format_templates target
SET check_type = seed.check_type, pattern = seed.pattern,
    description = seed.description, is_active = TRUE,
    updated_id = 'setup_lowes_dryer_format', updated_at = NOW()
FROM _lowes_dryer_templates seed WHERE target.name = seed.name;
INSERT INTO public.monitoring_format_templates
 (name, description, check_type, pattern, is_active,
  created_id, created_at, updated_id, updated_at)
SELECT seed.name, seed.description, seed.check_type, seed.pattern, TRUE,
       'setup_lowes_dryer_format', NOW(), 'setup_lowes_dryer_format', NOW()
FROM _lowes_dryer_templates seed
WHERE NOT EXISTS (SELECT 1 FROM public.monitoring_format_templates target
                  WHERE target.name = seed.name);

CREATE TEMP TABLE _lowes_dryer_rules (
    column_name text PRIMARY KEY, template_name text, rule_value text, error_message text
) ON COMMIT DROP;
INSERT INTO _lowes_dryer_rules VALUES
 ('account_name', 'SEA_LOWES_DRYER_ENUM', 'Lowes', 'account_name은 Lowes여야 합니다.'),
 ('country', 'SEA_LOWES_DRYER_ENUM', 'SEA', 'country는 SEA여야 합니다.'),
 ('item', 'SEA_LOWES_DRYER_ITEM', NULL, 'item은 1 이상의 숫자여야 합니다.'),
 ('product_url', 'SEA_LOWES_DRYER_URL', NULL, 'Lowes 상품 URL 형식이어야 합니다.'),
 ('crawl_datetime', 'SEA_LOWES_DRYER_TIMESTAMP', NULL, '수집시각은 날짜 또는 ISO 시각 형식이어야 합니다.'),
 ('calendar_week', 'SEA_LOWES_DRYER_WEEK', NULL, 'calendar_week는 W1~W53 형식이어야 합니다.'),
 ('final_sku_price', 'SEA_LOWES_DRYER_USD', NULL, '최종가는 달러 금액 형식이어야 합니다.'),
 ('original_sku_price', 'SEA_LOWES_DRYER_USD', NULL, '원가는 달러 금액 형식이어야 합니다.'),
 ('savings', 'SEA_LOWES_DRYER_USD', NULL, 'savings는 달러 금액 형식이어야 합니다.'),
 ('star_rating', 'SEA_LOWES_DRYER_RATING', '0~5', '별점은 0~5 사이여야 합니다.'),
 ('count_of_star_ratings', 'SEA_LOWES_DRYER_COUNT', NULL, '별점 수는 0 이상의 정수여야 합니다.'),
 ('count_of_reviews', 'SEA_LOWES_DRYER_COUNT', NULL, '리뷰 수는 0 이상의 정수여야 합니다.'),
 ('capacity', 'SEA_LOWES_DRYER_CAPACITY', NULL, '용량은 7.4 Cu.Feet 또는 7.4 cu ft 형식이어야 합니다.'),
 ('loading_type', 'SEA_LOWES_DRYER_ENUM', 'Front load|Top load|Front Load|Top Load',
  'loading_type은 Front/Top Load여야 합니다.');

UPDATE public.monitoring_format_rules target
SET template_id = template.id, rule_value = seed.rule_value,
    extra_allowed = NULL, forbidden_chars = NULL,
    error_message = seed.error_message, is_active = TRUE, is_del = FALSE,
    updated_id = 'setup_lowes_dryer_format', updated_at = NOW()
FROM _lowes_dryer_rules seed
JOIN public.monitoring_format_templates template ON template.name = seed.template_name
WHERE target.table_name = 'ldy_dryer_retail'
  AND LOWER(TRIM(target.account_name)) = 'lowes'
  AND target.column_name = seed.column_name;
INSERT INTO public.monitoring_format_rules
 (table_name, column_name, account_name, template_id, rule_value, error_message,
  is_active, is_del, created_id, created_at, updated_id, updated_at)
SELECT 'ldy_dryer_retail', seed.column_name, 'Lowes', template.id,
       seed.rule_value, seed.error_message, TRUE, FALSE,
       'setup_lowes_dryer_format', NOW(), 'setup_lowes_dryer_format', NOW()
FROM _lowes_dryer_rules seed
JOIN public.monitoring_format_templates template ON template.name = seed.template_name
WHERE NOT EXISTS (SELECT 1 FROM public.monitoring_format_rules target
                  WHERE target.table_name = 'ldy_dryer_retail'
                    AND LOWER(TRIM(target.account_name)) = 'lowes'
                    AND target.column_name = seed.column_name);

-- loading_type remains optional for NULL checks, but can be corrected if malformed.
UPDATE public.monitoring_retail_columns
SET is_editable = TRUE, updated_id = 'setup_lowes_dryer_format', updated_at = NOW()
WHERE product_line = 'sea_ldy_dryer' AND LOWER(TRIM(retailer)) = 'lowes'
  AND column_name = 'loading_type';

COMMIT;

-- Expected: 14 active Lowes rules. Check HomeDepot's existing 10 separately.
SELECT account_name, COUNT(*) AS active_format_rules
FROM public.monitoring_format_rules
WHERE table_name = 'ldy_dryer_retail'
  AND LOWER(TRIM(account_name)) IN ('lowes', 'homedepot')
  AND is_active = TRUE AND is_del = FALSE
GROUP BY account_name ORDER BY account_name;
