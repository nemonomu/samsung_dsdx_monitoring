"""Retry a rolled-back SQLite write, never a partial transaction or schema error."""
from time import sleep

from django.db import connection, OperationalError


def retry_locked_write(operation):
    # Retrying a savepoint cannot release an enclosing transaction's read lock.
    retryable = connection.vendor == 'sqlite' and not connection.in_atomic_block
    delays = (0.05, 0.15, 0.3)
    for attempt in range(len(delays) + 1):
        try:
            return operation()
        except OperationalError as exc:
            locked = any(value in str(exc).lower() for value in
                         ('database is locked', 'database table is locked'))
            if not retryable or not locked or attempt == len(delays):
                raise
            sleep(delays[attempt])
