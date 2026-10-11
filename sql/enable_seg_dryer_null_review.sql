-- Apply manually BEFORE enabling dryer NULL normal-review saves.
-- Extends only the evidence product-line constraint; no collected data changes.
BEGIN;
DO $$
DECLARE
    product_att smallint;
    constraint_name text;
    constraint_count integer;
BEGIN
    SELECT attnum INTO STRICT product_att
    FROM pg_attribute
    WHERE attrelid = 'public.monitoring_null_review_evidence'::regclass
      AND attname = 'product_line' AND NOT attisdropped;

    SELECT count(*), min(conname::text)
    INTO constraint_count, constraint_name
    FROM pg_constraint
    WHERE conrelid = 'public.monitoring_null_review_evidence'::regclass
      AND contype = 'c' AND conkey = ARRAY[product_att]::smallint[];
    IF constraint_count <> 1 THEN
        RAISE EXCEPTION 'Expected exactly one product_line check; inspect schema before proceeding';
    END IF;

    EXECUTE format('ALTER TABLE public.monitoring_null_review_evidence DROP CONSTRAINT %I', constraint_name);
    ALTER TABLE public.monitoring_null_review_evidence
        ADD CONSTRAINT monitoring_null_review_evidence_product_line_check
        CHECK (product_line IN ('TV', 'REF', 'LDY', 'LDY_DRYER'));
END $$;
COMMIT;

SELECT conname, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conrelid = 'public.monitoring_null_review_evidence'::regclass
  AND conname = 'monitoring_null_review_evidence_product_line_check';
