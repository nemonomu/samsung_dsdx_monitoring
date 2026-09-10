// Copy-only queries for the batches displayed on Layer 1 retail cards.
(function() {
    var entries = {};
    var active = null;
    var modal = 'retail-query';

    function literal(value) {
        return "'" + String(value).replace(/'/g, "''") + "'";
    }

    function source(country, product) {
        if (!['SEA', 'SIEL', 'SEG', 'TSE', 'SEM'].includes(country) ||
                !['TV', 'REF', 'LDY'].includes(product)) return null;
        var key = product.toLowerCase();
        return {
            table: country === 'SEA' ? 'public.' + key + '_retail_com'
                : 'dx_' + country.toLowerCase() + '.dx_' + country.toLowerCase() + '_' + key + '_retail_com',
            dateColumn: country === 'SEG' || (country === 'SEA' && product !== 'TV')
                ? 'crawl_strdatetime' : 'crawl_datetime',
            timestamp: country === 'SIEL'
        };
    }

    function buildQuery(country, product, retailer, batch, day) {
        var config = source(country, product);
        if (!config || !retailer || !batch || !/^\d{4}-\d{2}-\d{2}$/.test(day || '')) return '';
        // SEA summaries join multiple collected batch IDs with a comma.
        var batches = [...new Set(String(batch).split(',').map(function(value) { return value.trim(); }).filter(Boolean))];
        if (!batches.length) return '';
        var batchFilter = batches.length === 1 ? '= ' + literal(batches[0])
            : 'IN (' + batches.map(literal).join(', ') + ')';
        var dateFilter = config.timestamp
            ? config.dateColumn + ' >= (' + literal(day) + "::date::timestamp AT TIME ZONE 'Asia/Seoul')"
            : config.dateColumn + ' >= ' + literal(day);
        return 'SELECT *\nFROM ' + config.table + '\nWHERE LOWER(BTRIM(account_name)) = ' +
            literal(retailer.trim().toLowerCase()) + '\n  AND ' + dateFilter +
            '\n  AND batch_id ' + batchFilter + '\nORDER BY ' + config.dateColumn + ';';
    }

    function options(entry) {
        var cat = entry.category;
        var summary = entry.country === 'SEA' && typeof getRetailSummaryData === 'function'
            ? getRetailSummaryData(entry.product) : null;
        var result = [];
        function add(retailer, batch) {
            if (!retailer) return;
            batch = batch || '';
            if (!result.some(function(row) { return row.retailer === retailer && row.batch === batch; })) {
                result.push({ retailer: retailer, batch: batch });
            }
        }
        if (summary && summary.summary && summary.summary.length) {
            summary.summary.forEach(function(retailer) {
                var rows = retailer.rows || [];
                if (!rows.length) add(retailer.retailer, retailer.batch_id);
                rows.forEach(function(row) { add(retailer.retailer, row.batch_id || retailer.batch_id); });
            });
        } else {
            (cat.retailers || []).forEach(function(row) { add(row.retailer, row.batch_id); });
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

    function open(key) {
        var entry = entries[key];
        if (!entry) return;
        var data = options(entry);
        active = { entry: entry, rows: data.rows, query: '' };
        AppModal.create(modal, { style: 'wide', closeOnOverlay: true });
        AppModal.setTitle(modal, entry.country + ' · ' + entry.product + ' 전체 조회 SQL');
        var optionHtml = data.rows.map(function(row, index) {
            return '<option value="' + index + '">' + esc(row.retailer + ' / ' + (row.batch || '수집 배치 없음')) + '</option>';
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

    function update() {
        if (!active) return;
        var select = document.getElementById('l1-query-retailer');
        var day = document.getElementById('l1-query-date');
        var row = active.rows[Number(select.value)];
        active.query = row ? buildQuery(active.entry.country, active.entry.product,
            row.retailer, row.batch, day.value) : '';
        document.getElementById('l1-query-sql').textContent = active.query ||
            (row && !row.batch ? '수집 배치가 없어 조회 SQL을 만들 수 없습니다.' : '리테일러와 데이터일을 확인해주세요.');
        document.getElementById('l1-query-copy').disabled = !active.query;
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
        buildQuery: buildQuery, options: options };
})();
