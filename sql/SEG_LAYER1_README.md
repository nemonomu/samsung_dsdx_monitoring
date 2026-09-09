# SEG Layer1

Branch: `fix/sem-crossfield-history-3days`. Merge only on user request.

## Implemented

- Inspection date D maps to source date D, using the date recorded in text `crawl_strdatetime` without timezone conversion.
- Latest MAIN batch is selected per product/retailer/date by greatest MAIN row ID. MAIN and BSR rows of that batch are counted together once for physical row totals.
- MAIN and BSR rank counts can overlap; they are not added to obtain physical totals.
- TV/REF: Mediamarkt, OTTO, Amazon. LDY: Mediamarkt, OTTO, no redirect column.
- Collection window: KST 07:00 inclusive to 12:00 exclusive; at 12:00 collection is complete.
- MAIN average: previous dates strictly before the selected date, latest MAIN batch for each date, zero MAIN days excluded, latest seven positive days per retailer. Integer division discards fractional counts. Partial history uses available days; absent history is displayed as `-`.
- Average difference is informational pending a user-defined deviation threshold. Only zero MAIN collection after completion is currently critical. Before completion the status is pending/collecting.
- Existing backup tables are reused with ID-based insert-if-absent semantics. Backups cover the whole selected source date, including other batches and redirect rows, to preserve original data before later validation/editing.
- Layer2, Layer3, email rules and other countries' data rules are unchanged.

## Operational verification still required

Codex has not executed operational SQL or deployed this change.

1. Run `seg_layer1_preflight.sql` in DBeaver after selecting the comparison date. Return all result sets to verify real columns/types, indexes, schedule inventory, batch/rank counts and backup gaps.
2. Review `seed_seg_layer1_schedule.sql` against that inventory. It activates only the SEG Layer1 schedule with eight rows, and aborts on unexpected existing state. `expected_count=0` in these activation rows is not the runtime average; the SEG service computes the average from source data.
3. Run the activation script manually only after review. Check the post-COMMIT result rather than the PRECOMMIT marker alone. `rollback_seg_layer1_schedule.sql` is a rollback preview ending in ROLLBACK.
4. Apply the feature branch to the server only when deployment is requested. Check Django, collect static assets and refresh the schedule cache through the existing deployment procedure.
5. Compare the displayed selected batch, physical counts, rank counts, integer average dates/counts and backup gaps with read-only SQL results. Check a missing day, first collection day and KST 07:00/12:00 boundaries.

The date text's originating RDP timezone has not been independently verified; no KST/UTC conversion has been inferred for those stored strings.
