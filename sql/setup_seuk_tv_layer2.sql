-- Register only SEUK TV Amazon/Argos NULL fields and the item duplicate key.
-- Apply after setup_seuk_null.sql. Set prefix to 'test_' for test settings.
BEGIN;

DO $seuk_tv_layer2$
DECLARE
    prefix text := '';
    category_table text;
    group_table text;
    column_table text;
    retail_table text;
    category_id bigint;
    target_group_id bigint;
    affected integer;
    seller text;
    field text;
    check_key text;
    required text[];
    editable text[];
    display_cols text;
    table_name CONSTANT text := 'dx_seuk.dx_seuk_tv_retail_com';
    amazon_required CONSTANT text[] := ARRAY['item','screen_size','final_sku_price','retailer_sku_name',
        'star_rating','count_of_star_ratings','country','account_name','product_url'];
BEGIN
    IF prefix NOT IN ('', 'test_') THEN RAISE EXCEPTION 'Invalid prefix'; END IF;
    category_table := prefix || 'monitoring_null_category';
    group_table := prefix || 'monitoring_null_group';
    column_table := prefix || 'monitoring_null_column';
    retail_table := prefix || 'monitoring_retail_columns';
    EXECUTE format('LOCK TABLE public.%I, public.%I, public.%I, public.%I IN SHARE ROW EXCLUSIVE MODE',
                   category_table, group_table, column_table, retail_table);

    EXECUTE format('SELECT id FROM public.%I WHERE category_name=''seuk_tv_retail''
        AND is_active AND NOT is_del', category_table) INTO STRICT category_id;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema='dx_seuk' AND c.table_name='dx_seuk_tv_retail_com'
          AND c.column_name='is_redirect' AND c.data_type='boolean') THEN
        RAISE EXCEPTION 'SEUK TV requires is_redirect boolean';
    END IF;

    FOREACH seller IN ARRAY ARRAY['Amazon','Argos'] LOOP
        required := CASE WHEN seller='Amazon' THEN amazon_required
                         ELSE amazon_required || ARRAY['sku','count_of_reviews'] END;
        editable := required || ARRAY['original_sku_price','savings'];
        IF seller='Amazon' THEN editable := editable || ARRAY['sku']; END IF;
        check_key := lower(seller) || '_seuk_tv';
        EXECUTE format('UPDATE public.%I SET display_name=$1, table_name=$2,
            date_column=''crawl_datetime'', display_order=$3, is_active=TRUE, is_del=FALSE,
            updated_at=NOW(), updated_id=''setup_seuk_tv_layer2''
            WHERE category_id=$4 AND check_name=$5 RETURNING id', group_table)
        INTO target_group_id USING seller, table_name, CASE WHEN seller='Amazon' THEN 2 ELSE 3 END,
                                   category_id, check_key;
        GET DIAGNOSTICS affected = ROW_COUNT;
        IF affected > 1 THEN RAISE EXCEPTION 'Duplicate SEUK TV NULL group: %', seller; END IF;
        IF affected = 0 THEN
            EXECUTE format('INSERT INTO public.%I (category_id, check_name, display_name, table_name,
                date_column, display_order, is_active, is_del, created_at, created_id)
                VALUES ($1,$2,$3,$4,''crawl_datetime'',$5,TRUE,FALSE,NOW(),''setup_seuk_tv_layer2'')
                RETURNING id', group_table)
            INTO target_group_id USING category_id, check_key, seller, table_name,
                                       CASE WHEN seller='Amazon' THEN 2 ELSE 3 END;
        END IF;

        FOREACH field IN ARRAY editable LOOP
            EXECUTE format('UPDATE public.%I SET duplicate_key=$3, skip_missing_check=$4,
                is_editable=TRUE, is_active=TRUE, is_del=FALSE, updated_at=NOW(),
                updated_id=''setup_seuk_tv_layer2''
                WHERE product_line=''seuk_tv'' AND LOWER(BTRIM(retailer))=$1 AND column_name=$2', retail_table)
            USING lower(seller), field, field='item', NOT (field=ANY(required));
            GET DIAGNOSTICS affected = ROW_COUNT;
            IF affected > 1 THEN RAISE EXCEPTION 'Duplicate SEUK TV column metadata: %.%', seller, field;
            ELSIF affected = 0 THEN
                EXECUTE format('INSERT INTO public.%I (product_line, column_name, retailer, duplicate_key,
                    skip_missing_check, is_editable, is_active, is_del, created_at, created_id)
                    VALUES (''seuk_tv'',$1,$2,$3,$4,TRUE,TRUE,FALSE,NOW(),''setup_seuk_tv_layer2'')', retail_table)
                USING field, lower(seller), field='item', NOT (field=ANY(required));
            END IF;
        END LOOP;

        FOREACH field IN ARRAY required LOOP
            SELECT string_agg(value,'|' ORDER BY first_position) INTO display_cols
            FROM (SELECT value, MIN(position) AS first_position
                  FROM unnest(ARRAY['id','crawl_datetime','item','sku','retailer_sku_name',field,'product_url'])
                    WITH ORDINALITY AS cols(value,position) GROUP BY value) AS ordered;
            EXECUTE format('UPDATE public.%I SET check_type=''both'', display_columns=$1, query_columns=$1,
                query_days=0, is_active=TRUE, is_del=FALSE, updated_at=NOW(), updated_id=''setup_seuk_tv_layer2''
                WHERE group_id=$2 AND check_column=$3', column_table) USING display_cols, target_group_id, field;
            GET DIAGNOSTICS affected = ROW_COUNT;
            IF affected > 1 THEN RAISE EXCEPTION 'Duplicate SEUK TV NULL field: %.%', seller, field;
            ELSIF affected = 0 THEN
                EXECUTE format('INSERT INTO public.%I (group_id, check_column, check_type, display_columns,
                    query_columns, query_days, is_active, is_del, created_at, created_id)
                    VALUES ($1,$2,''both'',$3,$3,0,TRUE,FALSE,NOW(),''setup_seuk_tv_layer2'')', column_table)
                USING target_group_id, field, display_cols;
            END IF;
        END LOOP;
        EXECUTE format('SELECT COUNT(*) FROM public.%I WHERE group_id=$1 AND is_active AND NOT is_del', column_table)
        INTO affected USING target_group_id;
        IF affected <> cardinality(required) THEN RAISE EXCEPTION 'Unexpected SEUK TV NULL fields: %', seller; END IF;
    END LOOP;
END
$seuk_tv_layer2$;

COMMIT;
