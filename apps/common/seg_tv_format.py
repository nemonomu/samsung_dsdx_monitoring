"""SEG TV text formats from the September 23 exports; populated fields only."""
import re
from datetime import date


_MONTHS = 'January February March April May June July August September October November December'.split()
_MONTH = '(?:' + '|'.join(_MONTHS) + ')'
_WEEKDAY = r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)'
_DAY = r'[0-9]{1,2}(?:st|nd|rd|th)'
_DATE = rf'{_MONTH} {_DAY}'
_DATES = rf'(?:{_WEEKDAY}, {_DATE}|tomorrow, {_DATE}|{_DATE}(?: - {_DATE})?)(?:, [0-9]{{4}})?'
_TIME = r'(?:[01][0-9]|2[0-3]):[0-5][0-9]'
_TIMES = rf'{_TIME} - {_TIME}'
_MONEY = r'(?:0|[1-9][0-9]*)(?:,[0-9]{2})? ?€'
_ORDER = r'(?:\. Order within (?:[0-9]+ hrs\.(?: [0-5]?[0-9] mins\.)?|[0-5]?[0-9] mins\.))?'
_DELIVERY_PREFIX = rf'(?:FREE delivery(?: by appointment to a location of your choice)?|delivery(?: by appointment to a location of your choice)? for {_MONEY}|delivery)'
_DELIVERY = re.compile(rf'{_DELIVERY_PREFIX} {_DATES}(?: for qualifying first order)?{_ORDER}\.?')
_FASTEST = re.compile(rf'Or (?:fastest|earliest) delivery (?:{_DATES}(?:, {_TIMES})?|tomorrow {_TIMES}){_ORDER}\.?')
_EN_DATE = re.compile(rf'({_MONTH}) ([0-9]{{1,2}})(st|nd|rd|th)')
_PERIOD = re.compile(r'(?:Usually ready to ship in ([1-9][0-9]*) to ([1-9][0-9]*) (?:days|weeks|months)|Gewoehnlich versandfertig in ([1-9][0-9]*) bis ([1-9][0-9]*) (?:Tagen|Wochen|Monaten))')


def _match(pattern):
    compiled = re.compile(pattern)
    return lambda value: compiled.fullmatch(value) is not None


def _delivery_dates_valid(value):
    # Yearless February 29 is valid; do not infer a year from today's date.
    year_match = re.search(r', ([0-9]{4})(?=\.| for |$)', value)
    year = int(year_match[1]) if year_match else 2000
    for match in _EN_DATE.finditer(value):
        day = int(match[2])
        suffix = 'th' if 10 <= day % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
        if match[3] != suffix:
            return False
        try:
            date(year, _MONTHS.index(match[1]) + 1, day)
        except ValueError:
            return False
    for start, end in re.findall(rf'({_TIME}) - ({_TIME})', value):
        if start >= end:
            return False
    return True


def _amazon_delivery(value, fastest=False):
    return bool((_FASTEST if fastest else _DELIVERY).fullmatch(value)) and _delivery_dates_valid(value)


def _mediamarkt_delivery(value):
    if value == 'Not available for delivery':
        return True
    match = re.fullmatch(r'Home delivery from ([0-9]{2})\.([0-9]{2})\.([0-9]{4})', value)
    if not match:
        return False
    try:
        date(int(match[3]), int(match[2]), int(match[1]))
    except ValueError:
        return False
    return True


def _otto_delivery(value):
    if value == 'Available - at your door the next working day':
        return True
    match = re.fullmatch(r'Available - at your door in ([1-9][0-9]*)-([1-9][0-9]*) working days', value)
    if match:
        return int(match[1]) <= int(match[2])
    return re.fullmatch(r'Available in [1-9][0-9]* weeks', value) is not None


def _inventory(value):
    if value in ('In Stock', 'Currently unavailable.'):
        return True
    if re.fullmatch(r'Only [1-9][0-9]* left in stock(?: \(more on the way\)\.)?', value):
        return True
    match = _PERIOD.fullmatch(value)
    if match:
        start, end = [int(part) for part in match.groups() if part is not None]
        return start <= end
    return False


_MM_DISCOUNTS = frozenset({'Incl. streaming content', 'Our own brand', 'Price champion', 'Also for business customers'})


def _mediamarkt_discount(value):
    # Every component must be recognized, including those after the separator.
    return all(part in _MM_DISCOUNTS for part in value.split(' ||| '))


# Each entry is (predicate, accepted forms displayed in the detail view).
RULES = {
    'mediamarkt': {
        'sku_status': (lambda v: v == 'Sponsored', 'Sponsored'),
        'discount_type': (_mediamarkt_discount, 'Incl. streaming content / Our own brand / Price champion / Also for business customers (복수 문구는 " ||| "로 연결)'),
        'delivery_availability': (_mediamarkt_delivery, 'Home delivery from DD.MM.YYYY / Not available for delivery'),
        'pick_up_availability': (lambda v: v in ('Available for store pickup', 'Not available for store pickup'), 'Available for store pickup / Not available for store pickup'),
    },
    'otto': {
        'sku_popularity': (lambda v: v == 'Very popular', 'Very popular'),
        'sku_status': (lambda v: v == 'Sponsored', 'Sponsored'),
        'discount_type': (lambda v: v in ('Deal & Win', 'Deal of the week', 'Deal of the month'), 'Deal & Win / Deal of the week / Deal of the month'),
        'delivery_availability': (_otto_delivery, 'Available - at your door the next working day / Available - at your door in N-M working days / Available in N weeks (양의 정수, N ≤ M)'),
    },
    'amazon': {
        'sku_popularity': (lambda v: v in ('Bestseller', 'Amazons Tipp'), 'Bestseller / Amazons Tipp'),
        'number_of_units_purchased_past_month': (_match(r'[1-9][0-9]*\+ gekauft Mal im letzten Monat'), 'N+ gekauft Mal im letzten Monat (N은 양의 정수)'),
        # sku_status is pending: the export has no populated examples.
        'available_quantity_for_purchase': (_match(r'Nur noch [1-9][0-9]* auf Lager(?: \(mehr ist unterwegs\)\.)?'), 'Nur noch N auf Lager / Nur noch N auf Lager (mehr ist unterwegs). (N은 양의 정수)'),
        'delivery_availability': (_amazon_delivery, '무료·유료·예약 배송 + 영문 날짜/날짜 범위, 선택 연도·첫 주문 조건·Order within 시간'),
        'fastest_delivery': (lambda v: _amazon_delivery(v, fastest=True), 'Or fastest delivery / Or earliest delivery + 날짜 또는 tomorrow, 선택 시간대·Order within 시간'),
        'inventory_status': (_inventory, 'In Stock / Currently unavailable. / Only N left in stock (선택 추가 입고 문구) / Usually ready to ship in N to M days·weeks·months / Gewoehnlich versandfertig in N bis M Tagen·Wochen·Monaten'),
    },
}


def get_rules(product_line, retailer=None):
    if product_line != 'seg_tv':
        return {}
    if retailer is None:
        return {field: rule for rules in RULES.values() for field, rule in rules.items()}
    return RULES.get(str(retailer).strip().casefold(), {})


def evaluate(row, product_line, retailer):
    errors = {}
    for field, (valid, forms) in get_rules(product_line, retailer).items():
        value = row.get(field)
        if value is not None and str(value).strip() and not valid(str(value).strip()):
            errors[field] = f'허용 형식: {forms}'
    return errors


def rule_details(product_line, retailer):
    return [{'field': field, 'description': 'SEG TV 리테일러별 문구 형식 (빈값 제외)', 'pattern': forms}
            for field, (_, forms) in get_rules(product_line, retailer).items()]
