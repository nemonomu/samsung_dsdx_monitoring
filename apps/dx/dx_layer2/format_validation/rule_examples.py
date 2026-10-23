"""Display-only examples, checked against the existing validation rules."""
import re
from decimal import Decimal, InvalidOperation
from apps.common.retail_columns import _apply_validation_rule


FIELD_VALUES = {
    'final_sku_price': ('$999', '$1,299', '$1,299.99', '999,00 €', '1.299,99 €',
                        'R$2.199,00', '₹10,999', '฿12,990', '12,990', '12990', '£1399.00', '£1,399.00'),
    'star_rating': ('4.3', '0', '5', '4.5', '4,5'),
    'calendar_week': ('W1', 'W42', 'W53', 'w1', 'w42', '2026-W42'),
    'crawl_datetime': ('2026-10-20T01:09:37+09:00', '2026-10-20 09:30:00'),
    'item': ('123456', 'A12345', 'B0ABC12345'),
    'sku': ('ABC123', 'MODEL-123'),
    'country': ('SEA', 'SEDA', 'SIEL', 'SEG', 'SEM', 'TSE', 'SEIB', 'SEUK'),
    'product': ('TV', 'REF', 'LDY', 'LDY_DRYER'),
    'page_type': ('main', 'bsr', 'MAIN', 'BSR'),
    'screen_size': ('55 inches', '65 inches', '55 inch', '55 in.', '55"', '55 Polegadas', '109 cm (43 inch)', '55'),
    'estimated_annual_electricity_use': ('164.25 Kilowatt Hours', '141 Kilowatts', '100 W', '0.5 W (Standby)'),
    'model_year': ('2025', '2026'),
    'number_of_units_purchased_past_month': ('100+ bought in past month', '1K+ bought in past month',
                                            '100+ gekauft Mal im letzten Monat'),
    'ref_capacity': ('231 L', '300L', '20 cu ft', '20 cubic feet', '20 Cu.Feet', '300 liters'),
    'capacity': ('8 kg', '10.5 kg', '10.5kg, 6kg', '4.5 cu ft', '4.5 cubic feet', '4.5 Cu.Feet'),
    'loading_type': ('Front Load', 'Top Load', 'Front loading'),
    'ref_refrigerator_type': ('Single Door', 'Side-by-Side', 'French Door', 'Top Mount'),
    'savings': ('10%', '25%', '100%', '-30%', '$100', '$8,200 (43%)', '฿3,000 (-3%)', '£400.99'),
    'sku_status': ('Sponsored', 'New', 'NEW'),
    'discount_type': ('Hot Deal', 'Super Deals', 'Coupon R$ 100 off', 'USE O CUPOM DESCONTO 10%',
                      'Exclusive Appliance Bundle', '$100 Instant Savings', 'Buy More, Save More'),
    'sku_popularity': ('Bestseller', "Flipkart's Choice", 'Trending'),
    'available_quantity_for_purchase': ('Only few left', 'Only 2 left', 'Nur noch 2 auf Lager', '2'),
    'pick_up_availability': ('Pickup Ready Today', 'Pick up in store',
                             'Pick up in store starting tomorrow', 'Fast pickup in 2h',
                             'Pick up today', 'Pick up tomorrow'),
    'delivery_availability': ('Receive today', 'Receive tomorrow', 'Receive within 2 business days',
                              'Receive by Tuesday, October 20', 'Normal by Tuesday, October 20',
                              'Delivery by Wednesday, 23 Sep', 'Delivery unavailable for this ZIP code',
                              'FREE delivery Today.', 'FREE delivery Wednesday, 23 September.',
                              'FREE delivery Saturday, September 26th', 'Delivery Tomorrow',
                              'Delivery Tue, Oct 20', 'Delivery as soon as Tue, Oct 20'),
    'fastest_delivery': ('Or fastest delivery Friday, September 25th',
                        'fastest delivery Today by 1 pm. Order within 7 hrs.'),
    'detailed_review_content': ('review1 - Great product', 'review1 - Great product|||review2 - Easy to use'),
    'recommendation_intent': ('95% Recommend this product', '95% would recommend to a friend'),
}
FIELD_ALIASES = {
    'original_sku_price': 'final_sku_price', 'crawl_strdatetime': 'crawl_datetime',
    'ldy_capacity': 'capacity', 'ldy_loading_type': 'loading_type',
    'calender_week': 'calendar_week', 'week': 'calendar_week',
}


def candidates(field, pattern='', retailer=''):
    """Candidates are never shown until the caller's actual validator accepts."""
    text = str(pattern or '')
    literals = [text, *re.split(r' / | \| |\n|, (?=[A-Za-z])', text)]
    literals = [re.sub(r' 등 .*$', '', value).strip().strip('"') for value in literals]
    replacements = {'{ASIN}': 'B0ABC12345', '{상품명}': 'sample-tv', '{상품키}': 'itm123456',
                    '{상품 slug 또는 번호}': '123456', '...': 'sample-product'}
    for old, new in replacements.items():
        literals = [value.replace(old, new) for value in literals]
    values = list(FIELD_VALUES.get(FIELD_ALIASES.get(field, field), ()))
    if field == 'account_name':
        values = [retailer, retailer.replace(' ', '')]
    if field == 'product_url':
        values = []  # Prefer the source's documented domain, never another retailer's.
        literals += [
            'https://www.magazineluiza.com.br/sample-product/p/123456',
            'https://www.casasbahia.com.br/sample-product/123456/p/123456',
            'https://www.lowes.com/pd/sample-product/123456',
            'https://www.bestbuy.com/site/sample-product/123456.p',
        ]
    literals = [value for value in literals if not re.search(r'[가-힣]', value)
                and not value.startswith('^') and not value.endswith('$')]
    return list(dict.fromkeys(value for value in [*literals, *values, '1', '10', '100', '0', '4.5']
                              if value and len(value) <= 250))


def checked_examples(field, pattern, accepts, retailer=''):
    examples = []
    for value in candidates(field, pattern, retailer):
        if accepts(value):
            examples.append(value)
        if len(examples) == 3:
            break
    return examples


def static_rules(rules, evaluate, retailer):
    result = []
    for rule in rules:
        field = rule['field']
        examples = checked_examples(
            field, rule.get('pattern', ''),
            lambda value: field not in evaluate({field: value}), retailer,
        )
        result.append({**rule, 'examples': examples})
    return {'rules': result}


def database_examples(row):
    """Use template semantics, without altering any stored rule or approval."""
    field = row['column_name']
    kind = row.get('check_type') or ''
    value = str(row.get('rule_value') or '')
    pattern = row.get('pattern') or value
    extra = [part.strip() for part in str(row.get('extra_allowed') or '').split('|') if part.strip()]
    allowed = [part.strip() for part in value.split('|') if part.strip()]
    choices = []
    if kind == 'enum':
        choices = allowed
    elif kind in ('range', 'range_float', 'min'):
        try:
            parts = value.split('~')
            start = Decimal(parts[0])
            end = Decimal(parts[1]) if len(parts) == 2 else start + 10
            choices = [str(start), str((start + end) // 2), str(end)]
        except (InvalidOperation, ValueError):
            pass
    elif kind == 'starts_with':
        choices = [value + '123', value + '456']
    elif kind == 'separator_count':
        parts = value.split('~')
        if len(parts) == 2 and parts[1].isdigit() and 0 <= int(parts[1]) <= 10:
            choices = [parts[0].join(f'값{i + 1}' for i in range(int(parts[1]) + 1))]
    rule = {'type': kind, 'rule': pattern if kind in ('regex', 'regex_clean') else value,
            'allowed': allowed if kind == 'enum' or row.get('pattern') else [],
            'forbidden': [part for part in str(row.get('forbidden_chars') or '').split('|') if part],
            'error': ''}
    examples = []
    for candidate in [*choices, *candidates(field, pattern), *extra]:
        if candidate in examples:
            continue
        try:
            passed = (candidate in extra or
                      _apply_validation_rule(candidate, rule, field) is True)
        except (ValueError, TypeError, re.error):
            passed = False
        if passed:
            examples.append(candidate)
        if len(examples) == 3:
            break
    return examples
