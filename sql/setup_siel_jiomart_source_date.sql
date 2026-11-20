-- Collector onboarding for Layer 1. In the same transaction as the source
-- rows, record the producer's original date for each distinct crawl_datetime
-- in the batch. Never backfill a date from a timezone conversion or batch ID.
BEGIN;
CREATE TABLE IF NOT EXISTS dx_siel.jiomart_collection_dates (
    product text NOT NULL CHECK (product IN ('TV', 'REF', 'LDY')),
    batch_id text NOT NULL CHECK (btrim(batch_id) <> ''),
    crawl_datetime timestamptz NOT NULL,
    source_collection_date date NOT NULL,
    PRIMARY KEY (product, batch_id, crawl_datetime)
);
CREATE INDEX IF NOT EXISTS jiomart_collection_dates_source_day_idx
    ON dx_siel.jiomart_collection_dates (product, source_collection_date);
COMMIT;
