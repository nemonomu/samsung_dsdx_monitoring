-- Retail NULL review evidence, policy effective from 2026-09-12 (Asia/Seoul).
-- Apply in PostgreSQL BEFORE deploying the matching application change.
-- This creates an empty evidence store. Do NOT backfill legacy confirmations.
-- Cross-field, format, duplicate and collected product data are unchanged.

BEGIN;

CREATE TABLE IF NOT EXISTS public.monitoring_null_review_evidence (
    id bigserial PRIMARY KEY,
    correction_id bigint NOT NULL UNIQUE,
    policy_version smallint NOT NULL DEFAULT 1 CHECK (policy_version = 1),
    table_name text NOT NULL,
    country text NOT NULL CHECK (country IN ('SEA', 'SEM', 'SIEL', 'TSE', 'SEG')),
    product_line text NOT NULL CHECK (product_line IN ('TV', 'REF', 'LDY')),
    retailer text NOT NULL,
    record_id bigint NOT NULL,
    item text NOT NULL,
    product_name text NOT NULL,
    column_name text NOT NULL,
    subject_key text CHECK (subject_key IS NULL OR length(subject_key) = 64),
    value_snapshot jsonb NOT NULL,
    inspection_date date NOT NULL CHECK (inspection_date >= DATE '2026-09-12'),
    reviewed_at timestamptz NOT NULL,
    auto_apply_from date NOT NULL,
    reason text NOT NULL,
    reviewer text NOT NULL,
    memo text NOT NULL DEFAULT '',
    revoked_at timestamptz,
    revoked_by text,
    revoke_memo text,
    CHECK (auto_apply_from > inspection_date),
    CHECK (inspection_date <= (reviewed_at AT TIME ZONE 'Asia/Seoul')::date),
    CHECK (auto_apply_from > (reviewed_at AT TIME ZONE 'Asia/Seoul')::date),
    CHECK (reviewed_at >= TIMESTAMPTZ '2026-09-12 00:00:00+09'),
    FOREIGN KEY (correction_id) REFERENCES public.monitoring_corrections (id)
);

CREATE INDEX IF NOT EXISTS monitoring_null_review_evidence_subject_idx
    ON public.monitoring_null_review_evidence (subject_key, reviewed_at DESC, id DESC)
    WHERE subject_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS monitoring_null_review_evidence_record_idx
    ON public.monitoring_null_review_evidence (table_name, record_id, inspection_date);

COMMENT ON TABLE public.monitoring_null_review_evidence IS
    'NULL-only manual review snapshots; no legacy backfill; revoke preserves historical evidence';

COMMIT;

-- Read-only post-application checks:
-- SELECT to_regclass('public.monitoring_null_review_evidence');
-- SELECT COUNT(*) FROM public.monitoring_null_review_evidence;
