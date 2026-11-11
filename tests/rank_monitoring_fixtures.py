from datetime import date

DAY = date(2026, 11, 10)


def row(day, item, rank, *, id=None, name=None, sku=None, **extra):
    return {'date': f'2026-11-{day:02}', 'id': id if id is not None else day * 1000 + int(item),
            'item': str(item), 'sku': sku or f'SKU-{item}', 'name': name or f'Samsung product {item}',
            'url': 'https://example.com/product/' + str(item), 'rank': rank,
            'batch_id': f'b{day}', 'collected_at': f'2026-11-{day:02}T23:10:00-04:00', **extra}


def samples():
    values = {1: (1, 2, 1), 30: (30, None, 32), 80: (80, 150, 95),
              95: (95, None, None), 150: (150, 80, 150), 240: (240, 245, None),
              280: (280, 270, 280)}
    return [row(day, item, rank, name=('LG product' if item == 280 else f'Samsung product {item}'))
            for item, ranks in values.items() for day, rank in zip((9, 10, 11), ranks) if rank is not None]
