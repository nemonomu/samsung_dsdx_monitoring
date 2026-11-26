// Copy-only queries for the batches displayed on Layer 1 retail cards.
(function() {
    var entries = {};
    var active = null;
    var modal = 'retail-query';

    function literal(value) {
        return "'" + String(value).replace(/'/g, "''") + "'";
    }

    function source(country, product) {
        if (country === 'SEUK' && ['TV', 'REF', 'LDY', 'LDY_DRYER'].includes(product)) {
            return {table: 'dx_seuk.dx_seuk_' + product.toLowerCase() + '_retail_com', dateColumn: 'crawl_datetime'};
        }
        if (country === 'SEIB' && ['TV', 'REF', 'LDY', 'LDY_DRYER'].includes(product)) {
            return { table: 'dx_seib.dx_seib_' + product.toLowerCase() + '_retail_com', dateColumn: 'crawl_datetime' };
        }
        if (country === 'SEM' && product === 'LDY_DRYER') {
            return { table: 'dx_sem.dx_sem_ldy_dryer_retail_com', dateColumn: 'crawl_datetime' };
        }
        if (country === 'SEA' && product === 'LDY_DRYER') {
            return { table: 'public.ldy_dryer_retail', dateColumn: 'crawl_datetime' };
        }
        if (country === 'SEG' && product === 'LDY_DRYER') {
            return { table: 'dx_seg.dx_seg_ldy_dryer_retail', dateColumn: 'crawl_datetime' };
        }
        if (!['SEA', 'SEDA', 'SIEL', 'SEG', 'TSE', 'SEM'].includes(country) ||
                !['TV', 'REF', 'LDY'].includes(product)) return null;
        var key = product.toLowerCase();
        return {
            table: country === 'SEA' ? 'public.' + key + '_retail_com'
                : 'dx_' + country.toLowerCase() + '.dx_' + country.toLowerCase() + '_' + key + '_retail_com',
            dateColumn: country === 'SEG' || country === 'SEDA' ||
                (country === 'SEA' && product !== 'TV')
                ? 'crawl_strdatetime' : 'crawl_datetime'
        };
    }

    function buildQuery(country, product, retailer, batch, day) {
        if (country === 'SIEL' && retailer === 'Jiomart') return '';
        if (country === 'SEA' && product === 'LDY_DRYER' && !['Bestbuy', 'Costco'].includes(retailer)) return '';
        var config = source(country, product);
        if (!config || !retailer || !batch || !/^\d{4}-\d{2}-\d{2}$/.test(day || '')) return '';
        // SEA summaries join multiple collected batch IDs with a comma.
        var batches = [...new Set(String(batch).split(',').map(function(value) { return value.trim(); }).filter(Boolean))];
        if (!batches.length) return '';
        var batchFilter = batches.length === 1 ? '= ' + literal(batches[0])
            : 'IN (' + batches.map(literal).join(', ') + ')';
        var accountName = retailer;
        if (country === 'SEG' && accountName === 'Expert') accountName = 'expert';
        // SEDA cards display "Casas Bahia"; the collected account is CasasBahia.
        if (country === 'SEDA' && accountName === 'Casas Bahia') {
            accountName = 'CasasBahia';
        }
        var newSemTv = country === 'SEM' && product === 'TV' && ['Walmart', "Sam's Club"].includes(retailer);
        var dateFilter = config.dateColumn + ' >= ' + literal(day);
        var accountFilter = 'account_name = ' + literal(accountName);
        if (newSemTv) {
            dateFilter = 'LEFT(BTRIM(CAST(' + config.dateColumn + ' AS TEXT)), 10) = ' + literal(day);
            accountFilter = 'LOWER(BTRIM(account_name)) = LOWER(' + literal(accountName) + ')';
            batchFilter = '= ' + literal(batch);
        }
        if (country === 'SEUK' && product === 'TV') {
            var next = new Date(day + 'T00:00:00Z');
            if (!Number.isFinite(next.getTime())) return '';
            next.setUTCDate(next.getUTCDate() + 1);
            dateFilter += '\n  AND ' + config.dateColumn + ' < ' + literal(next.toISOString().slice(0, 10));
        } else if (country === 'SEIB' || country === 'SEUK' || (['SEM', 'SEG'].includes(country) && product === 'LDY_DRYER')) {
            dateFilter = 'LEFT(BTRIM(CAST(' + config.dateColumn + ' AS TEXT)), 10) = ' + literal(day);
        } else if (country === 'SEA' && accountName === 'Costco') {
            dateFilter = '(' + config.dateColumn + "::timestamptz AT TIME ZONE 'Asia/Seoul')::date = " + literal(day) + '::date';
        } else if (country === 'SEA' && product === 'LDY_DRYER' && accountName === 'Bestbuy') {
            dateFilter = 'LEFT(BTRIM(CAST(' + config.dateColumn + ' AS TEXT)), 10) = ' + literal(day);
        }
        return 'SELECT *\nFROM ' + config.table + '\nWHERE ' + dateFilter +
            '\n  AND ' + accountFilter +
            '\n  AND batch_id ' + batchFilter + '\nORDER BY item, ' + config.dateColumn + ';';
    }

    function options(entry) {
        var cat = entry.category;
        var summary = entry.country === 'SEA' && typeof getRetailSummaryData === 'function'
            ? getRetailSummaryData(entry.product) : null;
        var result = [];
        function add(retailer, batch, query) {
            if (!retailer) return;
            batch = batch || '';
            if (!result.some(function(row) { return row.retailer === retailer && row.batch === batch; })) {
                result.push({ retailer: retailer, batch: batch, query: query });
            }
        }
        if (summary && summary.summary && summary.summary.length) {
            summary.summary.forEach(function(retailer) {
                var rows = retailer.rows || [];
                if (!rows.length) add(retailer.retailer, retailer.batch_id);
                rows.forEach(function(row) { add(retailer.retailer, row.batch_id || retailer.batch_id); });
            });
        } else {
            (cat.retailers || []).forEach(function(row) { add(row.retailer, row.batch_id, row.copy_query); });
            (cat.time_slots || []).forEach(function(slot) {
                (slot.retailers || []).forEach(function(row) { add(row.retailer, row.batch_id); });
            });
        }
        var day = summary && summary.source_date || cat.source_date || entry.context.source_date;
        if (!day) {
            day = entry.context.inspection_date || entry.inspectionDate;
            if (entry.country === 'SEA' && /^\d{4}-\d{2}-\d{2}$/.test(day || '')) {
                var date = new Date(day + 'T00:00:00Z');
                date.setUTCDate(date.getUTCDate() - 1);
                day = date.toISOString().slice(0, 10);
            }
        }
        return { rows: result, day: day || '' };
    }

    function button(country, category, checkIdx, catIdx, context) {
        var product = String(category.name || category.category || '').toUpperCase();
        if (!source(country, product)) return '';
        var key = country + '-' + checkIdx + '-' + catIdx;
        entries[key] = {
            country: country, product: product, category: category, context: context || {},
            inspectionDate: typeof getSelectedDate === 'function' ? getSelectedDate() : ''
        };
        return '<button type="button" class="l1-retail-query-button" ' +
            'onclick="event.stopPropagation();L1.retailQuery.open(\'' + key + '\')">전체 조회 SQL</button>';
    }

    function optionLabel(retailer, batch) {
        return retailer + ' / ' + (batch || '수집 배치 없음');
    }

    function open(key) {
        var entry = entries[key];
        if (!entry) return;
        var data = options(entry);
        active = { entry: entry, rows: data.rows, sourceDay: data.day, query: '', requestId: 0 };
        AppModal.create(modal, { style: 'wide', closeOnOverlay: true });
        AppModal.setTitle(modal, entry.country + ' · ' + entry.product + ' 전체 조회 SQL');
        var optionHtml = data.rows.map(function(row, index) {
            return '<option value="' + index + '">' + esc(optionLabel(row.retailer, row.batch)) + '</option>';
        }).join('');
        AppModal.setBody(modal,
            '<div class="l1-retail-query-controls"><label>리테일러 <select id="l1-query-retailer" onchange="L1.retailQuery.update()">' +
            (optionHtml || '<option value="">수집 데이터 없음</option>') + '</select></label>' +
            '<label>데이터일 <input type="date" id="l1-query-date" value="' + esc(data.day) + '" onchange="L1.retailQuery.update()"></label></div>' +
            '<div class="l1-retail-query-box"><div class="l1-retail-query-header"><span>전체 조회 SQL</span>' +
            '<button type="button" id="l1-query-copy" onclick="L1.retailQuery.copy()">복사</button></div>' +
            '<pre id="l1-query-sql"></pre></div>');
        update();
        AppModal.open(modal);
    }

    function setQuery(query, message) {
        active.query = query;
        document.getElementById('l1-query-sql').textContent = query || message;
        document.getElementById('l1-query-copy').disabled = !query;
    }

    async function loadJiomartQuery(state, requestId, day, option) {
        setQuery('', '선택한 데이터일의 배치를 조회하는 중입니다.');
        try {
            var params = new URLSearchParams({
                check_type: 'siel_retail', product_line: 'siel_' + state.entry.product.toLowerCase(),
                source_date: day, retailer: 'Jiomart'
            });
            var response = await fetch('/dx/layer1/api/retail-batches/?' + params.toString());
            if (!response.ok) throw new Error('batch request failed');
            var data = await response.json();
            if (active !== state || state.requestId !== requestId) return;
            var batch = data.batches.find(function(entry) { return entry.applied; });
            if (option) option.textContent = optionLabel('Jiomart', batch && batch.batch_id);
            setQuery(batch ? batch.sql : '', '선택한 데이터일에 집계된 배치가 없습니다.');
        } catch (_) {
            if (active === state && state.requestId === requestId) {
                setQuery('', '선택한 데이터일의 배치를 조회하지 못했습니다.');
            }
        }
    }

    function update() {
        if (!active || !active.entry) return;
        var select = document.getElementById('l1-query-retailer');
        var day = document.getElementById('l1-query-date').value;
        var row = active.rows[Number(select.value)];
        var requestId = ++active.requestId;
        if (active.entry.country === 'SIEL') {
            var index = active.rows.findIndex(function(entry) { return entry.retailer === 'Jiomart'; });
            var option = index >= 0 ? select.options[index] : null;
            if (option) option.textContent = day === active.sourceDay
                ? optionLabel('Jiomart', active.rows[index].batch) : 'Jiomart';
            if (row && row.retailer === 'Jiomart' && day !== active.sourceDay && /^\d{4}-\d{2}-\d{2}$/.test(day)) {
                return loadJiomartQuery(active, requestId, day, option);
            }
        }
        var query = row && row.query && day === active.sourceDay ? row.query
            : row ? buildQuery(active.entry.country, active.entry.product, row.retailer, row.batch, day) : '';
        var message = row && !row.batch ? '수집 배치가 없어 조회 SQL을 만들 수 없습니다.' : '리테일러와 데이터일을 확인해주세요.';
        setQuery(query, message);
    }

    function showSql(title, sql) {
        active = { query: sql || '' };
        AppModal.create(modal, { style: 'wide', closeOnOverlay: true });
        AppModal.setTitle(modal, title);
        AppModal.setBody(modal, '<div class="l1-retail-query-box"><div class="l1-retail-query-header"><span>배치 원본 조회 SQL</span>' +
            '<button type="button" onclick="L1.retailQuery.copy()">복사</button></div><pre id="l1-query-sql"></pre></div>');
        document.getElementById('l1-query-sql').textContent = active.query;
        AppModal.open(modal);
    }

    async function copy() {
        if (!active || !active.query) return;
        try {
            if (navigator.clipboard && window.isSecureContext) {
                await navigator.clipboard.writeText(active.query);
            } else {
                var field = document.createElement('textarea');
                field.value = active.query;
                field.style.position = 'fixed';
                field.style.opacity = '0';
                // Keep the fallback inside the open modal's focus scope.
                AppModal.getBody(modal).appendChild(field);
                try {
                    field.select();
                    if (!document.execCommand('copy')) throw new Error('Copy failed');
                } finally { field.remove(); }
            }
            showToast('SQL을 복사했습니다.');
        } catch (_) { showToast('복사하지 못했습니다. SQL을 선택해 복사해주세요.', 'error'); }
    }

    L1.retailQuery = { button: button, open: open, update: update, copy: copy,
        buildQuery: buildQuery, options: options, showSql: showSql };
})();
