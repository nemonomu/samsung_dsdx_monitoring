# Retail collection dates

- For new countries and retailers, the collection date is the date recorded in
  the original DB collection timestamp (`crawl_datetime`, `crawl_strdatetime`,
  or the source registry's equivalent). Do not derive it from the current server
  date, a batch ID, or a conversion to KST/UTC/local time.
- Use `apps.common.source_dates.source_date_sql` and `source_date_value` for
  raw timestamp text. An offset-bearing value such as
  `2026-10-14T21:37:34-04:00` belongs to **2026-10-14**.
- Preserve the explicit SIEL business-timezone exception and existing lookup
  date conversions / display-time conversions. Lookup helpers are not defaults
  for monitoring. Do not copy their timezone rules into new source definitions.
- Keep inspection-day offsets (D-1 etc.), schedule/deadline timezones, and
  displayed timestamps separate from the collection-date key.
- PostgreSQL `timestamptz` does not preserve the originally supplied offset.
  For a new native `timestamptz` source, inspect the schema and retain/use an
  authoritative original collection date; do not let the DB session timezone
  silently determine that date.
- Verify date-boundary cases and unchanged SIEL / lookup behavior when changing
  date policy. Do not rewrite raw DB collection timestamps to fix classification.
