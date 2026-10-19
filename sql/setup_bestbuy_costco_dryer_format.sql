-- SEA Bestbuy and Costco LDY_DRYER format rules in monitoring metadata only.
-- Deploy the application change first. Source retail rows and other products are untouched.
BEGIN;

SELECT setval(pg_get_serial_sequence('public.monitoring_format_templates', 'id'),
              COALESCE((SELECT MAX(id) + 1 FROM public.monitoring_format_templates), 1), FALSE);
SELECT setval(pg_get_serial_sequence('public.monitoring_format_rules', 'id'),
              COALESCE((SELECT MAX(id) + 1 FROM public.monitoring_format_rules), 1), FALSE);

CREATE TEMP TABLE _dryer_format_templates (
    name text PRIMARY KEY, check_type text NOT NULL, pattern text, description text
) ON COMMIT DROP;
INSERT INTO _dryer_format_templates VALUES
 ('SEA_DRYER_ENUM', 'enum', NULL, 'Retailer-specific exact values'),
 ('SEA_DRYER_BESTBUY_ITEM', 'regex', $re$^[A-Z0-9]{10}$$re$, 'Bestbuy item identifier'),
 ('SEA_DRYER_COSTCO_ITEM', 'regex', $re$^[0-9]{9,10}$$re$, 'Costco item identifier'),
 ('SEA_DRYER_BESTBUY_URL', 'regex', $re$^https://www\.bestbuy\.com/product/\S+$$re$, 'Bestbuy product URL'),
 ('SEA_DRYER_COSTCO_URL', 'regex', $re$^https://www\.costco\.com/p/\S+$$re$, 'Costco product URL'),
 ('SEA_DRYER_BESTBUY_TIME', 'regex', $re$^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$$re$, 'Original Bestbuy collection timestamp'),
 ('SEA_DRYER_COSTCO_TIME', 'regex', $re$^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}[+-][0-9]{2}:[0-9]{2}$$re$, 'Original Costco timestamp with offset'),
 ('SEA_DRYER_BESTBUY_WEEK', 'regex', $re$^w(?:0?[1-9]|[1-4][0-9]|5[0-3])$$re$, 'Bestbuy week w1 through w53'),
 ('SEA_DRYER_COSTCO_WEEK', 'regex', $re$^[0-9]{4}-W(?:0[1-9]|[1-4][0-9]|5[0-3])$$re$, 'Costco YYYY-W01 through YYYY-W53'),
 ('SEA_DRYER_USD', 'regex', $re$^\$(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)(?:\.[0-9]{1,2})?$$re$, 'US dollar amount'),
 ('SEA_DRYER_COUNT', 'regex', $re$^(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)$$re$, 'Nonnegative integer count'),
 ('SEA_DRYER_BESTBUY_RATING', 'regex', $re$^(?:[0-4](?:\.[0-9]+)?|5(?:\.0+)?|Not yet reviewed)$$re$, 'Rating zero through five or Not yet reviewed'),
 ('SEA_DRYER_COSTCO_RATING', 'range_float', NULL, 'Rating zero through five'),
 ('SEA_DRYER_BESTBUY_CAPACITY', 'regex', $re$^[0-9]+(?:\.[0-9]+)?(?: cubic feet|Cu\.Ft\.)$$re$, 'Bestbuy cubic-feet capacity'),
 ('SEA_DRYER_COSTCO_CAPACITY', 'regex', $re$^[0-9]+(?:\.[0-9]+)? cu\.? ft\.$$re$, 'Costco cubic-feet capacity');

UPDATE public.monitoring_format_templates target
SET check_type = seed.check_type, pattern = seed.pattern,
    description = seed.description, is_active = TRUE,
    updated_id = 'setup_bestbuy_costco_dryer_format', updated_at = NOW()
FROM _dryer_format_templates seed WHERE target.name = seed.name;
INSERT INTO public.monitoring_format_templates
 (name, description, check_type, pattern, is_active,
  created_id, created_at, updated_id, updated_at)
SELECT seed.name, seed.description, seed.check_type, seed.pattern, TRUE,
       'setup_bestbuy_costco_dryer_format', NOW(),
       'setup_bestbuy_costco_dryer_format', NOW()
FROM _dryer_format_templates seed
WHERE NOT EXISTS (SELECT 1 FROM public.monitoring_format_templates target
                  WHERE target.name = seed.name);

CREATE TEMP TABLE _dryer_format_rules (
    account_name text, column_name text, template_name text,
    rule_value text, error_message text,
    PRIMARY KEY (account_name, column_name)
) ON COMMIT DROP;
WITH retailers(account_name, item_template, url_template, time_template,
               week_template, rating_template, capacity_template, loading_values) AS (
    VALUES
     ('Bestbuy', 'SEA_DRYER_BESTBUY_ITEM', 'SEA_DRYER_BESTBUY_URL',
      'SEA_DRYER_BESTBUY_TIME', 'SEA_DRYER_BESTBUY_WEEK',
      'SEA_DRYER_BESTBUY_RATING', 'SEA_DRYER_BESTBUY_CAPACITY', 'Frontload|Topload'),
     ('Costco', 'SEA_DRYER_COSTCO_ITEM', 'SEA_DRYER_COSTCO_URL',
      'SEA_DRYER_COSTCO_TIME', 'SEA_DRYER_COSTCO_WEEK',
      'SEA_DRYER_COSTCO_RATING', 'SEA_DRYER_COSTCO_CAPACITY', 'Front Load')
)
INSERT INTO _dryer_format_rules
SELECT retailer.account_name, rule.column_name, rule.template_name,
       rule.rule_value, rule.error_message
FROM retailers retailer
CROSS JOIN LATERAL (VALUES
 ('account_name', 'SEA_DRYER_ENUM', retailer.account_name, 'Unexpected retailer'),
 ('country', 'SEA_DRYER_ENUM', 'SEA', 'Country must be SEA'),
 ('item', retailer.item_template, NULL, 'Invalid item identifier'),
 ('product_url', retailer.url_template, NULL, 'Invalid product URL'),
 ('crawl_datetime', retailer.time_template, NULL, 'Invalid original collection timestamp'),
 ('calendar_week', retailer.week_template, NULL, 'Invalid calendar week'),
 ('final_sku_price', 'SEA_DRYER_USD', NULL, 'Invalid US dollar price'),
 ('original_sku_price', 'SEA_DRYER_USD', NULL, 'Invalid US dollar original price'),
 ('savings', 'SEA_DRYER_USD', NULL, 'Invalid US dollar saving'),
 ('star_rating', retailer.rating_template,
  CASE WHEN retailer.account_name = 'Costco' THEN '0~5' ELSE NULL END,
  'Invalid star rating'),
 ('count_of_star_ratings', 'SEA_DRYER_COUNT', NULL, 'Invalid rating count'),
 ('count_of_reviews', 'SEA_DRYER_COUNT', NULL, 'Invalid review count'),
 ('capacity', retailer.capacity_template, NULL, 'Invalid cubic-feet capacity'),
 ('loading_type', 'SEA_DRYER_ENUM', retailer.loading_values, 'Invalid loading type')
) rule(column_name, template_name, rule_value, error_message);

UPDATE public.monitoring_format_rules target
SET template_id = template.id, rule_value = seed.rule_value,
    extra_allowed = NULL, forbidden_chars = NULL,
    error_message = seed.error_message, is_active = TRUE, is_del = FALSE,
    updated_id = 'setup_bestbuy_costco_dryer_format', updated_at = NOW()
FROM _dryer_format_rules seed
JOIN public.monitoring_format_templates template ON template.name = seed.template_name
WHERE target.table_name = 'ldy_dryer_retail'
  AND LOWER(TRIM(target.account_name)) = LOWER(seed.account_name)
  AND target.column_name = seed.column_name;
INSERT INTO public.monitoring_format_rules
 (table_name, column_name, account_name, template_id, rule_value, error_message,
  is_active, is_del, created_id, created_at, updated_id, updated_at)
SELECT 'ldy_dryer_retail', seed.column_name, seed.account_name, template.id,
       seed.rule_value, seed.error_message, TRUE, FALSE,
       'setup_bestbuy_costco_dryer_format', NOW(),
       'setup_bestbuy_costco_dryer_format', NOW()
FROM _dryer_format_rules seed
JOIN public.monitoring_format_templates template ON template.name = seed.template_name
WHERE NOT EXISTS (SELECT 1 FROM public.monitoring_format_rules target
                  WHERE target.table_name = 'ldy_dryer_retail'
                    AND LOWER(TRIM(target.account_name)) = LOWER(seed.account_name)
                    AND target.column_name = seed.column_name);

COMMIT;

-- Expected: 14 active rules per retailer.
SELECT account_name, COUNT(*) AS active_format_rules
FROM public.monitoring_format_rules
WHERE table_name = 'ldy_dryer_retail'
  AND LOWER(TRIM(account_name)) IN ('bestbuy', 'costco')
  AND is_active = TRUE AND is_del = FALSE
GROUP BY account_name ORDER BY account_name;
