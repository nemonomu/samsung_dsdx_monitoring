# SIEL Jiomart Layer 1

TV, REF, and LDY use the existing SIEL source tables with a Jiomart-only Layer 1 scope. The same latest batch drives receipt counts, daily and weekly statistics, column checks, and MAIN/BSR ranks. Latest means `crawl_datetime DESC NULLS LAST, id DESC` within the recorded collection day. Jiomart rows have no required `page_type` value.

- The 2026-11-20 test date is tied to the verified test batch and exact stored instant. It is viewable and excluded from operating totals, incidents, and observation days. Deleting the test rows requires no monitoring cleanup.
- The operating policy starts on 2026-11-22. The receipt window is 09:00–11:00 KST. Actual, completed source days with rows contribute to each product's five-day observation period.
- The native `crawl_datetime` stores an instant. It determines batch order but cannot recover the producer's original day. Amazon and Flipkart keep the existing SIEL business-day rule.

Before operational ingestion, create [the collection-date registry](../sql/setup_siel_jiomart_source_date.sql). The Jiomart collector must store `(product, batch_id, crawl_datetime, source_collection_date)` from its original collection metadata in the **same transaction** as each batch. If rows within a batch have different stored timestamps, register each distinct timestamp. Register the producer's original date, not a date inferred from the batch name, server clock, or a converted timestamp. The setup leaves all retail and backup tables unchanged.

On operating dates without a verified date source, Layer 1 shows date confirmation pending and withholds missing-collection verdicts. For any dates populated after the automatic recent refresh window, use `python manage.py refresh_collection_statistics --country SIEL --start YYYY-MM-DD --end YYYY-MM-DD` to rebuild the saved statistics.
