-- DBeaver-only rollback preview. Default ROLLBACK makes no persistent change.
-- Removes only rows created by seed_seg_layer1_schedule, not pre-existing rows.
BEGIN;
LOCK TABLE public.monitoring_collection_schedule IN SHARE ROW EXCLUSIVE MODE;
DO $$
DECLARE owned_count integer;
BEGIN
    SELECT COUNT(*) INTO owned_count
    FROM public.monitoring_collection_schedule
    WHERE check_type = 'seg_retail' AND created_id = 'seed_seg_layer1_schedule';
    IF owned_count NOT IN (0, 8) OR EXISTS (
        SELECT 1 FROM public.monitoring_collection_schedule
        WHERE check_type = 'seg_retail' AND created_id = 'seed_seg_layer1_schedule'
          AND (updated_id IS DISTINCT FROM 'seed_seg_layer1_schedule'
               OR updated_at IS DISTINCT FROM created_at)
    ) THEN
        RAISE EXCEPTION 'SEG schedule was partially created or subsequently edited; review before rollback';
    END IF;
END $$;
DELETE FROM public.monitoring_collection_schedule
WHERE check_type = 'seg_retail' AND created_id = 'seed_seg_layer1_schedule'
RETURNING id, category, retailer;
SELECT 'SEG_LAYER1_ROLLBACK_PREVIEW' AS marker;
ROLLBACK;
