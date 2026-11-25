(function () {
    'use strict';
    const form = document.getElementById('ccs-filters');
    if (!form) return;
    const catalog = JSON.parse(document.getElementById('ccs-catalog').textContent);
    const controls = Object.fromEntries(['country', 'product', 'retailer', 'days', 'date'].map(k => [k, document.getElementById('ccs-' + k)]));
    const message = document.getElementById('ccs-message');
    const results = document.getElementById('ccs-results');
    const detail = document.getElementById('ccs-detail');
    const overview = document.getElementById('ccs-overview');
    const groups = document.getElementById('ccs-groups');
    const overviewFilters = document.getElementById('ccs-overview-filters');
    const detailTemplate = document.getElementById('ccs-retailer-detail');
    const params = new URLSearchParams(location.search);
    const today = new Intl.DateTimeFormat('sv-SE', {timeZone: 'Asia/Seoul'}).format(new Date());
    const esc = value => String(value).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
    const number = value => Number(value).toLocaleString('ko-KR');
    const comparison = window.ColumnComparison;
    const notes = window.ColumnStatisticsNotes;
    let loadedData;
    let overviewData;
    let selectedStatus = 'all';
    let overviewStatus = 'all';
    let controller;
    let manualGuidesRequest;
    const detailRequests = new Map();
    const openRetailers = new Set();

    const countrySources = () => catalog.filter(source => source.country === controls.country.value);
    function options(control, values, preferred) {
        control.replaceChildren(...values.map(value => new Option(value === 'all' ? '전체' : value, value)));
        control.value = values.includes(preferred) ? preferred : values[0];
    }
    function retailers(preferred) {
        const sources = countrySources().filter(source => controls.product.value === 'all' || source.product === controls.product.value);
        const values = [...new Set(sources.flatMap(source => source.retailers))];
        options(controls.retailer, ['all', ...values], preferred);
    }
    function products(preferredProduct, preferredRetailer) {
        options(controls.product, ['all', ...countrySources().map(source => source.product)], preferredProduct);
        retailers(preferredRetailer);
    }
    options(controls.country, [...new Set(catalog.map(s => s.country))], params.get('country') || 'SEA');
    const countryOnly = params.has('country') && !params.has('product') && !params.has('retailer');
    products(params.get('product') || (countryOnly ? 'all' : 'TV'), params.get('retailer') || (countryOnly ? 'all' : 'Amazon'));
    if (['5', '7', '14', '28', '49'].includes(params.get('days'))) controls.days.value = params.get('days');
    controls.date.max = today;
    controls.date.value = /^\d{4}-\d{2}-\d{2}$/.test(params.get('date') || '') && params.get('date') <= today ? params.get('date') : today;
    controls.country.addEventListener('change', () => {products(controls.product.value, controls.retailer.value); invalidate();});
    controls.product.addEventListener('change', () => {retailers(controls.retailer.value); invalidate();});
    ['retailer', 'days', 'date'].forEach(key => controls[key].addEventListener('change', invalidate));
    function invalidate() {
        if (controller) controller.abort();
        loadedData = null;
        overviewData = null;
        results.hidden = true;
        message.hidden = false;
        message.className = 'cs-message';
        message.textContent = '선택한 조건으로 조회해주세요.';
        form.querySelector('button').disabled = false;
    }
    function renderTable(panel, data, status) {
        panel.querySelector('.ccs-status-filters').innerHTML = comparison.tabs(data.comparisons, status, false);
        panel.querySelector('thead').innerHTML = '<tr><th scope="col">수집 항목</th><th scope="col">검수 판정</th><th scope="col">평소 기준<small>이전 28일 중앙값</small></th>' + data.dates.map(day => `<th scope="col" class="${day === data.comparison_date ? 'ccs-target' : ''}">${esc(day.slice(5))}<small>${day === data.comparison_date ? '비교일' : '수집 건수'}</small></th>`).join('') + '<th scope="col">기준 대비<small>현재 ÷ 기준</small></th><th scope="col">증감 건수<small>현재 − 기준</small></th><th scope="col" class="ccs-note-col">비고<small>더블클릭으로 편집</small></th></tr>';
        let html = '<tr class="ccs-total"><th scope="row">실제 수집 데이터</th><td colspan="2">전체 건수</td>' + data.daily.map(day => `<td class="${day.date === data.comparison_date ? 'ccs-target' : ''}"><span class="${day.total === 0 ? 'ccs-zero' : ''}">${number(day.total)}</span>${day.total === 0 ? '<small>수집 데이터 없음</small>' : ''}</td>`).join('') + '<td>—</td><td>—</td><td>—</td></tr>';
        const visible = data.comparisons.filter(row => comparison.matches(row, status));
        html += visible.map(row => {
            const column = row.column;
            return `<tr data-column="${esc(column)}" class="${column === params.get('column') ? 'ccs-focused' : ''}"><th scope="row">${esc(column)}</th><td>${comparison.badge(row)}</td><td><strong>${comparison.number(row.baseline)}</strong><small>기준 이력 ${row.history_days}일</small></td>` + data.daily.map(day => {
                const target = day.date === data.comparison_date;
                return `<td class="${target ? 'ccs-target ' + esc(row.status) : ''}"><strong class="${day.total && day.counts[column] === 0 ? 'ccs-zero' : ''}">${day.total ? number(day.counts[column]) : '—'}</strong></td>`;
            }).join('') + `<td class="ccs-verdict ${esc(row.status)}">${comparison.ratio(row)}</td><td class="ccs-verdict ${esc(row.status)}">${comparison.delta(row)}</td><td class="ccs-note-col" data-note-column="${esc(column)}">—</td></tr>`;
        }).join('');
        if (!visible.length) html += `<tr><td colspan="${data.dates.length + 6}">해당 판정의 항목이 없습니다.</td></tr>`;
        const tbody = panel.querySelector('tbody');
        tbody.innerHTML = html;
        linkManualColumns(tbody, data);
        notes.render(tbody, data);
        const scroll = panel.querySelector('.ccs-scroll');
        scroll.hidden = false;
        scroll.scrollLeft = scroll.scrollWidth;
        const focused = panel.querySelector('.ccs-focused');
        if (focused) scroll.scrollTop = focused.offsetTop - 65;
    }

    function showUpdated(value) {
        document.getElementById('ccs-updated').textContent = value
            ? '집계 ' + new Date(value).toLocaleString('ko-KR', {timeZone: 'Asia/Seoul'}) : '';
    }

    function render(data) {
        loadedData = data;
        detail.hidden = false;
        overview.hidden = true;
        document.getElementById('ccs-selection').textContent = `${data.country} · ${data.product} · ${data.retailer} · 검수일 ${data.inspection_date} / 판정 데이터일 ${data.comparison_date} · ${data.dates[0]} ~ ${data.dates[data.dates.length - 1]} · ${data.columns.length}개 항목`;
        showUpdated(data.updated_at);
        renderTable(detail, data, selectedStatus);
        document.getElementById('ccs-sku-note').hidden = !data.sku_from_master;
        results.hidden = false;
        message.hidden = true;
        if (data.issue_history_error) {
            message.hidden = false;
            message.className = 'cs-message error';
            message.textContent = '수집 건수는 조회했지만 미해결 이력을 저장하지 못했습니다. 다시 조회해주세요.';
        }
        if (data.review_error) {
            message.hidden = false;
            message.className = 'cs-message error';
            message.textContent = '수집 건수는 조회했지만 검수 기록을 불러오지 못했습니다. 다시 조회해주세요.';
        }
    }
    document.getElementById('ccs-status-filters').addEventListener('click', event => {
        const button = event.target.closest('[data-status]');
        if (!button || !loadedData) return;
        selectedStatus = button.dataset.status;
        render(loadedData);
    });

    function scopeRows(row) {
        let missing = false;
        return (row.comparisons || []).filter(item => {
            if (item.status !== 'uncollected') return true;
            if (missing) return false;
            missing = true;
            return true;
        });
    }

    function statusBadges(rows) {
        const warnings = [
            ['abnormal', '이상'], ['review', '확인 필요'], ['uncollected', '전체 미수집'],
        ].map(([status, label]) => [status, label, rows.filter(row => comparison.matches(row, status)).length]);
        const badges = warnings.filter(([, , count]) => count).map(([status, label, count]) =>
            `<span class="ccs-badge ${status}">${label} ${number(count)}건</span>`);
        if (badges.length) return badges.join('');
        const state = rows.find(row => comparison.matches(row, 'normal')) || rows[0];
        return state ? comparison.badge(state) : '—';
    }

    function getJSON(url, signal) {
        return fetch(url, {signal}).then(async response => {
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || '조회에 실패했습니다.');
            return data;
        });
    }

    function linkManualColumns(tbody, {country, product, retailer}) {
        const rows = tbody.querySelectorAll('tr[data-column]');
        if (!rows.length) return;
        if (!manualGuidesRequest) {
            manualGuidesRequest = getJSON('/dx/layer1/api/column-alert-links/?guides_only=1').then(data => {
                if (data.manual_error) throw new Error('DX 매뉴얼 조회 실패');
                return data.guides;
            }).catch(() => {
                manualGuidesRequest = null;
                return {};
            });
        }

        const retailerKey = retailer.toLowerCase().replace(/[^a-z0-9]/g, '');
        manualGuidesRequest.then(guides => {
            for (const row of rows) {
                const column = row.dataset.column;
                const url = guides?.[`${country}|${product}|${retailerKey}|${column}`];
                if (!row.isConnected || !url?.startsWith('/dx/documents/manual/?')) continue;
                const link = document.createElement('a');
                link.className = 'ccs-manual-link';
                link.href = url;
                link.target = '_blank';
                link.rel = 'noopener noreferrer';
                link.setAttribute('aria-label', `${column} DX 매뉴얼 (새 탭)`);
                link.textContent = column;
                const icon = document.createElement('span');
                icon.setAttribute('aria-hidden', 'true');
                icon.textContent = '↗';
                link.append(icon);
                row.firstElementChild.replaceChildren(link);
            }
        });
    }

    const scopeKey = row => JSON.stringify([row.product, row.retailer]);

    function retailerCard(row, state, signal) {
        const card = document.createElement('details');
        const key = scopeKey(row);
        const names = (row.comparisons || []).filter(item => comparison.matches(item, 'attention'))
            .map(item => esc(item.column)).join(', ');
        card.innerHTML = `<summary class="ccs-overview-row ccs-retailer-summary"><span class="ccs-overview-title"><span class="ccs-disclosure" aria-hidden="true">▶</span><span><strong>${esc(row.retailer)}</strong>${names ? `<small>${names}</small>` : ''}</span></span><span>${row.error ? '—' : `${number(row.total)}건`}</span><span>${row.error ? '—' : `${number(row.column_count)}개`}</span><span class="ccs-overview-badges">${row.error ? '<span class="ccs-badge abnormal">조회 실패</span>' : statusBadges(scopeRows(row))}</span></summary>`;
        const panel = detailTemplate.content.firstElementChild.cloneNode(true);
        const notice = panel.querySelector('[role="status"]');
        card.append(panel);
        let tableLoaded = false;
        card.addEventListener('toggle', async () => {
            if (!card.isConnected || signal.aborted) return;
            if (!card.open) {
                openRetailers.delete(key);
                return;
            }
            openRetailers.add(key);
            if (tableLoaded) return;
            notice.textContent = '리테일러별 컬럼 건수를 불러오는 중입니다.';
            if (!detailRequests.has(key)) {
                const query = new URLSearchParams({country: state.country, product: row.product, retailer: row.retailer,
                                                   date: state.inspection_date, days: controls.days.value, prepared: '1'});
                detailRequests.set(key, getJSON('/dx/layer1/api/column-statistics/?' + query, signal));
            }
            const request = detailRequests.get(key);
            try {
                const data = await request;
                if (!card.isConnected || signal.aborted) return;
                window.ColumnAlertCache?.remember(data, data.inspection_date, data);
                notice.textContent = [data.review_error && '검수 기록을 불러오지 못했습니다.',
                                      data.issue_history_error && '미해결 이력을 저장하지 못했습니다.'].filter(Boolean).join(' ');
                panel.querySelector('.ccs-detail-sku-note').hidden = !data.sku_from_master;
                renderTable(panel, data, overviewStatus);
                panel.querySelector('.ccs-status-filters').onclick = event => {
                    const button = event.target.closest('[data-status]');
                    if (!button) return;
                    renderTable(panel, data, button.dataset.status);
                    panel.querySelector('.ccs-filter.active')?.focus();
                };
                tableLoaded = true;
            } catch (error) {
                if (detailRequests.get(key) === request) detailRequests.delete(key);
                if (card.isConnected && !signal.aborted) {
                    notice.textContent = `${error.message} 접었다 다시 펼쳐 조회하세요.`;
                }
            }
        });
        card.open = openRetailers.has(key);
        return card;
    }

    function renderOverview(data, signal) {
        overviewData = data;
        detail.hidden = true;
        overview.hidden = false;
        const eligible = data.rows.flatMap(scopeRows);
        overviewFilters.innerHTML = comparison.tabs(eligible, overviewStatus, false);
        const visible = data.rows.filter(row => row.error || overviewStatus === 'all' ||
            scopeRows(row).some(item => comparison.matches(item, overviewStatus)));
        const byProduct = new Map();
        for (const row of visible) {
            if (!byProduct.has(row.product)) byProduct.set(row.product, []);
            byProduct.get(row.product).push(row);
        }
        const cards = [...byProduct].map(([product, rows]) => {
            const card = document.createElement('details');
            card.className = 'ccs-product-group';
            card.open = true;
            const total = rows.reduce((sum, row) => sum + (row.total ?? 0), 0);
            const totalLabel = rows.some(row => row.error) ? '일부 조회 실패' : `${number(total)}건`;
            card.innerHTML = `<summary class="ccs-overview-row ccs-product-summary"><span class="ccs-overview-title"><span class="ccs-disclosure" aria-hidden="true">▶</span>${esc(product)}</span><span>${totalLabel}</span><span>리테일러 ${number(rows.length)}개</span><span class="ccs-overview-badges">${statusBadges(rows.flatMap(scopeRows))}</span></summary><div class="ccs-overview-row ccs-overview-head" aria-hidden="true"><span>리테일러</span><span>수집 건수</span><span>수집 항목</span><span>검수 판정</span></div>`;
            card.append(...rows.map(row => retailerCard(row, data, signal)));
            return card;
        });
        groups.replaceChildren(...cards);
        if (!cards.length) groups.innerHTML = '<p class="ccs-overview-empty">해당 판정의 항목이 없습니다.</p>';

        const dateLabel = [...new Set(data.rows.map(row => row.comparison_date))].sort().join(', ');
        const product = data.product === 'all' ? '전체 제품군' : data.product;
        const retailer = data.retailer === 'all' ? '전체 리테일러' : data.retailer;
        document.getElementById('ccs-selection').textContent = `${data.country} · ${product} · ${retailer} · 검수일 ${data.inspection_date} / 판정 데이터일 ${dateLabel} · ${number(data.rows.length)}개 조합`;
        document.getElementById('ccs-sku-note').hidden = true;
        showUpdated(data.updated_at);
        results.hidden = false;
        const notices = [data.rows.some(row => row.error) && '일부 리테일러의 통계를 조회하지 못했습니다. 다시 조회해주세요.',
                         data.review_error && '수집 건수는 조회했지만 검수 기록을 불러오지 못했습니다.'].filter(Boolean);
        message.hidden = !notices.length;
        if (notices.length) {
            message.className = 'cs-message error';
            message.textContent = notices.join(' ');
        }
    }

    overviewFilters.addEventListener('click', event => {
        const button = event.target.closest('[data-status]');
        if (!button || !overviewData) return;
        overviewStatus = button.dataset.status;
        renderOverview(overviewData, controller.signal);
        overviewFilters.querySelector('.ccs-filter.active')?.focus();
    });

    async function load() {
        if (!form.reportValidity()) return;
        if (controller) controller.abort();
        const current = new AbortController();
        controller = current;
        overviewData = null;
        loadedData = null;
        detailRequests.clear();
        notes.reset();
        openRetailers.clear();
        const query = new URLSearchParams(Object.fromEntries(Object.entries(controls).map(([key, el]) => [key, el.value])));
        history.replaceState(null, '', '?' + query);
        results.hidden = true;
        message.hidden = false;
        message.className = 'cs-message';
        message.textContent = '컬럼별 수집 건수를 불러오는 중입니다.';
        form.querySelector('button').disabled = true;
        try {
            const wide = controls.product.value === 'all' || controls.retailer.value === 'all';
            const endpoint = '/dx/layer1/api/column-statistics/' + (wide ? 'overview/' : '');
            const data = await getJSON(endpoint + '?' + query, current.signal);
            if (!current.signal.aborted) {
                if (wide) renderOverview(data, current.signal);
                else {
                    window.ColumnAlertCache?.remember(data, data.inspection_date, data);
                    render(data);
                }
            }
        } catch (error) {
            if (current.signal.aborted) return;
            message.className = 'cs-message error';
            message.textContent = error.message || '조회에 실패했습니다.';
        } finally {
            if (controller === current) form.querySelector('button').disabled = false;
        }
    }
    form.addEventListener('submit', event => {event.preventDefault(); load();});
    document.addEventListener('column-review-saved', event => {
        const {target, comparison: reviewed} = event.detail;
        if (loadedData && ['country','product','retailer'].every(k => loadedData[k] === target[k])
            && loadedData.comparison_date === target.source_date) load();
        if (!overviewData || !reviewed || overviewData.country !== target.country) return;
        const scope = overviewData.rows.find(row => row.product === target.product && row.retailer === target.retailer
                                                  && row.comparison_date === target.source_date);
        const column = scope?.comparisons?.find(row => row.column === reviewed.column);
        if (column) {
            Object.assign(column, {status: reviewed.status, review: reviewed.review});
            detailRequests.delete(scopeKey(scope));
            renderOverview(overviewData, controller.signal);
        }
    });
    load();
})();
