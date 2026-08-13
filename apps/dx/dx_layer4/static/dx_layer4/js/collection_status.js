/**
 * Layer 4 수집 현황
 */

(function() {
    'use strict';

    var activeFocus = new URLSearchParams(window.location.search).get('focus') || '일일 수집 현황';

    // ── 일일 수집 현황 ────────────────────────────────

    var CATEGORY_MAP = {
        'retail': 'Retail',
        'sentiment': 'Retail',
        'youtube': 'Consumer',
        'tse_retail': 'TSE',
        'market_trend': 'Market',
        'market_demand': 'Market',
        'market_competitor': 'Market',
        'market_competitor_event': 'Market',
        'market_promotion': 'Market'
    };

    var NAME_MAP = {
        'retail': '거래선 제품 정보 / 감성점수',
        'sentiment': '감성분석',
        'youtube': 'YouTube 영상 데이터 (HHP)',
        'tse_retail': 'TSE Retail 수집 데이터',
        'market_trend': '키워드 검색 트렌드 (TV/HHP)',
        'market_demand': '수요 증감율 예측 (TV/HHP)',
        'market_competitor_event': '경쟁 신제품 출시 정보 (TV/HHP)',
        'market_promotion': '거래선 프로모션 정보'
    };

    var TABLE_NAME_MAP = {
        'retail_tv': 'RAW_EXT_TV_RETAIL_COM_VIEW',
        'youtube': 'RAW_EXT_YOUTUBE_VIDEOS_VIEW',
        'youtube_runs': 'youtube_country_collection_runs',
        'youtube_videos': 'RAW_EXT_YOUTUBE_VIDEOS_VIEW',
        'youtube_comments': 'youtube_comments',
        'tse_tv': 'dx_tse.dx_tse_tv_retail_com',
        'tse_ref': 'dx_tse.dx_tse_ref_retail_com',
        'tse_ldy': 'dx_tse.dx_tse_ldy_retail_com',
        'market_trend': 'RAW_EXT_MARKET_TREND_VIEW',
        'market_demand': 'RAW_EXT_OPENAI_FORECAST_RESULTS_VIEW',
        'market_competitor_event': 'RAW_EXT_MARKET_COMP_EVENT_VIEW',
        'market_promotion': 'RAW_EXT_OPENAI_RETAILER_PROMOTIONS_VIEW'
    };

    // Email daily-status display names are standardized by product line.
    // Physical source table names remain unchanged for database queries.
    var EMAIL_TABLE_NAME_MAP = {
        'TV': 'RAW_EXT_TV_RETAIL_COM_VIEW',
        'REF': 'RAW_EXT_REF_RETAIL_COM_VIEW',
        'LDY': 'RAW_EXT_LDY_RETAIL_COM_VIEW'
    };

    var EMAIL_PRODUCT_ORDER = { 'TV': 0, 'REF': 1, 'LDY': 2 };
    var EMAIL_COUNTRY_ORDER = {
        'SEA': 0,
        'SEG': 1,
        'SIEL': 2,
        'SEDA': 3,
        'TSE': 4
    };

    // 수집이 중단된 항목은 Layer 1 응답에 남아 있어도 일일 현황·이메일에서 제외한다.
    var DISABLED_CHECK_TYPES = {
        'market_trend': true,
        'market_demand': true,
        'market_promotion': true,
        'market_competitor': true,
        'market_competitor_event': true
    };

    function loadDailyStatus() {
        var date = getSelectedDate();
        if (!date) return;

        var container = document.getElementById('cs-daily-container');
        container.innerHTML = '<div class="l4-empty-state"><p>조회 중...</p></div>';

        fetch('/dx/layer1/api/stats/?date=' + encodeURIComponent(date))
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data || data.error) throw new Error('Layer1 stats unavailable');
                renderDailyStatus(data, date);
            })
            .catch(function(e) {
                console.error(e);
                container.innerHTML = '<div class="l4-empty-state"><p>오류가 발생했습니다.</p></div>';
            });
    }

    function renderDailyStatus(data, date) {
        var container = document.getElementById('cs-daily-container');
        var checks = data.checks || [];

        if (checks.length === 0) {
            container.innerHTML = '<div class="l4-empty-state"><p>수집 데이터가 없습니다.</p></div>';
            return;
        }

        var rows = buildDailyRows(data);

        var totalExpected = 0;
        var totalActual = 0;
        rows.forEach(function(r) {
            if (typeof r.expected === 'number') totalExpected += r.expected;
            totalActual += r.actual;
        });

        var html = '<div class="ds-date-label">기준일: ' + L4.escapeHtml(date) + '</div>';
        html += '<div class="ds-table-wrap"><table class="ds-table">';
        html += '<thead><tr>';
        html += '<th style="width:50px;">No</th>';
        html += '<th style="width:100px;">카테고리</th>';
        html += '<th>수집 항목</th>';
        html += '<th>테이블명</th>';
        html += '<th style="width:100px;">예상건수</th>';
        html += '<th style="width:100px;">일일수집건수</th>';
        html += '</tr></thead>';
        html += '<tbody>';

        rows.forEach(function(r) {
            html += '<tr>';
            html += '<td class="num">' + r.no + '</td>';
            html += '<td style="text-align:center;">' + L4.escapeHtml(r.category) + '</td>';
            html += '<td>' + L4.escapeHtml(r.name) + '</td>';
            html += '<td>' + L4.escapeHtml(r.table_name) + '</td>';
            html += '<td class="num">' + (typeof r.expected === 'number' ? L4.formatNumber(r.expected) : r.expected) + '</td>';
            html += '<td class="num">' + L4.formatNumber(r.actual) + '</td>';
            html += '</tr>';
        });

        html += '<tr class="ds-total-row">';
        html += '<td colspan="4" style="text-align:center;">합 계</td>';
        html += '<td class="num">' + L4.formatNumber(totalExpected) + '</td>';
        html += '<td class="num">' + L4.formatNumber(totalActual) + '</td>';
        html += '</tr>';
        html += '</tbody></table></div>';

        container.innerHTML = html;
    }

    // ── 항목별 NULL 현황 ────────────────────────────────

    var VALID_NULL_CATEGORIES = {
        'tv': true,
        'tse_tv': true,
        'tse_ref': true,
        'tse_ldy': true
    };
    var requestedCategory = new URLSearchParams(window.location.search).get('category');
    var currentCategory = VALID_NULL_CATEGORIES[requestedCategory] ? requestedCategory : 'tv';

    function loadNullStatus() {
        var date = getSelectedDate();
        if (!date) return;

        var container = document.getElementById('cs-container');
        container.innerHTML = '<div class="l4-empty-state"><p>조회 중...</p></div>';

        var url = '/dx/layer4/api/collection-status/'
            + '?date=' + encodeURIComponent(date)
            + '&category=' + encodeURIComponent(currentCategory);

        fetch(url)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.success) {
                    container.innerHTML = '<div class="l4-empty-state"><p>' + L4.escapeHtml(data.error || '조회 실패') + '</p></div>';
                    return;
                }
                renderNullStatus(data.retailers);
            })
            .catch(function(e) {
                console.error(e);
                container.innerHTML = '<div class="l4-empty-state"><p>오류가 발생했습니다.</p></div>';
            });
    }

    function renderNullStatus(retailers) {
        var container = document.getElementById('cs-container');

        if (!retailers || retailers.length === 0) {
            container.innerHTML = '<div class="l4-empty-state"><p>수집 데이터가 없습니다.</p></div>';
            return;
        }

        var html = buildNullTable(retailers, '', true);

        container.innerHTML = html;
    }

    // 카테고리 토글
    document.addEventListener('DOMContentLoaded', function() {
        document.querySelectorAll('.cs-cat-btn').forEach(function(btn) {
            btn.classList.toggle('active', btn.dataset.cat === currentCategory);
            btn.addEventListener('click', function() {
                document.querySelectorAll('.cs-cat-btn').forEach(function(b) { b.classList.remove('active'); });
                btn.classList.add('active');
                currentCategory = btn.dataset.cat;
                loadNullStatus();
            });
        });
    });

    // ── 이메일 보고 ────────────────────────────────

    var emailSentCount = 0;
    var emailReportComplete = false;
    var emailRequestSequence = 0;
    var emailRenderedDate = '';

    function updateSendButton(count, info) {
        var sendBtn = document.getElementById('email-send-btn');
        if (!sendBtn) return;
        emailSentCount = count;
        if (count > 0) {
            sendBtn.textContent = '재발송';
            sendBtn.title = (info.sent_id || '') + ' / ' + (info.sent_at || '') + ' 발송됨 (' + count + '회)';
        } else {
            sendBtn.textContent = '발송';
            sendBtn.title = '';
        }
        sendBtn.disabled = !emailReportComplete;
    }

    function disableEmailSend() {
        emailReportComplete = false;
        emailRenderedDate = '';
        var sendBtn = document.getElementById('email-send-btn');
        if (sendBtn) sendBtn.disabled = true;
    }

    function renderIncompleteEmailWarning(errors) {
        var container = document.getElementById('cs-email-container');
        var html = '<div class="l4-empty-state"><p>이메일 보고 데이터가 불완전하여 발송할 수 없습니다.</p>';
        var messages = (errors || []).map(function(error) {
            if (typeof error === 'string') return error;
            if (!error) return '';
            return error.message || error.error || error.label || '';
        }).filter(function(message) { return Boolean(message); });
        if (messages.length > 0) {
            html += '<p style="font-size:12px;color:#888;">' + L4.escapeHtml(messages.join(' / ')) + '</p>';
        }
        html += '</div>';
        container.innerHTML = html;
    }

    function loadEmailReport() {
        var date = getSelectedDate();
        if (!date) return;
        var requestSequence = ++emailRequestSequence;
        var requestedDate = date;

        var container = document.getElementById('cs-email-container');
        container.innerHTML = '<div class="l4-empty-state"><p>조회 중...</p></div>';
        disableEmailSend();

        // Layer 1 YouTube + 이메일 전용 통합 데이터 + 발송 여부 동시 조회
        Promise.all([
            fetchJsonRequired('/dx/layer1/api/stats/?date=' + encodeURIComponent(date)),
            fetchJsonRequired('/dx/layer4/api/collection-status/email-report-data/?date=' + encodeURIComponent(date)),
            fetchJsonOrFallback('/dx/layer4/api/collection-status/email-check/?date=' + encodeURIComponent(date), { count: 0 })
        ]).then(function(results) {
            if (requestSequence !== emailRequestSequence || getSelectedDate() !== requestedDate) return;
            var emailData = results[1] || {};
            emailReportComplete = emailData.success === true && emailData.complete === true;
            renderEmailReport(results[0], emailData, requestedDate);
            updateSendButton(results[2].count || 0, results[2]);
        }).catch(function(e) {
            if (requestSequence !== emailRequestSequence || getSelectedDate() !== requestedDate) return;
            console.error(e);
            disableEmailSend();
            renderIncompleteEmailWarning([e && e.message]);
        });
    }

    function fetchJsonRequired(url) {
        return fetch(url)
            .then(function(r) {
                if (!r.ok) throw new Error('Required report data unavailable');
                return r.json();
            })
            .then(function(data) {
                if (!data || data.error) {
                    throw new Error('Required report data unavailable');
                }
                return data;
            });
    }

    function fetchJsonOrFallback(url, fallback) {
        return fetch(url)
            .then(function(r) {
                return r.json().catch(function() {
                    return fallback;
                });
            })
            .then(function(data) {
                if (!data || data.error) {
                    console.warn('이메일 보고 데이터 조회 실패:', url, data && data.error);
                    return fallback;
                }
                return data;
            })
            .catch(function(e) {
                console.warn('이메일 보고 데이터 조회 실패:', url, e);
                return fallback;
            });
    }

    function buildDailyRows(data, options) {
        options = options || {};
        var checks = data.checks || [];
        var rows = [];
        var no = 1;
        checks.forEach(function(check) {
            var checkType = check.check_type;
            if (DISABLED_CHECK_TYPES[checkType]) return;
            if (options.emailOnlyYoutube && checkType !== 'youtube') return;

            if (checkType === 'retail' && check.categories) {
                check.categories.forEach(function(cat) {
                    if (cat.name === 'HHP') return;
                    var key = 'retail_tv';
                    rows.push({ no: no++, category: 'Retail', name: '거래선 ' + cat.name + ' 제품 정보 / 감성점수', table_name: TABLE_NAME_MAP[key] || '', expected: cat.expected || 900, actual: cat.total || 0 });
                });
            } else if (checkType === 'sentiment' || checkType === 'market_competitor') {
                return;
            } else if (check.is_target_date === false) {
                return;
            } else if (checkType === 'tse_retail') {
                if (options.excludeTseRetail) return;
                (check.categories || []).forEach(function(cat) {
                    var productLine = String(cat.product_line || ('tse_' + String(cat.name || '').toLowerCase())).toLowerCase();
                    var retailerRows = cat.retailers || [];
                    var expected = typeof cat.expected === 'number' ? cat.expected : 0;
                    var actual = typeof cat.total === 'number' ? cat.total : (typeof cat.actual === 'number' ? cat.actual : 0);
                    if (retailerRows.length > 0) {
                        expected = 0;
                        actual = 0;
                        retailerRows.forEach(function(retailer) {
                            expected += Number(retailer.expected || 0);
                            actual += Number(retailer.actual !== undefined ? retailer.actual : (retailer.total || 0));
                        });
                    }
                    rows.push({
                        no: no++,
                        category: 'TSE',
                        name: 'TSE ' + String(cat.name || '').toUpperCase() + ' 수집 데이터',
                        table_name: cat.table_name || TABLE_NAME_MAP[productLine] || '',
                        expected: expected || 300,
                        actual: actual
                    });
                });
            } else if (checkType === 'youtube') {
                var youtubeTotals = {
                    expectedCountries: 0,
                    completedCountries: 0,
                    expectedKeywords: 0,
                    completedKeywords: 0,
                    videos: 0,
                    comments: 0
                };
                (check.categories || []).forEach(function(cat) {
                    if (cat.name === 'TV') return;
                    youtubeTotals.expectedCountries += (cat.expected_country_count || 0);
                    youtubeTotals.completedCountries += (cat.completed_country_count || 0);
                    youtubeTotals.expectedKeywords += (cat.expected || 0);
                    youtubeTotals.completedKeywords += (cat.log_count || 0);
                    youtubeTotals.videos += (cat.video_count || 0);
                    youtubeTotals.comments += (cat.comment_count || 0);
                });

                if (options.emailYoutubeVideoOnly) {
                    rows.push({ no: no++, category: 'Consumer', name: 'YouTube 영상 데이터 (HHP)', table_name: TABLE_NAME_MAP.youtube_videos, expected: '-', actual: youtubeTotals.videos });
                } else {
                    rows.push({ no: no++, category: CATEGORY_MAP[checkType] || '', name: NAME_MAP[checkType] || check.name, table_name: TABLE_NAME_MAP[checkType] || '', expected: '-', actual: youtubeTotals.videos });
                }
            } else {
                rows.push({ no: no++, category: CATEGORY_MAP[checkType] || '', name: NAME_MAP[checkType] || check.name, table_name: TABLE_NAME_MAP[checkType] || '', expected: check.expected || '-', actual: check.actual || 0 });
            }
        });
        return rows;
    }

    function buildEmailDailyRows(dailyData, emailData) {
        var rows = [];
        var sources = (emailData.sources || []).map(function(source, index) {
            return { source: source, index: index };
        }).sort(function(left, right) {
            var leftProduct = String(left.source.product || '').toUpperCase();
            var rightProduct = String(right.source.product || '').toUpperCase();
            var leftProductOrder = EMAIL_PRODUCT_ORDER[leftProduct];
            var rightProductOrder = EMAIL_PRODUCT_ORDER[rightProduct];
            if (leftProductOrder === undefined) leftProductOrder = 99;
            if (rightProductOrder === undefined) rightProductOrder = 99;
            if (leftProductOrder !== rightProductOrder) {
                return leftProductOrder - rightProductOrder;
            }

            var leftCountry = String(left.source.country || '').toUpperCase();
            var rightCountry = String(right.source.country || '').toUpperCase();
            var leftCountryOrder = EMAIL_COUNTRY_ORDER[leftCountry];
            var rightCountryOrder = EMAIL_COUNTRY_ORDER[rightCountry];
            if (leftCountryOrder === undefined) leftCountryOrder = 99;
            if (rightCountryOrder === undefined) rightCountryOrder = 99;
            if (leftCountryOrder !== rightCountryOrder) {
                return leftCountryOrder - rightCountryOrder;
            }
            return left.index - right.index;
        });

        sources.forEach(function(entry) {
            var source = entry.source;
            var productLine = String(source.product || '').toUpperCase();
            rows.push({
                category: source.country || '',
                name: productLine ? productLine + ' 수집 데이터' : (source.label || '수집 데이터'),
                table_name: EMAIL_TABLE_NAME_MAP[productLine] || source.table_name || '',
                table_group: 'product:' + (productLine || source.key || entry.index),
                actual: typeof source.total_count === 'number' ? source.total_count : 0
            });
        });

        buildDailyRows(dailyData, {
            emailOnlyYoutube: true,
            emailYoutubeVideoOnly: true
        }).forEach(function(row) {
            row.table_group = 'youtube:' + row.table_name;
            rows.push(row);
        });

        var index = 0;
        while (index < rows.length) {
            var groupEnd = index + 1;
            while (groupEnd < rows.length
                    && rows[groupEnd].table_group === rows[index].table_group) {
                groupEnd += 1;
            }
            rows[index].table_rowspan = groupEnd - index;
            for (var groupedIndex = index + 1;
                    groupedIndex < groupEnd; groupedIndex += 1) {
                rows[groupedIndex].table_rowspan = 0;
            }
            index = groupEnd;
        }

        rows.forEach(function(row, rowIndex) {
            row.no = rowIndex + 1;
        });

        return rows;
    }

    function prepareEmailMissingSource(source) {
        function isVisibleColumn(columnName) {
            return String(columnName || '').trim().toLowerCase() !== 'bsr_rank';
        }

        var columnOrder = (source.column_order || []).filter(isVisibleColumn);
        var isSeaTv = String(source.key || '').toLowerCase() === 'sea_tv'
            || (String(source.country || '').toUpperCase() === 'SEA'
                && String(source.product || '').toUpperCase() === 'TV');
        var retailers = (source.retailers || []).map(function(retailer) {
            var copy = Object.assign({}, retailer);
            copy.columns = (retailer.columns || []).filter(function(column) {
                return isVisibleColumn(column.column);
            });
            if (isSeaTv && retailer.retailer === 'Amazon'
                    && !copy.columns.some(function(column) { return column.column === 'redirect'; })) {
                copy.columns.push({
                    column: 'redirect',
                    total_count: retailer.redirect_true_count || 0,
                    null_count: 0,
                    remark: 'Amazon redirect=TRUE 건수'
                });
            }
            return copy;
        });
        if (isSeaTv && retailers.some(function(retailer) { return retailer.retailer === 'Amazon'; })
                && columnOrder.indexOf('redirect') === -1) {
            columnOrder.push('redirect');
        }

        columnOrder = columnOrder.map(function(columnName, index) {
            var missingTotal = 0;
            retailers.forEach(function(retailer) {
                var info = (retailer.columns || []).find(function(column) {
                    return column.column === columnName;
                });
                if (!info) return;
                var nullCount = Number(info.null_count);
                if (!isNaN(nullCount)) missingTotal += nullCount;
            });
            return {
                columnName: columnName,
                index: index,
                missingTotal: missingTotal
            };
        }).sort(function(left, right) {
            return left.missingTotal - right.missingTotal
                || left.index - right.index;
        }).map(function(item) {
            return item.columnName;
        });

        return { retailers: retailers, columnOrder: columnOrder };
    }

    var TH = 'padding:6px 10px;background:#f5f5f5;border:1px solid #ccc;font-weight:700;text-align:center;font-size:12px;font-family:Malgun Gothic,sans-serif;';
    var TD = 'padding:5px 10px;border:1px solid #ccc;font-size:12px;font-family:Malgun Gothic,sans-serif;';
    var TD_NUM = 'padding:5px 10px;border:1px solid #ccc;font-size:12px;font-family:Malgun Gothic,sans-serif;text-align:center;';
    var TABLE = 'border-collapse:collapse;width:100%;margin-bottom:8px;';
    var TITLE = 'font-size:14px;font-weight:700;margin:24px 0 10px;font-family:Malgun Gothic,sans-serif;';

    function buildNullTable(retailers, label, withLinks, columnOrder) {
        if (!retailers || retailers.length === 0) return '';

        var colSet = {};
        retailers.forEach(function(r) {
            (r.columns || []).forEach(function(c) { colSet[c.column] = true; });
        });
        var allColumns = Array.isArray(columnOrder) && columnOrder.length > 0
            ? columnOrder.slice()
            : Object.keys(colSet).sort();

        var retailerMaps = {};
        retailers.forEach(function(r) {
            var map = {};
            (r.columns || []).forEach(function(c) { map[c.column] = c; });
            retailerMaps[r.retailer] = map;
        });

        // 비고 매핑 수집
        var remarkMap = {};
        retailers.forEach(function(r) {
            (r.columns || []).forEach(function(c) {
                if (c.remark) remarkMap[c.column] = c.remark;
            });
        });
        var hasRemarks = Object.keys(remarkMap).length > 0;

        var html = '';
        if (label) html += '<div style="font-size:13px;font-weight:700;margin:16px 0 8px;font-family:Malgun Gothic,sans-serif;">' + label + '</div>';
        html += '<table style="' + TABLE + '"><tr><th style="' + TH + 'width:250px;" rowspan="2">수집항목</th>';
        retailers.forEach(function(r) { html += '<th style="' + TH + '" colspan="2">' + L4.escapeHtml(r.retailer) + '</th>'; });
        if (hasRemarks) html += '<th style="' + TH + '" rowspan="2">비고</th>';
        html += '</tr><tr>';
        retailers.forEach(function() {
            html += '<th style="' + TH + 'width:60px;">전체</th>';
            html += '<th style="' + TH + 'width:60px;">Missing</th>';
        });
        html += '</tr>';
        allColumns.forEach(function(colName) {
            html += '<tr><td style="' + TD + 'white-space:nowrap;">' + colName + '</td>';
            retailers.forEach(function(r) {
                var info = retailerMaps[r.retailer][colName];
                if (!info) {
                    html += '<td style="' + TD + 'text-align:center;">-</td>';
                    html += '<td style="' + TD + 'text-align:center;">-</td>';
                } else {
                    var colTotal = info.total_count !== undefined ? info.total_count : r.total_count;
                    html += '<td style="' + TD_NUM + '">' + L4.formatNumber(colTotal) + '</td>';
                    if (withLinks && info.null_count > 0) {
                        var detailUrl = '/dx/layer4/collection-status/detail/'
                            + '?date=' + encodeURIComponent(getSelectedDate())
                            + '&category=' + encodeURIComponent(currentCategory)
                            + '&retailer=' + encodeURIComponent(r.retailer)
                            + '&column=' + encodeURIComponent(colName);
                        html += '<td style="' + TD_NUM + '"><a href="' + detailUrl + '" style="color:inherit;text-decoration:none;cursor:pointer;">'
                            + L4.formatNumber(info.null_count) + '</a></td>';
                    } else {
                        html += '<td style="' + TD_NUM + '">' + L4.formatNumber(info.null_count) + '</td>';
                    }
                }
            });
            if (hasRemarks) {
                html += '<td style="' + TD + 'font-size:12px;color:var(--text-secondary);">' + (remarkMap[colName] || '') + '</td>';
            }
            html += '</tr>';
        });
        html += '</table>';
        return html;
    }

    function buildEmailNullTable(retailers, label, columnOrder) {
        if (!retailers || retailers.length === 0) return '';
        var retailerMaps = {};
        var remarkMap = {};
        retailers.forEach(function(retailer) {
            var map = {};
            (retailer.columns || []).forEach(function(column) {
                map[column.column] = column;
                if (column.remark) remarkMap[column.column] = column.remark;
            });
            retailerMaps[retailer.retailer] = map;
        });
        var html = '<div class="et">' + label + '</div>';
        html += '<table class="e" border="1" cellpadding="6" cellspacing="0"><tr><th class="ec" width="250" rowspan="2">수집항목</th>';
        retailers.forEach(function(retailer) {
            html += '<th colspan="2">' + L4.escapeHtml(retailer.retailer) + '</th>';
        });
        html += '<th rowspan="2">비고</th>';
        html += '</tr><tr>';
        retailers.forEach(function() { html += '<th>전체</th><th>Missing</th>'; });
        html += '</tr>';
        (columnOrder || []).forEach(function(columnName) {
            html += '<tr><td class="ec" width="250">' + L4.escapeHtml(columnName) + '</td>';
            retailers.forEach(function(retailer) {
                var info = retailerMaps[retailer.retailer][columnName];
                if (!info) {
                    html += '<td align="center">-</td><td align="center">-</td>';
                } else {
                    var total = info.total_count !== undefined ? info.total_count : retailer.total_count;
                    html += '<td align="center">' + L4.formatNumber(total) + '</td>';
                    html += '<td align="center">' + L4.formatNumber(info.null_count) + '</td>';
                }
            });
            html += '<td class="er">' + L4.escapeHtml(remarkMap[columnName] || '') + '</td>';
            html += '</tr>';
        });
        return html + '</table>';
    }

    function renderEmailReport(dailyData, emailData, date) {
        var container = document.getElementById('cs-email-container');
        var dailyRows = buildEmailDailyRows(dailyData, emailData);
        var totalActual = 0;
        dailyRows.forEach(function(r) {
            totalActual += r.actual;
        });

        var dateDisplay = date.replace(/-/g, '.');

        var FONT = 'font-size:13px;font-family:Malgun Gothic,sans-serif;';

        var html = '<div class="email-preview" id="email-preview-content">';
        html += '<style>.e{border-collapse:collapse;width:100%;margin-bottom:8px;font:12px "Malgun Gothic",sans-serif}.e th{background:#f5f5f5;font-weight:700}.e td,.e th{border:1px solid #ccc;padding:6px;text-align:center}.et{font:700 13px "Malgun Gothic",sans-serif;margin:16px 0 8px}.ec{width:250px;white-space:nowrap}.er{font-size:12px;color:#666}.en{text-align:center}.ew{font-size:12px;color:#888;line-height:1.8}.ef{font-size:12px;color:#555;line-height:1.8}</style>';
        html += '<span class="email-subject" hidden>[데이터 수집 모니터링] ' + dateDisplay + ' 수집 현황</span>';

        if (!emailReportComplete) {
            html += '<div style="padding:10px 12px;margin-bottom:16px;border:1px solid #f59e0b;background:#fffbeb;color:#92400e;font-weight:700;">'
                + '※ 이메일 보고 데이터가 불완전하여 발송할 수 없습니다.';
            var errorMessages = (emailData.errors || []).map(function(error) {
                if (typeof error === 'string') return error;
                if (!error) return '';
                return error.message || error.error || error.label || '';
            }).filter(function(message) { return Boolean(message); });
            if (errorMessages.length > 0) {
                html += '<br><span style="font-size:12px;font-weight:400;">' + L4.escapeHtml(errorMessages.join(' / ')) + '</span>';
            }
            html += '</div>';
        }

        // 전체를 하나의 table로 래핑 (Gmail 접힘 방지)
        html += '<table width="100%" cellpadding="0" cellspacing="0"><tr><td style="border:0;font:13px Malgun Gothic,sans-serif;line-height:1.7">';

        html += dateDisplay + ' 기준 데이터 수집 모니터링 현황 공유드립니다.<br><br>';

        // 1. 일일 수집 현황
        html += '<b>1. 일일 수집 현황</b><br><br>';
        html += '<b>&nbsp;기준일: ' + dateDisplay + '</b><br><br>';
        html += '<table class="e" border="1" cellpadding="6" cellspacing="0"><tr>';
        html += '<th>No</th><th>카테고리</th><th>수집 항목</th><th>테이블명</th><th>일일수집건수</th>';
        html += '</tr>';
        dailyRows.forEach(function(r) {
            html += '<tr>';
            html += '<td align="center">' + r.no + '</td>';
            html += '<td align="center">' + L4.escapeHtml(r.category) + '</td>';
            if (r.table_rowspan > 0) {
                html += '<td rowspan="' + r.table_rowspan + '" align="center" valign="middle">'
                    + L4.escapeHtml(r.name) + '</td>';
                html += '<td rowspan="' + r.table_rowspan + '" align="center" valign="middle">'
                    + L4.escapeHtml(r.table_name) + '</td>';
            }
            html += '<td align="center">' + L4.formatNumber(r.actual) + '</td>';
            html += '</tr>';
        });
        html += '<tr><th colspan="4">합 계</th>';
        html += '<th>' + L4.formatNumber(totalActual) + '</th></tr>';
        html += '</table>';

        html += '<br><br>';

        // 2. R.com 수집 항목 Missing Value 현황
        html += '<b>2. R.com 수집 항목 Missing Value 현황</b><br>';
        (emailData.sources || []).forEach(function(source) {
            var missingSource = prepareEmailMissingSource(source);
            var label = [source.country, String(source.product || '').toUpperCase()].filter(function(value) {
                return Boolean(value);
            }).join(' - ');
            html += buildEmailNullTable(
                missingSource.retailers,
                L4.escapeHtml(label),
                missingSource.columnOrder
            );
        });

        html += '<br>감사합니다.';

        // 래퍼 table 닫기
        html += '</td></tr></table>';
        html += '</div>';
        container.innerHTML = html;
        emailRenderedDate = date;
    }

    // 이메일 HTML 복사 + 발송
    document.addEventListener('DOMContentLoaded', function() {
        var copyBtn = document.getElementById('email-copy-btn');
        if (copyBtn) {
            copyBtn.addEventListener('click', function() {
                var preview = document.getElementById('email-preview-content');
                if (!preview) return;

                var range = document.createRange();
                range.selectNodeContents(preview);
                var sel = window.getSelection();
                sel.removeAllRanges();
                sel.addRange(range);
                document.execCommand('copy');
                sel.removeAllRanges();

                showToast('이메일 내용이 복사되었습니다.', 'success');
            });
        }

        var sendBtn = document.getElementById('email-send-btn');
        if (sendBtn) {
            sendBtn.addEventListener('click', function() {
                if (!emailReportComplete) {
                    showToast('이메일 보고 데이터가 불완전하여 발송할 수 없습니다.', 'warning');
                    return;
                }
                var selectedDate = getSelectedDate();
                if (!emailRenderedDate || selectedDate !== emailRenderedDate) {
                    disableEmailSend();
                    showToast('조회 날짜가 변경되었습니다. 다시 조회해주세요.', 'warning');
                    return;
                }
                var renderedDate = emailRenderedDate;
                var today = new Date();
                var todayStr = today.getFullYear() + '-' + String(today.getMonth() + 1).padStart(2, '0') + '-' + String(today.getDate()).padStart(2, '0');
                if (selectedDate === todayStr) {
                    showToast('당일 데이터는 이메일 발송할 수 없습니다.', 'warning');
                    return;
                }

                sendBtn.disabled = true;
                fetch('/dx/layer4/api/collection-status/email-recipients/')
                    .then(function(r) { return r.json(); })
                    .then(function(res) {
                        sendBtn.disabled = false;
                        var list = (res.recipients || []);
                        var recipientText = list.length > 0
                            ? '\n\n수신자:\n' + list.map(function(r) { return r.name + ' : ' + r.email; }).join('\n')
                            : '\n\n(등록된 수신자가 없습니다)';
                        var dateDisplay = selectedDate.replace(/-/g, '.');
                        var confirmMsg = emailSentCount > 0
                            ? dateDisplay + ' 데이터를 이미 ' + emailSentCount + '회 발송했습니다.\n재발송하시겠습니까?' + recipientText
                            : dateDisplay + ' 데이터를 발송하시겠습니까?' + recipientText;
                        var confirmOk = emailSentCount > 0 ? '재발송' : '발송';
                        return showConfirm(confirmMsg, emailSentCount > 0 ? 'warning' : 'info', { okText: confirmOk, cancelText: '취소' });
                    })
                    .catch(function() {
                        sendBtn.disabled = false;
                        showToast('수신자 목록을 불러올 수 없습니다.', 'error');
                        return Promise.reject();
                    })
                    .then(function(ok) {
                if (!ok) return;

                if (!emailReportComplete || emailRenderedDate !== renderedDate
                        || getSelectedDate() !== renderedDate) {
                    disableEmailSend();
                    showToast('조회 날짜가 변경되었습니다. 다시 조회해주세요.', 'warning');
                    return;
                }

                var preview = document.getElementById('email-preview-content');
                if (!preview) { showToast('먼저 조회해주세요.', 'error'); return; }

                var subjectEl = preview.querySelector('.email-subject');
                var subject = subjectEl ? subjectEl.textContent : '';
                var htmlContent = preview.innerHTML;

                if (!subject || !htmlContent) { showToast('이메일 내용이 없습니다.', 'error'); return; }

                var previousText = sendBtn.textContent;
                sendBtn.disabled = true;
                sendBtn.textContent = '발송 중...';

                fetch('/dx/layer4/api/collection-status/send-email/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]')
                            ? document.querySelector('[name=csrfmiddlewaretoken]').value
                            : document.cookie.match(/csrftoken=([^;]+)/)?.[1] || ''
                    },
                    body: JSON.stringify({ subject: subject, html: htmlContent, date: renderedDate })
                })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data.success) {
                        showToast(data.message, 'success');
                        updateSendButton(emailSentCount + 1, { sent_at: '방금', sent_id: '' });
                    } else {
                        showToast(data.error || '발송 실패', 'error');
                    }
                })
                .catch(function(e) {
                    console.error(e);
                    showToast('발송 중 오류가 발생했습니다.', 'error');
                })
                .finally(function() {
                    sendBtn.disabled = false;
                    if (sendBtn.textContent === '발송 중...') {
                        sendBtn.textContent = previousText || (emailSentCount > 0 ? '재발송' : '발송');
                    }
                });
                });
            });
        }
    });

    // ── 초기화 ────────────────────────────────

    var sections = ['cs-daily-section', 'cs-null-section', 'cs-email-section'];

    L4._sectionInit['collection_status'] = function() {
        var activeSection = 'cs-daily-section';
        if (activeFocus === '항목별 NULL 현황') activeSection = 'cs-null-section';
        else if (activeFocus === '이메일 보고') activeSection = 'cs-email-section';

        sections.forEach(function(id) {
            var el = document.getElementById(id);
            if (el) el.style.display = id === activeSection ? '' : 'none';
        });
    };

    L4._sectionHandler['collection_status'] = function() {
        if (activeFocus === '항목별 NULL 현황') {
            loadNullStatus();
        } else if (activeFocus === '이메일 보고') {
            loadEmailReport();
        } else {
            loadDailyStatus();
        }
    };

})();
