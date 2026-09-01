-- SEA REF/LDY Layer 2 format rules (idempotent).
-- Run this file in PostgreSQL after deploying the application.
-- It is safe to run again: matching templates/rules are updated and only
-- missing rows are inserted.  The file intentionally does not open a
-- transaction so it also works when DBeaver already has one in progress.

SELECT setval(
    pg_get_serial_sequence('public.monitoring_format_templates', 'id'),
    COALESCE((
        SELECT MAX(id) + 1
        FROM public.monitoring_format_templates
    ), 1),
    FALSE
);

WITH seed (name, description, check_type, pattern) AS (
    VALUES
        ('SEA_APPLIANCE_ENUM',
         'SEA REF/LDY allowed values', 'enum', NULL),
        ('SEA_APPLIANCE_ALNUM_ITEM',
         'Bestbuy item: letters and numbers only', 'regex',
         '^[A-Za-z0-9]+$'),
        ('SEA_APPLIANCE_NUMERIC_ITEM',
         'Lowes item: digits only', 'regex', '^[0-9]+$'),
        ('SEA_APPLIANCE_BESTBUY_URL',
         'Bestbuy product URL', 'regex',
         E'^https?://([A-Za-z0-9-]+\\.)*bestbuy\\.com(/|$)'),
        ('SEA_APPLIANCE_LOWES_URL',
         'Lowes product URL', 'regex',
         E'^https?://([A-Za-z0-9-]+\\.)*lowes\\.com(/|$)'),
        ('SEA_APPLIANCE_NONNEGATIVE_COUNT',
         'Non-negative integer; thousands comma is allowed', 'regex',
         '^(0|[1-9][0-9]*|[1-9][0-9]{0,2}(,[0-9]{3})+)$'),
        ('SEA_APPLIANCE_RATING',
         'Star rating from 0 through 5', 'range_float', NULL),
        ('SEA_APPLIANCE_USD',
         'US dollar amount', 'regex',
         E'^\\$[0-9]+(,[0-9]{3})*(\\.[0-9]{1,2})?$'),
        ('SEA_APPLIANCE_REVIEW_BODY',
         'Review body begins with review1', 'starts_with', NULL),
        ('SEA_APPLIANCE_WEEK',
         'Calendar week w1 through w52', 'regex',
         '^[wW]0?([1-9]|[1-4][0-9]|5[0-2])$'),
        ('SEA_APPLIANCE_BESTBUY_CAPACITY',
         'Bestbuy capacity, for example 22.9 cubic feet', 'regex',
         '^(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+) cubic feet$'),
        ('SEA_APPLIANCE_LOWES_CAPACITY',
         'Lowes capacity, for example 22.9 Cu.Feet', 'regex',
         E'^(?:[0-9]+(?:\\.[0-9]+)?|\\.[0-9]+) Cu\\.Feet$')
), updated AS (
    UPDATE public.monitoring_format_templates target
    SET description = seed.description,
        check_type = seed.check_type,
        pattern = seed.pattern,
        is_active = TRUE,
        updated_id = 'seed_sea_format',
        updated_at = NOW()
    FROM seed
    WHERE target.name = seed.name
    RETURNING target.name
)
INSERT INTO public.monitoring_format_templates (
    name, description, check_type, pattern, is_active,
    created_id, created_at, updated_id, updated_at
)
SELECT
    seed.name, seed.description, seed.check_type, seed.pattern, TRUE,
    'seed_sea_format', NOW(), 'seed_sea_format', NOW()
FROM seed
WHERE NOT EXISTS (
    SELECT 1
    FROM public.monitoring_format_templates existing
    WHERE existing.name = seed.name
);

SELECT setval(
    pg_get_serial_sequence('public.monitoring_format_rules', 'id'),
    COALESCE((
        SELECT MAX(id) + 1
        FROM public.monitoring_format_rules
    ), 1),
    FALSE
);

WITH products (
    table_name, product_value, capacity_column, loading_type_column
) AS (
    VALUES
        ('ref_retail_com', 'REF', 'ref_capacity', NULL::text),
        ('ldy_retail_com', 'LDY', 'ldy_capacity', 'ldy_loading_type')
), retailers (
    account_name, item_template, url_template, capacity_template
) AS (
    VALUES
        ('Bestbuy', 'SEA_APPLIANCE_ALNUM_ITEM',
         'SEA_APPLIANCE_BESTBUY_URL',
         'SEA_APPLIANCE_BESTBUY_CAPACITY'),
        ('Lowes', 'SEA_APPLIANCE_NUMERIC_ITEM',
         'SEA_APPLIANCE_LOWES_URL',
         'SEA_APPLIANCE_LOWES_CAPACITY')
), common_seed AS (
    SELECT
        product.table_name,
        retailer.account_name,
        rule.column_name,
        rule.template_name,
        rule.rule_value,
        CASE
            WHEN rule.column_name = 'star_rating'
             AND retailer.account_name = 'Bestbuy'
            THEN 'Not yet reviewed'
            ELSE NULL
        END AS extra_allowed,
        rule.error_message
    FROM products product
    CROSS JOIN retailers retailer
    CROSS JOIN LATERAL (
        VALUES
            ('account_name', 'SEA_APPLIANCE_ENUM',
             retailer.account_name,
             '허용된 리테일러명이 아닙니다.'),
            ('country', 'SEA_APPLIANCE_ENUM', 'SEA',
             'country는 SEA여야 합니다.'),
            ('product', 'SEA_APPLIANCE_ENUM', product.product_value,
             'product가 테이블 제품군과 일치하지 않습니다.'),
            ('page_type', 'SEA_APPLIANCE_ENUM', 'main|bsr',
             'page_type은 main 또는 bsr이어야 합니다.'),
            ('count_of_reviews', 'SEA_APPLIANCE_NONNEGATIVE_COUNT', NULL,
             'count_of_reviews는 0 이상의 정수여야 합니다.'),
            ('count_of_star_ratings', 'SEA_APPLIANCE_NONNEGATIVE_COUNT', NULL,
             'count_of_star_ratings는 0 이상의 정수여야 합니다.'),
            ('star_rating', 'SEA_APPLIANCE_RATING', '0~5',
             'star_rating은 0~5 범위여야 합니다.'),
            ('final_sku_price', 'SEA_APPLIANCE_USD', NULL,
             'final_sku_price는 $ 금액 형식이어야 합니다.'),
            ('original_sku_price', 'SEA_APPLIANCE_USD', NULL,
             'original_sku_price는 $ 금액 형식이어야 합니다.'),
            ('savings', 'SEA_APPLIANCE_USD', NULL,
             'savings는 $ 금액 형식이어야 합니다.'),
            ('detailed_review_content', 'SEA_APPLIANCE_REVIEW_BODY',
             'review1 - ',
             '리뷰본문은 "review1 - "로 시작해야 합니다.'),
            ('calendar_week', 'SEA_APPLIANCE_WEEK', NULL,
             'calendar_week는 w1~w52 형식이어야 합니다.')
    ) AS rule(column_name, template_name, rule_value, error_message)
), retailer_seed AS (
    SELECT
        product.table_name,
        retailer.account_name,
        'item'::text AS column_name,
        retailer.item_template AS template_name,
        NULL::text AS rule_value,
        NULL::text AS extra_allowed,
        CASE retailer.account_name
            WHEN 'Bestbuy' THEN 'Bestbuy item은 영문/숫자 형식이어야 합니다.'
            ELSE 'Lowes item은 숫자 형식이어야 합니다.'
        END AS error_message
    FROM products product
    CROSS JOIN retailers retailer

    UNION ALL

    SELECT
        product.table_name,
        retailer.account_name,
        'product_url',
        retailer.url_template,
        NULL,
        NULL,
        CASE retailer.account_name
            WHEN 'Bestbuy' THEN 'Bestbuy 상품 URL 형식이 아닙니다.'
            ELSE 'Lowes 상품 URL 형식이 아닙니다.'
        END
    FROM products product
    CROSS JOIN retailers retailer

    UNION ALL

    SELECT
        product.table_name,
        retailer.account_name,
        product.capacity_column,
        retailer.capacity_template,
        NULL,
        NULL,
        CASE retailer.account_name
            WHEN 'Bestbuy' THEN '용량은 "숫자 cubic feet" 형식이어야 합니다.'
            ELSE '용량은 "숫자 Cu.Feet" 형식이어야 합니다.'
        END
    FROM products product
    CROSS JOIN retailers retailer

    UNION ALL

    SELECT
        product.table_name,
        retailer.account_name,
        product.loading_type_column,
        'SEA_APPLIANCE_ENUM',
        'Front load|Top load',
        NULL,
        'ldy_loading_type은 Front load 또는 Top load여야 합니다.'
    FROM products product
    CROSS JOIN retailers retailer
    WHERE product.loading_type_column IS NOT NULL
), rule_seed AS (
    SELECT * FROM common_seed
    UNION ALL
    SELECT * FROM retailer_seed
), resolved AS (
    SELECT
        seed.*,
        template.id AS template_id
    FROM rule_seed seed
    JOIN public.monitoring_format_templates template
      ON template.name = seed.template_name
), updated AS (
    UPDATE public.monitoring_format_rules target
    SET template_id = seed.template_id,
        rule_value = seed.rule_value,
        extra_allowed = seed.extra_allowed,
        forbidden_chars = NULL,
        error_message = seed.error_message,
        is_active = TRUE,
        is_del = FALSE,
        updated_id = 'seed_sea_format',
        updated_at = NOW()
    FROM resolved seed
    WHERE target.table_name = seed.table_name
      AND target.column_name = seed.column_name
      AND LOWER(TRIM(target.account_name)) =
          LOWER(TRIM(seed.account_name))
    RETURNING target.id
)
INSERT INTO public.monitoring_format_rules (
    table_name, column_name, account_name, template_id,
    rule_value, extra_allowed, forbidden_chars, error_message,
    is_active, is_del, created_id, created_at, updated_id, updated_at
)
SELECT
    seed.table_name, seed.column_name, seed.account_name, seed.template_id,
    seed.rule_value, seed.extra_allowed, NULL, seed.error_message,
    TRUE, FALSE, 'seed_sea_format', NOW(), 'seed_sea_format', NOW()
FROM resolved seed
WHERE NOT EXISTS (
    SELECT 1
    FROM public.monitoring_format_rules existing
    WHERE existing.table_name = seed.table_name
      AND existing.column_name = seed.column_name
      AND LOWER(TRIM(existing.account_name)) =
          LOWER(TRIM(seed.account_name))
);

-- Verification: expected result is 4 rows.
SELECT
    table_name,
    account_name,
    COUNT(*) AS active_rule_count,
    STRING_AGG(column_name, ', ' ORDER BY column_name) AS format_columns
FROM public.monitoring_format_rules
WHERE table_name IN ('ref_retail_com', 'ldy_retail_com')
  AND LOWER(account_name) IN ('bestbuy', 'lowes')
  AND is_active = TRUE
  AND is_del = FALSE
GROUP BY table_name, account_name
ORDER BY table_name, account_name;
