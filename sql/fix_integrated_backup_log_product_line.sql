-- Apply in the monitoring DB before retrying integrated backup.
-- The new SEA/SEM/SEIB LDY_DRYER keys are 13-14 characters, but the existing
-- backup log permits only 10. Only monitoring_backup_log is changed.
BEGIN;

ALTER TABLE public.monitoring_backup_log
    ALTER COLUMN product_line TYPE text;

COMMIT;

-- Read-only verification:
-- SELECT data_type, character_maximum_length
-- FROM information_schema.columns
-- WHERE table_schema = 'public'
--   AND table_name = 'monitoring_backup_log'
--   AND column_name = 'product_line';
