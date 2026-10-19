-- Read-only checks for the newly added integrated-backup targets.
-- Run both SELECT statements in the monitoring database and share the results.
WITH pairs(source_table, backup_table) AS (
    VALUES
        ('public.ldy_dryer_retail', 'public.ldy_dryer_retail_backup'),
        ('dx_sem.dx_sem_ldy_dryer_retail_com', 'dx_sem.dx_sem_ldy_dryer_retail_com_backup'),
        ('dx_seg.dx_seg_ldy_dryer_retail', 'dx_seg.dx_seg_ldy_dryer_retail_backup'),
        ('dx_seib.dx_seib_tv_retail_com', 'dx_seib.dx_seib_tv_retail_com_backup'),
        ('dx_seib.dx_seib_ref_retail_com', 'dx_seib.dx_seib_ref_retail_com_backup'),
        ('dx_seib.dx_seib_ldy_retail_com', 'dx_seib.dx_seib_ldy_retail_com_backup'),
        ('dx_seib.dx_seib_ldy_dryer_retail_com', 'dx_seib.dx_seib_ldy_dryer_retail_com_backup')
), layouts AS (
    SELECT p.*,
           to_regclass(p.source_table) AS source_object,
           to_regclass(p.backup_table) AS backup_object,
           (SELECT array_agg(a.attname || ':' || format_type(a.atttypid, a.atttypmod)
                             ORDER BY a.attnum)
            FROM pg_attribute a
            WHERE a.attrelid = to_regclass(p.source_table)
              AND a.attnum > 0 AND NOT a.attisdropped) AS source_columns,
           (SELECT array_agg(a.attname || ':' || format_type(a.atttypid, a.atttypmod)
                             ORDER BY a.attnum)
            FROM pg_attribute a
            WHERE a.attrelid = to_regclass(p.backup_table)
              AND a.attnum > 0 AND NOT a.attisdropped) AS backup_columns
    FROM pairs p
)
SELECT source_table, backup_table,
       source_object IS NOT NULL AS source_exists,
       backup_object IS NOT NULL AS backup_exists,
       CASE WHEN source_object IS NULL OR backup_object IS NULL THEN NULL
            ELSE source_columns = backup_columns END AS columns_match,
       CASE WHEN backup_object IS NULL THEN NULL
            ELSE has_table_privilege(current_user, backup_object, 'INSERT')
       END AS can_insert_backup,
       source_columns, backup_columns
FROM layouts
ORDER BY source_table;

SELECT c.column_name, c.data_type, c.character_maximum_length,
       c.is_nullable,
       (SELECT string_agg(pg_get_constraintdef(k.oid), ' | ' ORDER BY k.conname)
        FROM pg_constraint k
        JOIN pg_attribute a ON a.attrelid = k.conrelid
                           AND a.attname = c.column_name
                           AND a.attnum = ANY(k.conkey)
        WHERE k.conrelid = 'public.monitoring_backup_log'::regclass
          AND k.contype = 'c') AS check_constraints
FROM information_schema.columns c
WHERE c.table_schema = 'public'
  AND c.table_name = 'monitoring_backup_log'
  AND c.column_name IN ('product_line', 'table_name', 'target_date', 'backup_count')
ORDER BY c.ordinal_position;
