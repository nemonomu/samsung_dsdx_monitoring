/**
 * Layer 4 보고서
 */

(function() {
    'use strict';

    var reportCache = null;

    // 리테일러 고정 정렬 순서
    var RETAILER_ORDER = [
        'TV Amazon', 'TV Bestbuy', 'TV Walmart',
        'HOMEPRO TV', 'HOMEPRO REF', 'HOMEPRO LDY'
    ];

    var TSE_TABLE_CATEGORY = {
        'dx_tse.dx_tse_tv_retail_com': 'TV',
        'dx_tse.dx_tse_ref_retail_com': 'REF',
        'dx_tse.dx_tse_ldy_retail_com': 'LDY'
    };

    function reportRetailerName(tableName, retailer, fallbackCategory) {
        var tseCategory = TSE_TABLE_CATEGORY[tableName];
        if (tseCategory) {
            var tseRetailer = String(retailer || 'TSE').trim().toUpperCase();
            return tseRetailer + ' ' + tseCategory;
        }
        var category = fallbackCategory || tableName;
        return retailer ? (category + ' ' + retailer) : category;
    }

    function sortRetailerKeys(keys) {
        return keys.sort(function(a, b) {
            var ia = RETAILER_ORDER.indexOf(a);
            var ib = RETAILER_ORDER.indexOf(b);
            if (ia === -1) ia = 9999;
            if (ib === -1) ib = 9999;
            return ia - ib;
        });
    }

    // DOM 헬퍼
    function createDiv(className, text) {
        var el = document.createElement('div');
        if (className) el.className = className;
        if (text) el.textContent = text;
        return el;
    }

    function createReportTable(parentEl, columns, data, renderRow) {
        var container = document.createElement('div');
        container.style.margin = '8px 0 16px';
        parentEl.appendChild(container);
        var table = new CommonTable(container, {
            variant: 'detail', columns: columns, resize: false, vlines: true, bordered: true
        });
        table.render();
        table.renderBody(data, renderRow);
        return table;
    }

    // ============================================================
    // 보고서 저장
    // ============================================================
    window.saveReportToDocument = function() {
        var el = document.getElementById('report-detail');
        var rawContent = el ? el.innerHTML : '';
        if (!rawContent || rawContent.indexOf('l4-empty-state') >= 0) {
            showToast('저장할 보고서가 없습니다.', 'warning');
            return;
        }

        var content = rawContent
            .replace(/<div class="report-title"[^>]*>.*?<\/div>/i, '')
            .replace(/<div class="report-section-title"/g, '<br><div class="report-section-title"');

        var date = getSelectedDate();
        var title = date + ' DX 검수 보고서';
        var categoryId = '20260207-0002';

        var btn = document.getElementById('saveReportBtn');
        btn.disabled = true;

        fetch('/api/dx/documents/create/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({
                category_id: categoryId,
                title: title,
                content: content,
                crawl_date: date
            })
        })
        .then(function(r) { return r.json(); })
        .then(function(res) {
            btn.disabled = false;
            if (res.success) {
                showToast(res.message || '검수 보고서가 저장되었습니다.', 'success');
            } else {
                showToast(res.error || '보고서 저장에 실패했습니다.', 'info');
            }
        })
        .catch(function() {
            btn.disabled = false;
            showToast('보고서 저장 중 오류가 발생했습니다.', 'error');
        });
    };

    // ============================================================
    // 보고서 로드
    // ============================================================
    function loadReport() {
        var date = getSelectedDate();
        if (!date) return;

        fetch('/dx/layer4/api/report/?date=' + encodeURIComponent(date))
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.success) {
                    showToast(data.error || '조회 실패', 'error');
                    return;
                }
                reportCache = data;
                renderReport(data);
            })
            .catch(function(e) {
                console.error(e);
                showToast('보고서 조회 중 오류가 발생했습니다.', 'error');
            });
    }

    // ============================================================
    // 섹션 렌더러: 리테일러별 그룹 (NULL / 형식 / 누락필드)
    // ============================================================
    function renderRetailerGroupedSection(parentEl, sectionNo, typeName, tableGroups, typeSummaryData, itemField, itemLabel) {
        if (!tableGroups || Object.keys(tableGroups).length === 0) return;
        var corrected = (typeSummaryData && typeSummaryData.corrected) || 0;
        var normal = (typeSummaryData && typeSummaryData.normal) || 0;
        var total = corrected + normal;

        var section = createDiv('report-section');
        section.appendChild(createDiv('report-section-title',
            '■ ' + sectionNo + '. ' + typeName + ' (' + total + '건)'));

        var TABLE_CATEGORY = { 'tv_retail_com': 'TV' };

        var retailerData = {};
        Object.keys(tableGroups).forEach(function(tn) {
            var category = TABLE_CATEGORY[tn] || tn;
            tableGroups[tn].forEach(function(d) {
                var retailerName = reportRetailerName(tn, d.retailer, category);
                if (!retailerData[retailerName]) retailerData[retailerName] = { total: 0, groups: {} };
                retailerData[retailerName].total++;

                var action, groupKey;
                if (d.status === 'normal') {
                    action = d.reason || '확인';
                    groupKey = 'normal|' + (d.column_name || '') + '|' + action;
                } else {
                    action = (d.column_name || '') + ' 수정';
                    groupKey = 'corrected|' + (d.column_name || '');
                }

                if (!retailerData[retailerName].groups[groupKey]) {
                    retailerData[retailerName].groups[groupKey] = { column: d.column_name || '', action: action, items: [], count: 0 };
                }
                retailerData[retailerName].groups[groupKey].count++;
                var val = d[itemField];
                if (val) retailerData[retailerName].groups[groupKey].items.push(val);
            });
        });

        var allRows = [];
        sortRetailerKeys(Object.keys(retailerData)).forEach(function(name) {
            var rd = retailerData[name];
            var rows = Object.keys(rd.groups).map(function(gk) {
                var g = rd.groups[gk];
                var uniqueItems = g.items.filter(function(v, i, a) { return a.indexOf(v) === i; });
                return { retailer: name, column: g.column, count: g.count, item: uniqueItems.join(', '), action: g.action };
            });
            rows.sort(function(a, b) { return a.column.localeCompare(b.column); });
            allRows = allRows.concat(rows);
        });

        // 리테일러 rowspan
        var retailerSpanMap = {};
        var retailerSkipSet = {};
        var ri = 0;
        while (ri < allRows.length) {
            var curRetailer = allRows[ri].retailer;
            var spanCount = 1;
            while (ri + spanCount < allRows.length && allRows[ri + spanCount].retailer === curRetailer) {
                retailerSkipSet[ri + spanCount] = true;
                spanCount++;
            }
            if (spanCount > 1) retailerSpanMap[ri] = spanCount;
            ri += spanCount;
        }

        // 필드 rowspan
        var fieldSpanMap = {};
        var fieldSkipSet = {};
        ri = 0;
        while (ri < allRows.length) {
            var curRetailer2 = allRows[ri].retailer;
            var curCol = allRows[ri].column;
            var spanCount2 = 1;
            while (ri + spanCount2 < allRows.length && allRows[ri + spanCount2].retailer === curRetailer2 && allRows[ri + spanCount2].column === curCol) {
                fieldSkipSet[ri + spanCount2] = true;
                spanCount2++;
            }
            if (spanCount2 > 1) fieldSpanMap[ri] = spanCount2;
            ri += spanCount2;
        }

        var fieldWidth = typeName === '누락필드 검증' ? 240 : 140;
        createReportTable(section, [
            { key: 'retailer', label: '리테일러', width: 120 },
            { key: 'column', label: '필드', width: fieldWidth },
            { key: 'count', label: '건수', width: 60, align: 'center' },
            { key: 'item', label: itemLabel },
            { key: 'action', label: '조치 및 확인사항' }
        ], allRows, function(d, idx) {
            var retailerTd = '';
            if (!retailerSkipSet[idx]) {
                var rSpan = retailerSpanMap[idx];
                var rSpanAttr = rSpan ? ' rowspan="' + rSpan + '"' : '';
                retailerTd = '<td' + rSpanAttr + ' style="vertical-align:middle;">' + L4.escapeHtml(d.retailer) + '</td>';
            }
            var fieldTd = '';
            if (!fieldSkipSet[idx]) {
                var fSpan = fieldSpanMap[idx];
                var fSpanAttr = fSpan ? ' rowspan="' + fSpan + '"' : '';
                fieldTd = '<td' + fSpanAttr + ' style="vertical-align:middle;">' + L4.escapeHtml(d.column) + '</td>';
            }
            return '<tr>'
                + retailerTd
                + fieldTd
                + '<td style="text-align:center">' + d.count + '</td>'
                + '<td>' + L4.escapeHtml(d.item) + '</td>'
                + '<td>' + L4.escapeHtml(d.action) + '</td>'
                + '</tr>';
        });

        parentEl.appendChild(section);
    }

    // ============================================================
    // 섹션 렌더러: 중복검증
    // ============================================================
    function renderDuplicateSection(parentEl, sectionNo, typeName, tableGroups, typeSummaryData) {
        if (!tableGroups || Object.keys(tableGroups).length === 0) return;
        var corrected = (typeSummaryData && typeSummaryData.corrected) || 0;
        var normal = (typeSummaryData && typeSummaryData.normal) || 0;
        var total = corrected + normal;

        var section = createDiv('report-section');
        section.appendChild(createDiv('report-section-title',
            '■ ' + sectionNo + '. ' + typeName + ' (' + total + '건)'));

        var TABLE_CATEGORY = { 'tv_retail_com': 'TV' };

        var retailerData = {};
        Object.keys(tableGroups).forEach(function(tn) {
            var category = TABLE_CATEGORY[tn] || tn;
            tableGroups[tn].forEach(function(d) {
                var retailerName = reportRetailerName(tn, d.retailer, category);
                if (!retailerData[retailerName]) retailerData[retailerName] = { total: 0, items: [], action: '' };
                retailerData[retailerName].total++;
                if (d.item) retailerData[retailerName].items.push(d.item);
                if (!retailerData[retailerName].action) {
                    retailerData[retailerName].action = d.memo || '중복 삭제';
                }
            });
        });

        var rows = sortRetailerKeys(Object.keys(retailerData)).map(function(name) {
            var rd = retailerData[name];
            var uniqueItems = rd.items.filter(function(v, i, a) { return a.indexOf(v) === i; });
            return { retailer: name, count: rd.total, item: uniqueItems.join(', '), action: rd.action };
        });

        createReportTable(section, [
            { key: 'retailer', label: '리테일러', width: 140 },
            { key: 'count', label: '건수', width: 60, align: 'center' },
            { key: 'item', label: 'Item' },
            { key: 'action', label: '조치 및 확인사항' }
        ], rows, function(d) {
            return '<tr>'
                + '<td>' + L4.escapeHtml(d.retailer) + '</td>'
                + '<td style="text-align:center">' + d.count + '</td>'
                + '<td>' + L4.escapeHtml(d.item) + '</td>'
                + '<td>' + L4.escapeHtml(d.action) + '</td>'
                + '</tr>';
        });

        parentEl.appendChild(section);
    }

    // ============================================================
    // 섹션 렌더러: 크로스필드 검증
    // ============================================================
    function renderCrossfieldSection(parentEl, sectionNo, typeName, tableGroups, typeSummaryData) {
        if (!tableGroups || Object.keys(tableGroups).length === 0) return;
        var corrected = (typeSummaryData && typeSummaryData.corrected) || 0;
        var normal = (typeSummaryData && typeSummaryData.normal) || 0;
        var total = corrected + normal;

        var section = createDiv('report-section');
        section.appendChild(createDiv('report-section-title',
            '■ ' + sectionNo + '. ' + typeName + ' (' + total + '건)'));

        var TABLE_CATEGORY = { 'tv_retail_com': 'TV' };

        var ruleGroups = {};
        Object.keys(tableGroups).forEach(function(tn) {
            var category = TABLE_CATEGORY[tn] || tn;
            tableGroups[tn].forEach(function(d) {
                var ruleKey = d.detail_code || d.rule_name || '규칙 ' + (d.rule_id || 0);
                if (!ruleGroups[ruleKey]) ruleGroups[ruleKey] = { name: d.rule_name || ruleKey, items: [] };
                var item = Object.assign({}, d);
                item._category = category;
                item._tableName = tn;
                ruleGroups[ruleKey].items.push(item);
            });
        });

        var ruleIdx = 1;
        Object.keys(ruleGroups).forEach(function(ruleKey) {
            var rg = ruleGroups[ruleKey];
            section.appendChild(createDiv('rpt-sub-title',
                '(' + ruleIdx + ') ' + rg.name + ' (' + rg.items.length + '건)'));

            var retailerData = {};
            rg.items.forEach(function(d) {
                var retailerName = reportRetailerName(
                    d._tableName, d.retailer, d._category
                );
                if (!retailerData[retailerName]) retailerData[retailerName] = { total: 0, groups: {} };
                retailerData[retailerName].total++;

                var action, groupKey;
                if (d.status === 'normal') {
                    action = d.reason || '확인';
                    groupKey = 'normal|' + action;
                } else {
                    action = '수정';
                    groupKey = 'corrected';
                }

                if (!retailerData[retailerName].groups[groupKey]) {
                    retailerData[retailerName].groups[groupKey] = { action: action, items: [], count: 0 };
                }
                retailerData[retailerName].groups[groupKey].count++;
                if (d.item) retailerData[retailerName].groups[groupKey].items.push(d.item);
            });

            var rows = [];
            sortRetailerKeys(Object.keys(retailerData)).forEach(function(name) {
                var rd = retailerData[name];
                Object.keys(rd.groups).forEach(function(gk) {
                    var g = rd.groups[gk];
                    var uniqueItems = g.items.filter(function(v, i, a) { return a.indexOf(v) === i; });
                    rows.push({ retailer: name, count: g.count, item: uniqueItems.join(', '), action: g.action });
                });
            });

            var cfRetailerSpanMap = {};
            var cfRetailerSkipSet = {};
            var cri = 0;
            while (cri < rows.length) {
                var curR = rows[cri].retailer;
                var rSpan = 1;
                while (cri + rSpan < rows.length && rows[cri + rSpan].retailer === curR) {
                    cfRetailerSkipSet[cri + rSpan] = true;
                    rSpan++;
                }
                if (rSpan > 1) cfRetailerSpanMap[cri] = rSpan;
                cri += rSpan;
            }

            createReportTable(section, [
                { key: 'retailer', label: '리테일러', width: 120 },
                { key: 'count', label: '건수', width: 60, align: 'center' },
                { key: 'item', label: 'Item' },
                { key: 'action', label: '조치 및 확인사항' }
            ], rows, function(d, idx) {
                var rTd = '';
                if (!cfRetailerSkipSet[idx]) {
                    var span = cfRetailerSpanMap[idx];
                    var spanAttr = span ? ' rowspan="' + span + '"' : '';
                    rTd = '<td' + spanAttr + ' style="vertical-align:middle;">' + L4.escapeHtml(d.retailer) + '</td>';
                }
                return '<tr>'
                    + rTd
                    + '<td style="text-align:center">' + d.count + '</td>'
                    + '<td>' + L4.escapeHtml(d.item) + '</td>'
                    + '<td>' + L4.escapeHtml(d.action) + '</td>'
                    + '</tr>';
            });

            ruleIdx++;
        });

        parentEl.appendChild(section);
    }

    // ============================================================
    // 보고서 메인 렌더링
    // ============================================================
    function renderReport(data) {
        var detailEl = document.getElementById('report-detail');

        var date = data.date || '';
        var collectionStatus = data.collection_status || [];
        var collectionIssues = data.collection_issues || [];
        var typeSummary = data.type_summary || {};
        var groupedDetails = data.grouped_details || {};

        var totalCorrected = 0, totalNormal = 0;
        Object.keys(typeSummary).forEach(function(ct) {
            totalCorrected += (typeSummary[ct].corrected || 0);
            totalNormal += (typeSummary[ct].normal || 0);
        });

        var hasCollection = collectionStatus.length > 0;
        var hasIssues = collectionIssues.length > 0;
        var hasCorrections = totalCorrected > 0 || totalNormal > 0;

        if (!hasCollection && !hasIssues && !hasCorrections) {
            detailEl.innerHTML = '<div class="l4-empty-state"><p>해당 날짜에 검수 기록이 없습니다.</p></div>';
            return;
        }

        detailEl.innerHTML = '';
        detailEl.appendChild(createDiv('report-title', '[DX] ' + date + ' 검수 보고서'));

        // ━━━ 요약 테이블 ━━━
        var summarySection = createDiv('report-section');
        summarySection.appendChild(createDiv('report-section-title', '■ 요약'));

        var issueCount = collectionIssues.length;
        var TYPES_ORDER = ['null_check', 'duplicate_check', 'format_check', 'cross_field', 'field_missing'];
        var TABLE_SECTION = {
            'tv_retail_com': 'Retail',
            'youtube_collection_logs': 'YouTube', 'youtube_videos': 'YouTube', 'youtube_comments': 'YouTube',
            'market_trend': 'Market Trend', 'market_comp_product': 'Market', 'market_comp_event': 'Market',
            'openai_forecast_results': '수요증감율'
        };

        var collMemos = [];
        collectionStatus.forEach(function(cs) {
            if (cs.memo) {
                var name = L4.CHECK_SECTION_NAMES[cs.section] || cs.section;
                collMemos.push(name + ':\n' + cs.memo);
            }
        });
        var collRemarks = collMemos.length > 0 ? collMemos.join('\n') : '특이사항 없음';
        var summaryData = [{ category: '수집현황', count: issueCount + '건', remarks: collRemarks }];

        TYPES_ORDER.forEach(function(ct) {
            var c = typeSummary[ct] || {};
            var total = (c.corrected || 0) + (c.normal || 0);
            var remarks = '';
            if (total === 0) {
                remarks = '특이사항 없음';
            } else {
                var tableGroups = groupedDetails[ct] || {};
                var sectionStats = {};
                Object.keys(tableGroups).forEach(function(tn) {
                    tableGroups[tn].forEach(function(d) {
                        var sName = TSE_TABLE_CATEGORY[tn]
                            ? reportRetailerName(tn, d.retailer, tn)
                            : (TABLE_SECTION[tn] || tn);
                        if (!sectionStats[sName]) sectionStats[sName] = { corrected: 0, normal: 0 };
                        if (d.status === 'corrected') sectionStats[sName].corrected++;
                        else if (d.status === 'normal') sectionStats[sName].normal++;
                    });
                });
                var parts = [];
                Object.keys(sectionStats).forEach(function(sName) {
                    var s = sectionStats[sName];
                    var sub = [];
                    if (s.corrected > 0) sub.push('수정 ' + s.corrected + '건');
                    if (s.normal > 0) sub.push('확인 ' + s.normal + '건');
                    parts.push(sName + ' ' + sub.join(', '));
                });
                remarks = parts.join(' / ');
            }
            summaryData.push({ category: L4.TYPE_NAMES[ct], count: total + '건', remarks: remarks });
        });

        // 비제품 제외
        var excludedItems = data.excluded_items || [];
        var exCount = excludedItems.length;
        var exRemarks = '특이사항 없음';
        if (exCount > 0) {
            var exByRetailer = {};
            excludedItems.forEach(function(d) {
                var name = d.category + ' ' + d.account_name;
                exByRetailer[name] = (exByRetailer[name] || 0) + 1;
            });
            exRemarks = sortRetailerKeys(Object.keys(exByRetailer)).map(function(name) {
                return name + ' ' + exByRetailer[name] + '건 비제품으로 변경';
            }).join('\n');
        }
        summaryData.push({ category: '비제품 제외', count: exCount + '건', remarks: exRemarks });

        createReportTable(summarySection, [
            { key: 'category', label: '구분', width: 150 },
            { key: 'count', label: '이슈건수', width: 80, align: 'center' },
            { key: 'remarks', label: '비고' }
        ], summaryData, function(item) {
            return '<tr>'
                + '<td>' + L4.escapeHtml(item.category) + '</td>'
                + '<td style="text-align:center">' + L4.escapeHtml(item.count) + '</td>'
                + '<td style="white-space:pre-line">' + L4.escapeHtml(item.remarks) + '</td>'
                + '</tr>';
        });
        detailEl.appendChild(summarySection);

        // ━━━ 1. 수집현황 ━━━
        var collSection = createDiv('report-section');
        collSection.appendChild(createDiv('report-section-title', '■ 1. 수집현황'));

        if (hasCollection) {
            var sectionNames = collectionStatus.map(function(cs) {
                return L4.CHECK_SECTION_NAMES[cs.section] || cs.section;
            });
            collSection.appendChild(createDiv('report-item', '수집 항목: ' + sectionNames.join(', ')));
        } else {
            collSection.appendChild(createDiv('report-item', '- 수집현황 기록 없음'));
        }

        if (hasIssues) {
            collSection.appendChild(createDiv('rpt-sub-title', '▸ 수집 이슈'));
            collectionIssues.forEach(function(issue, idx) {
                var sectionName = L4.CHECK_SECTION_NAMES[issue.section] || issue.section;
                var statusTag = issue.resolution_status === 'resolved' ? '[확인] ' : '';
                collSection.appendChild(createDiv('report-item', '(' + (idx + 1) + ') ' + statusTag + '[' + sectionName + '] ' + issue.title));
                var fields = [
                    { label: '일시', value: issue.issue_date },
                    { label: '현상', value: issue.symptom },
                    { label: '원인', value: issue.cause },
                    { label: '조치', value: issue.action }
                ];
                if (issue.resolution_status === 'resolved' && issue.resolution_memo) {
                    fields.push({ label: '처리사유', value: issue.resolution_memo });
                }
                fields.forEach(function(f) {
                    if (f.value) {
                        var item = createDiv('report-item', f.label + ': ' + f.value);
                        item.style.paddingLeft = '32px';
                        collSection.appendChild(item);
                    }
                });
            });
        }

        // 수요증감율 부족 키워드
        var missingKeywords = data.missing_keywords || [];
        if (missingKeywords.length > 0) {
            collSection.appendChild(createDiv('rpt-sub-title', '▸ 수요증감율 부족 키워드'));
            var kwByEvent = {};
            missingKeywords.forEach(function(kw) {
                var key = kw.event_name;
                if (!kwByEvent[key]) kwByEvent[key] = { category: kw.category, event_date: kw.event_date, products: [] };
                kwByEvent[key].products.push(kw.product_name);
            });
            var kwData = Object.keys(kwByEvent).map(function(eventName) {
                var g = kwByEvent[eventName];
                return { event_name: eventName, category: g.category, products: g.products.join(', '), count: g.products.length };
            });
            createReportTable(collSection, [
                { key: 'category', label: '카테고리', align: 'center' },
                { key: 'count', label: '건수', align: 'center' },
                { key: 'event_name', label: '이벤트' },
                { key: 'products', label: '부족 키워드' }
            ], kwData, function(item) {
                return '<tr>'
                    + '<td style="text-align:center">' + L4.escapeHtml(item.category) + '</td>'
                    + '<td style="text-align:center">' + item.count + '</td>'
                    + '<td>' + L4.escapeHtml(item.event_name) + '</td>'
                    + '<td>' + L4.escapeHtml(item.products) + '</td>'
                    + '</tr>';
            });
        }
        detailEl.appendChild(collSection);

        // ━━━ 2~6. 검증 상세 ━━━
        var sectionNo = 2;
        ['null_check', 'duplicate_check', 'format_check', 'cross_field', 'field_missing'].forEach(function(ct) {
            var tableGroups = groupedDetails[ct];
            var hasData = tableGroups && Object.keys(tableGroups).length > 0;
            if (hasData) {
                if (ct === 'duplicate_check') {
                    renderDuplicateSection(detailEl, sectionNo, L4.TYPE_NAMES[ct], tableGroups, typeSummary[ct]);
                } else if (ct === 'cross_field') {
                    renderCrossfieldSection(detailEl, sectionNo, L4.TYPE_NAMES[ct], tableGroups, typeSummary[ct]);
                } else {
                    renderRetailerGroupedSection(detailEl, sectionNo, L4.TYPE_NAMES[ct], tableGroups, typeSummary[ct], 'item', 'Item');
                }
            } else {
                var emptySection = createDiv('report-section');
                var c = typeSummary[ct] || {};
                var total = (c.corrected || 0) + (c.normal || 0);
                emptySection.appendChild(createDiv('report-section-title',
                    '■ ' + sectionNo + '. ' + L4.TYPE_NAMES[ct] + ' (' + total + '건)'));
                emptySection.appendChild(createDiv('report-item', '- 특이사항 없음'));
                detailEl.appendChild(emptySection);
            }
            sectionNo++;
        });

        // ━━━ 비제품 제외 ━━━
        var excludedItems2 = data.excluded_items || [];
        if (excludedItems2.length > 0) {
            var exSection = createDiv('report-section');
            exSection.appendChild(createDiv('report-section-title',
                '■ ' + sectionNo + '. 비제품 제외 (' + excludedItems2.length + '건)'));

            var exRetailerData = {};
            excludedItems2.forEach(function(d) {
                var retailerName = d.category + ' ' + d.account_name;
                if (!exRetailerData[retailerName]) exRetailerData[retailerName] = { items: [] };
                if (d.item) exRetailerData[retailerName].items.push(d.item);
            });

            var exRows = sortRetailerKeys(Object.keys(exRetailerData)).map(function(name) {
                var rd = exRetailerData[name];
                var uniqueItems = rd.items.filter(function(v, i, a) { return a.indexOf(v) === i; });
                return { retailer: name, count: uniqueItems.length, item: uniqueItems.join(', '), action: 'is_product = false로 변경' };
            });

            createReportTable(exSection, [
                { key: 'retailer', label: '리테일러', width: 140 },
                { key: 'count', label: '건수', width: 60, align: 'center' },
                { key: 'item', label: 'Item' },
                { key: 'action', label: '조치 및 확인사항' }
            ], exRows, function(d) {
                return '<tr>'
                    + '<td>' + L4.escapeHtml(d.retailer) + '</td>'
                    + '<td style="text-align:center">' + d.count + '</td>'
                    + '<td>' + L4.escapeHtml(d.item) + '</td>'
                    + '<td>' + L4.escapeHtml(d.action) + '</td>'
                    + '</tr>';
            });

            detailEl.appendChild(exSection);
            sectionNo++;
        }
    }

    // 핸들러 등록
    L4._sectionHandler['report'] = loadReport;

})();
