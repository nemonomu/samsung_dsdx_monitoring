"""Helpers for carrying DS anomaly causes forward from the previous day."""


def _is_blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def anomaly_signature(anomaly):
    """Return the anomaly types/NULL layout without comparing actual values."""
    signature = []

    if _is_blank(anomaly.get('title')):
        signature.append('title_null')

    imageurl = anomaly.get('imageurl')
    if _is_blank(imageurl):
        signature.append('imageurl_null')
    elif not str(imageurl).strip().lower().startswith('https://'):
        signature.append('imageurl_invalid')

    for field in ('retailprice', 'ships_from', 'sold_by'):
        if _is_blank(anomaly.get(field)):
            signature.append(f'{field}_null')

    return tuple(signature)


def _normalized_sku(value):
    if _is_blank(value):
        return ''
    return str(value).strip().casefold()


def carry_forward_causes(anomalies, previous_anomalies):
    """Fill blank causes when the previous day has one unambiguous match."""
    candidates = {}

    for previous in previous_anomalies:
        sku = _normalized_sku(previous.get('retailersku'))
        signature = anomaly_signature(previous)
        cause = previous.get('cause')
        if not sku or not signature or _is_blank(cause):
            continue

        key = (sku, signature)
        candidates.setdefault(key, set()).add(str(cause).strip())

    carried = []
    for anomaly in anomalies:
        current = dict(anomaly)
        sku = _normalized_sku(current.get('retailersku'))
        signature = anomaly_signature(current)
        causes = candidates.get((sku, signature), set())

        if _is_blank(current.get('cause')) and len(causes) == 1:
            current['cause'] = next(iter(causes))

        carried.append(current)

    return carried
