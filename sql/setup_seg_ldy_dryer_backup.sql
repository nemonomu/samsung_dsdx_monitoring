-- SEG Expert LDY_DRYER integrated-backup target. No source rows are changed.
-- Run in the monitoring PostgreSQL database before enabling this backup source.
BEGIN;

CREATE TABLE IF NOT EXISTS dx_seg.dx_seg_ldy_dryer_retail_backup
    (LIKE dx_seg.dx_seg_ldy_dryer_retail INCLUDING DEFAULTS INCLUDING STORAGE INCLUDING COMMENTS);

DO $verify$
DECLARE
    source_columns text[];
    backup_columns text[];
BEGIN
    SELECT array_agg(attname || ':' || format_type(atttypid, atttypmod) ORDER BY attnum)
    INTO source_columns
    FROM pg_attribute
    WHERE attrelid = 'dx_seg.dx_seg_ldy_dryer_retail'::regclass
      AND attnum > 0 AND NOT attisdropped;

    SELECT array_agg(attname || ':' || format_type(atttypid, atttypmod) ORDER BY attnum)
    INTO backup_columns
    FROM pg_attribute
    WHERE attrelid = 'dx_seg.dx_seg_ldy_dryer_retail_backup'::regclass
      AND attnum > 0 AND NOT attisdropped;

    IF source_columns IS DISTINCT FROM backup_columns THEN
        RAISE EXCEPTION 'SEG LDY_DRYER backup columns differ from source';
    END IF;
END
$verify$;

CREATE UNIQUE INDEX IF NOT EXISTS dx_seg_ldy_dryer_retail_backup_id_uq
    ON dx_seg.dx_seg_ldy_dryer_retail_backup (id);

-- The source key seg_ldy_dryer is longer than the original varchar(10) log field.
ALTER TABLE public.monitoring_backup_log
    ALTER COLUMN product_line TYPE text;

COMMIT;
