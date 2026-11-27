"""Read final, producer-published D-DAY receipts from a private directory."""
import json
from datetime import datetime
from pathlib import Path

from django.conf import settings


def receipt_state(country, product, retailer, day, now, counts):
    directory = getattr(settings, 'DX_DDAY_RECEIPTS_DIR', None)
    if not directory:
        return None
    name = f'{country}-{product}-{retailer.casefold().replace(" ", "")}.json'
    try:
        receipt = json.loads((Path(directory) / str(day) / name).read_text(encoding='utf-8'))
        if not isinstance(receipt, dict):
            return None
        if [receipt.get(key) for key in ('country', 'product', 'retailer', 'source_date')] != [
                country, product, retailer, str(day)]:
            return None
        batch = receipt['batch_id']
        if not isinstance(batch, str) or not batch.strip():
            return None
        if receipt.get('state') == 'running':
            started_at = datetime.fromisoformat(receipt['started_at'])
            expires_at = datetime.fromisoformat(receipt['expires_at'])
            if started_at.tzinfo is not None and expires_at.tzinfo is not None and started_at <= now < expires_at:
                return 'running'
            return None
        if receipt.get('state') != 'committed':
            return None
        completed_at = datetime.fromisoformat(receipt['completed_at'])
        count, _, active_batch, main, bsr = counts
        reported = [receipt.get(field) for field in ('count', 'main_count', 'bsr_count')]
        outcome = receipt.get('outcome')
        if (completed_at.tzinfo is not None and completed_at <= now
                and all(type(value) is int and value >= 0 for value in reported)
                and reported == [count, main, bsr]
                and ((outcome == 'loaded' and batch == active_batch) if count
                     else (outcome == 'empty' and not active_batch))):
            return 'committed'
    except (OSError, KeyError, TypeError, ValueError):
        return None
