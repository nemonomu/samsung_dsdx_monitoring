-- Backup tables for SEA and SEM LDY_DRYER. No source rows or source schema change.
-- Run before enabling integrated backup. INSERT ... SELECT a.* needs matching order.
BEGIN;

CREATE TABLE IF NOT EXISTS public.ldy_dryer_retail_backup
    (LIKE public.ldy_dryer_retail INCLUDING DEFAULTS INCLUDING STORAGE INCLUDING COMMENTS);
CREATE TABLE IF NOT EXISTS dx_sem.dx_sem_ldy_dryer_retail_com_backup
    (LIKE dx_sem.dx_sem_ldy_dryer_retail_com INCLUDING DEFAULTS INCLUDING STORAGE INCLUDING COMMENTS);

DO $verify$
DECLARE
    source_name text;
    backup_name text;
    source_columns text[];
    backup_columns text[];
BEGIN
    FOR source_name, backup_name IN
        SELECT * FROM (VALUES
            ('public.ldy_dryer_retail', 'public.ldy_dryer_retail_backup'),
            ('dx_sem.dx_sem_ldy_dryer_retail_com',
             'dx_sem.dx_sem_ldy_dryer_retail_com_backup')
        ) AS pairs(source_name, backup_name)
    LOOP
        SELECT array_agg(attname || ':' || format_type(atttypid, atttypmod)
                         ORDER BY attnum)
        INTO source_columns FROM pg_attribute
        WHERE attrelid = source_name::regclass
          AND attnum > 0 AND NOT attisdropped;
        SELECT array_agg(attname || ':' || format_type(atttypid, atttypmod)
                         ORDER BY attnum)
        INTO backup_columns FROM pg_attribute
        WHERE attrelid = backup_name::regclass
          AND attnum > 0 AND NOT attisdropped;
        IF source_columns IS DISTINCT FROM backup_columns THEN
            RAISE EXCEPTION 'Backup columns differ: %', backup_name;
        END IF;
    END LOOP;
END
$verify$;

CREATE UNIQUE INDEX IF NOT EXISTS ldy_dryer_retail_backup_id_uq
    ON public.ldy_dryer_retail_backup (id);
CREATE UNIQUE INDEX IF NOT EXISTS dx_sem_ldy_dryer_retail_com_backup_id_uq
    ON dx_sem.dx_sem_ldy_dryer_retail_com_backup (id);

COMMIT;
