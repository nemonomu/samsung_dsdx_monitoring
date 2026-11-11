"""Filter/paginate a completed snapshot; never recalculate cohort metrics."""
PRIORITY = {'data': 0, 'return': 1, 'missing': 2, 'next_missing': 2, 'swing': 3,
            'unassessed': 4, 'new': 5, 'stable': 6}


def filtered(products, params):
    view, signal, tier, order = (params.get(k, default) for k, default in
        (('view', 'all'), ('signal', 'all'), ('tier', 'all'), ('sort', 'rank')))
    query = params.get('query', '').strip().casefold()
    if (view not in ('all', 'review') or signal not in ('all', 'return', 'missing', 'next_missing', 'swing', 'data')
            or tier not in ('all', '0', '1', '2') or order not in ('rank', 'priority') or len(query) > 200):
        raise ValueError('Invalid list filter')
    result = []
    for product in products:
        cell = product['cells'][0]
        if view == 'review' and not product['review_needed']:
            continue
        if signal != 'all' and not product['signals'][signal]:
            continue
        if tier != 'all' and (cell['state'] != 'ranked' or (cell['rank'] - 1) // 100 != int(tier)):
            continue
        if query and query not in f"{product['name']} {product['item']} {product['sku']}".casefold():
            continue
        result.append(product)
    return sorted(result, key=lambda p: (PRIORITY[p['status']] if order == 'priority' else 0,
                                         p['cells'][0]['rank'] or 10**9, p['item']))


def lightweight(product, review_index):
    return {**{key: product[key] for key in ('key', 'item', 'sku', 'name', 'samsung', 'status', 'label', 'review_needed', 'signals')},
            'cells': [{'rank': cell['rank'], 'state': cell['state']} for cell in product['cells']],
            'review': {'result': review_index.get(product['fingerprint'], '미확인')}}
