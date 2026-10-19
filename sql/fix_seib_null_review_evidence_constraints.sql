-- Apply to the monitoring DB before confirming SEIB NULL findings.
-- The original evidence table allows neither SEIB nor LDY_DRYER, so the
-- correction and its evidence roll back together. No retail source is changed.
-- Safe to rerun: replace only the two single-column CHECK constraints.
BEGIN;

DO $seib_evidence$
DECLARE
    field_name text;
    check_name text;
BEGIN
    IF to_regclass('public.monitoring_null_review_evidence') IS NULL THEN
        RAISE EXCEPTION
            'public.monitoring_null_review_evidence is missing; run sql/create_null_review_evidence.sql first';
    END IF;

    FOREACH field_name IN ARRAY ARRAY['country', 'product_line'] LOOP
        FOR check_name IN
            SELECT constraint_row.conname
            FROM pg_constraint AS constraint_row
            JOIN pg_attribute AS field_column
              ON field_column.attrelid = constraint_row.conrelid
             AND field_column.attname = field_name
             AND constraint_row.conkey = ARRAY[field_column.attnum]::smallint[]
            WHERE constraint_row.conrelid =
                  'public.monitoring_null_review_evidence'::regclass
              AND constraint_row.contype = 'c'
        LOOP
            EXECUTE format(
                'ALTER TABLE public.monitoring_null_review_evidence DROP CONSTRAINT %I',
                check_name
            );
        END LOOP;
    END LOOP;

    ALTER TABLE public.monitoring_null_review_evidence
        ADD CONSTRAINT monitoring_null_review_evidence_country_check
        CHECK (country IN ('SEA', 'SEDA', 'SEM', 'SIEL', 'TSE', 'SEG', 'SEIB'));
    ALTER TABLE public.monitoring_null_review_evidence
        ADD CONSTRAINT monitoring_null_review_evidence_product_line_check
        CHECK (product_line IN ('TV', 'REF', 'LDY', 'LDY_DRYER'));
END
$seib_evidence$;

COMMIT;

-- Read-only verification after applying:
-- SELECT conname, pg_get_constraintdef(oid)
-- FROM pg_constraint
-- WHERE conrelid = 'public.monitoring_null_review_evidence'::regclass
--   AND conname IN ('monitoring_null_review_evidence_country_check',
--                   'monitoring_null_review_evidence_product_line_check');
