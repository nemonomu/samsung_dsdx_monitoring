-- SEIB MediaMarkt retail backup tables for Layer 1 integrated backup.
-- Run once in the DX PostgreSQL database before deploying the backup code.
-- No source rows are changed, and no backup is executed by this script.
-- Column order must match each source because backup.py uses INSERT ... SELECT a.*.
BEGIN;

CREATE TABLE IF NOT EXISTS dx_seib.dx_seib_tv_retail_com_backup
    (LIKE dx_seib.dx_seib_tv_retail_com INCLUDING DEFAULTS INCLUDING STORAGE INCLUDING COMMENTS);
CREATE TABLE IF NOT EXISTS dx_seib.dx_seib_ref_retail_com_backup
    (LIKE dx_seib.dx_seib_ref_retail_com INCLUDING DEFAULTS INCLUDING STORAGE INCLUDING COMMENTS);
CREATE TABLE IF NOT EXISTS dx_seib.dx_seib_ldy_retail_com_backup
    (LIKE dx_seib.dx_seib_ldy_retail_com INCLUDING DEFAULTS INCLUDING STORAGE INCLUDING COMMENTS);
CREATE TABLE IF NOT EXISTS dx_seib.dx_seib_ldy_dryer_retail_com_backup
    (LIKE dx_seib.dx_seib_ldy_dryer_retail_com INCLUDING DEFAULTS INCLUDING STORAGE INCLUDING COMMENTS);

-- Fail before any backup if an existing table has a different column order/type.
DO $verify$
DECLARE
    product text;
    source_columns text[];
    backup_columns text[];
BEGIN
    FOREACH product IN ARRAY ARRAY['tv', 'ref', 'ldy', 'ldy_dryer'] LOOP
        SELECT array_agg(attname || ':' || format_type(atttypid, atttypmod) ORDER BY attnum)
        INTO source_columns
        FROM pg_attribute
        WHERE attrelid = format('dx_seib.dx_seib_%s_retail_com', product)::regclass
          AND attnum > 0 AND NOT attisdropped;

        SELECT array_agg(attname || ':' || format_type(atttypid, atttypmod) ORDER BY attnum)
        INTO backup_columns
        FROM pg_attribute
        WHERE attrelid = format('dx_seib.dx_seib_%s_retail_com_backup', product)::regclass
          AND attnum > 0 AND NOT attisdropped;

        IF source_columns IS DISTINCT FROM backup_columns THEN
            RAISE EXCEPTION 'SEIB % backup columns differ from source', product;
        END IF;
    END LOOP;
END
$verify$;

CREATE UNIQUE INDEX IF NOT EXISTS dx_seib_tv_retail_com_backup_id_uq
    ON dx_seib.dx_seib_tv_retail_com_backup (id);
CREATE UNIQUE INDEX IF NOT EXISTS dx_seib_ref_retail_com_backup_id_uq
    ON dx_seib.dx_seib_ref_retail_com_backup (id);
CREATE UNIQUE INDEX IF NOT EXISTS dx_seib_ldy_retail_com_backup_id_uq
    ON dx_seib.dx_seib_ldy_retail_com_backup (id);
CREATE UNIQUE INDEX IF NOT EXISTS dx_seib_ldy_dryer_retail_com_backup_id_uq
    ON dx_seib.dx_seib_ldy_dryer_retail_com_backup (id);

COMMIT;
