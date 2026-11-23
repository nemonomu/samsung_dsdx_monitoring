# SIEL Jiomart Layer 1

TV, REF, and LDY use the existing SIEL source tables with a Jiomart-only Layer 1 scope. The same latest batch drives receipt counts, daily and weekly statistics, column checks, and MAIN/BSR ranks. Latest means `crawl_datetime DESC NULLS LAST, id DESC` within the recorded collection day. Jiomart rows have no required `page_type` value.

- The 2026-11-20 test date is tied to the verified test batch and exact stored instant. It is viewable and excluded from operating totals, incidents, and observation days. Deleting the test rows requires no monitoring cleanup.
- The operating policy starts on 2026-11-22. The receipt window is 09:00–11:00 KST. Actual, completed source days with rows contribute to each product's five-day observation period.
- Jiomart, Amazon, and Flipkart use the SIEL business day (`Asia/Seoul`). The native `crawl_datetime` must fall at or after the selected day's KST midnight and before the following day's KST midnight. Jiomart's 09:00–11:00 KST window controls receipt status.

Layer 1 reads the SIEL retail tables directly for Jiomart. The previous collection-date registry is retained for historical reference. The normal refresh rebuilds saved statistics using the business-day rule.
