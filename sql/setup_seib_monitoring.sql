-- PRODUCTION configuration: public.monitoring_* (not test_monitoring_*).
-- Deploy matching SEIB application code first. Run this whole file in one session.
-- Registers Layer1 schedules, collection columns and NULL checks only.
-- Original source date: crawl_datetime text; D-day; first date 2026-10-18.
-- KST 01:00-04:00 deadline and historical comparisons live in application code.
-- No collected source rows are modified. Re-running updates existing settings.
BEGIN;

DO $setup$
DECLARE
    product record;
    source_key text;
    section_key text;
    source_table text;
    source_name text;
    group_key text;
    category_id_value bigint;
    group_id_value bigint;
    column_value text;
    required_columns text[];
    source_columns text[];
    is_required boolean;
    is_editable_value boolean;
    display_value text;
    common_required constant text[] := ARRAY[
        'country','account_name','item','sku','retailer_sku_name','product_url',
        'final_sku_price','count_of_reviews','star_rating','count_of_star_ratings'];
BEGIN
    FOR product IN SELECT * FROM (VALUES
        ('tv', 'screen_size', ARRAY['screen_size'], 30),
        ('ref', 'ref_capacity', ARRAY['ref_capacity','ref_refrigerator_type'], 31),
        ('ldy', 'capacity', ARRAY['capacity','loading_type'], 32),
        ('ldy_dryer', 'capacity', ARRAY['capacity','loading_type'], 33)
    ) AS p(code, required_extra, extras, sort_order)
    LOOP
        source_key := 'seib_' || product.code;
        section_key := source_key || '_retail';
        source_table := 'dx_seib.dx_seib_' || product.code || '_retail_com';
        source_name := 'SEIB ' || UPPER(product.code);
        group_key := 'mediamarkt_' || source_key;
        required_columns := array_append(common_required, product.required_extra);
        source_columns := ARRAY['id','batch_id'] || common_required || ARRAY[
            'original_sku_price','savings','main_rank','bsr_rank','crawl_datetime','calendar_week'
        ] || product.extras;

        UPDATE public.monitoring_collection_schedule
        SET check_name=source_name, check_group='Retail', schedule_type='daily', schedule_value=NULL,
            us_start_hour=NULL, expected_count=0, country='SEIB', collection_duration_min=180,
            view_table_name=source_table, sort_order=6,
            description='Spain MediaMarkt D-day / KST 01:00-04:00 / first 2026-10-18',
            is_active=TRUE, is_del=0, updated_at=NOW(), updated_id='setup_seib'
        WHERE check_type='seib_retail' AND category=UPPER(product.code)
          AND LOWER(BTRIM(retailer))='mediamarkt';
        IF NOT FOUND THEN
            INSERT INTO public.monitoring_collection_schedule
                (check_group,check_type,check_name,category,schedule_type,retailer,expected_count,country,
                 collection_duration_min,view_table_name,sort_order,description,is_active,is_del,
                 created_at,created_id,updated_at,updated_id)
            VALUES ('Retail','seib_retail',source_name,UPPER(product.code),'daily','MediaMarkt',0,'SEIB',
                    180,source_table,6,'Spain MediaMarkt D-day / KST 01:00-04:00 / first 2026-10-18',
                    TRUE,0,NOW(),'setup_seib',NOW(),'setup_seib');
        END IF;

        FOREACH column_value IN ARRAY source_columns LOOP
            is_required := column_value = ANY(required_columns);
            is_editable_value := is_required OR column_value IN ('original_sku_price','savings');
            UPDATE public.monitoring_retail_columns
            SET skip_missing_check=NOT is_required, is_editable=is_editable_value,
                is_active=TRUE, is_del=FALSE, updated_at=NOW(), updated_id='setup_seib'
            WHERE product_line=source_key AND LOWER(BTRIM(retailer))='mediamarkt' AND column_name=column_value;
            IF NOT FOUND THEN
                INSERT INTO public.monitoring_retail_columns
                    (product_line,column_name,retailer,duplicate_key,skip_missing_check,is_editable,
                     is_active,is_del,created_at,created_id,updated_at,updated_id)
                VALUES (source_key,column_value,'MediaMarkt',FALSE,NOT is_required,is_editable_value,
                        TRUE,FALSE,NOW(),'setup_seib',NOW(),'setup_seib');
            END IF;
        END LOOP;

        UPDATE public.monitoring_null_category
        SET display_name=source_name, display_order=product.sort_order,
            has_retailer=TRUE, is_active=TRUE, is_del=FALSE
        WHERE category_name=section_key RETURNING id INTO category_id_value;
        IF NOT FOUND THEN
            INSERT INTO public.monitoring_null_category
                (category_name,display_name,display_order,has_retailer,is_active,is_del,created_at,created_id)
            VALUES (section_key,source_name,product.sort_order,TRUE,TRUE,FALSE,NOW(),'setup_seib')
            RETURNING id INTO category_id_value;
        END IF;

        UPDATE public.monitoring_null_group
        SET display_name='MediaMarkt', table_name=source_table, date_column='crawl_datetime',
            display_order=1, is_active=TRUE, is_del=FALSE, updated_at=NOW(), updated_id='setup_seib'
        WHERE category_id=category_id_value AND check_name=group_key RETURNING id INTO group_id_value;
        IF NOT FOUND THEN
            INSERT INTO public.monitoring_null_group
                (category_id,check_name,display_name,table_name,date_column,display_order,
                 is_active,is_del,created_at,created_id)
            VALUES (category_id_value,group_key,'MediaMarkt',source_table,'crawl_datetime',1,
                    TRUE,FALSE,NOW(),'setup_seib') RETURNING id INTO group_id_value;
        END IF;

        UPDATE public.monitoring_null_column
        SET is_active=FALSE, updated_at=NOW(), updated_id='setup_seib'
        WHERE group_id=group_id_value AND NOT (check_column = ANY(required_columns));
        FOREACH column_value IN ARRAY required_columns LOOP
            SELECT string_agg(field, '|' ORDER BY first_position) INTO display_value
            FROM (SELECT field, MIN(position) AS first_position
                  FROM unnest(ARRAY['id','crawl_datetime','item','sku','retailer_sku_name',column_value,
                       'star_rating','count_of_star_ratings','count_of_reviews','final_sku_price',
                       'original_sku_price','savings','product_url']) WITH ORDINALITY AS f(field, position)
                  GROUP BY field) fields;
            UPDATE public.monitoring_null_column
            SET check_type='both', display_columns=display_value, query_columns=display_value,
                query_days=0, is_active=TRUE, is_del=FALSE, updated_at=NOW(), updated_id='setup_seib'
            WHERE group_id=group_id_value AND check_column=column_value;
            IF NOT FOUND THEN
                INSERT INTO public.monitoring_null_column
                    (group_id,check_column,check_type,display_columns,query_columns,query_days,
                     is_active,is_del,created_at,created_id)
                VALUES (group_id_value,column_value,'both',display_value,display_value,0,
                        TRUE,FALSE,NOW(),'setup_seib');
            END IF;
        END LOOP;
        IF (SELECT COUNT(*) FROM public.monitoring_null_column
            WHERE group_id=group_id_value AND is_active AND NOT is_del) <> 11 THEN
            RAISE EXCEPTION '%: expected exactly 11 active NULL columns', source_key;
        END IF;
    END LOOP;
END
$setup$;

-- Expected: 4 rows (TV, REF, LDY, LDY_DRYER), each with 11 active NULL columns.
SELECT c.category_name, g.display_name, COUNT(*) AS null_columns
FROM public.monitoring_null_category c
JOIN public.monitoring_null_group g ON g.category_id=c.id
JOIN public.monitoring_null_column n ON n.group_id=g.id
WHERE c.category_name IN ('seib_tv_retail','seib_ref_retail','seib_ldy_retail','seib_ldy_dryer_retail')
  AND g.check_name='mediamarkt_' || replace(c.category_name, '_retail', '')
  AND c.is_active AND NOT c.is_del AND g.is_active AND NOT g.is_del AND n.is_active AND NOT n.is_del
GROUP BY c.category_name,g.display_name ORDER BY c.category_name;
SELECT category, retailer, is_active FROM public.monitoring_collection_schedule
WHERE check_type='seib_retail' AND LOWER(BTRIM(retailer))='mediamarkt' AND is_del=0
ORDER BY category;
COMMIT;
