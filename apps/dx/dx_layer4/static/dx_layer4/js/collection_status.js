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
        'market_trend': '키워드 검색 트렌드 (TV/HHP)',
        'market_demand': '수요 증감율 예측 (TV/HHP)',
        'market_competitor_event': '경쟁 신제품 출시 정보 (TV/HHP)',
        'market_promotion': '거래선 프로모션 정보'
    };

    var TABLE_NAME_MAP = {
        'retail_tv': 'RAW_EXT_TV_RETAIL_COM_VIEW',
        'youtube': 'RAW_EXT_YOUTUBE_VIDEOS_VIEW',
        'youtube_runs': 'youtube_country_collection_runs',
        'youtube_videos': 'youtube_videos',
        'youtube_comments': 'youtube_comments',
        'market_trend': 'RAW_EXT_MARKET_TREND_VIEW',
        'market_demand': 'RAW_EXT_OPENAI_FORECAST_RESULTS_VIEW',
        'market_competitor_event': 'RAW_EXT_MARKET_COMP_EVENT_VIEW',
        'market_promotion': 'RAW_EXT_OPENAI_RETAILER_PROMOTIONS_VIEW'
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

    var currentCategory = 'tv';

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
        sendBtn.disabled = false;
    }

    function loadEmailReport() {
        var date = getSelectedDate();
        if (!date) return;

        var container = document.getElementById('cs-email-container');
        container.innerHTML = '<div class="l4-empty-state"><p>조회 중...</p></div>';

        // 일일 수집 현황 + TV Retail NULL + 발송 여부 동시 조회
        Promise.all([
            fetchJsonRequired('/dx/layer1/api/stats/?date=' + encodeURIComponent(date)),
            fetchJsonOrFallback('/dx/layer4/api/collection-status/?date=' + encodeURIComponent(date) + '&category=tv', { success: true, retailers: [] }),
            fetchJsonOrFallback('/dx/layer4/api/collection-status/email-check/?date=' + encodeURIComponent(date), { count: 0 })
        ]).then(function(results) {
            renderEmailReport(results[0], results[1], date);
            updateSendButton(results[2].count || 0, results[2]);
        }).catch(function(e) {
            console.error(e);
            container.innerHTML = '<div class="l4-empty-state"><p>오류가 발생했습니다.</p></div>';
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

                if (options.expandYoutube) {
                    rows.push({ no: no++, category: 'Consumer', name: 'YouTube 국가 실행 (HHP)', table_name: TABLE_NAME_MAP.youtube_runs, expected: youtubeTotals.expectedCountries, actual: youtubeTotals.completedCountries });
                    rows.push({ no: no++, category: 'Consumer', name: 'YouTube 완료 키워드 작업 (HHP)', table_name: TABLE_NAME_MAP.youtube_runs, expected: youtubeTotals.expectedKeywords, actual: youtubeTotals.completedKeywords });
                    rows.push({ no: no++, category: 'Consumer', name: 'YouTube 영상 데이터 (HHP)', table_name: TABLE_NAME_MAP.youtube_videos, expected: '-', actual: youtubeTotals.videos });
                    rows.push({ no: no++, category: 'Consumer', name: 'YouTube 댓글 데이터 (HHP)', table_name: TABLE_NAME_MAP.youtube_comments, expected: '-', actual: youtubeTotals.comments });
                } else {
                    rows.push({ no: no++, category: CATEGORY_MAP[checkType] || '', name: NAME_MAP[checkType] || check.name, table_name: TABLE_NAME_MAP[checkType] || '', expected: '-', actual: youtubeTotals.videos });
                }
            } else {
                rows.push({ no: no++, category: CATEGORY_MAP[checkType] || '', name: NAME_MAP[checkType] || check.name, table_name: TABLE_NAME_MAP[checkType] || '', expected: check.expected || '-', actual: check.actual || 0 });
            }
        });
        return rows;
    }

    var TH = 'padding:6px 10px;background:#f5f5f5;border:1px solid #ccc;font-weight:700;text-align:center;font-size:12px;font-family:Malgun Gothic,sans-serif;';
    var TD = 'padding:5px 10px;border:1px solid #ccc;font-size:12px;font-family:Malgun Gothic,sans-serif;';
    var TD_NUM = 'padding:5px 10px;border:1px solid #ccc;font-size:12px;font-family:Malgun Gothic,sans-serif;text-align:center;';
    var TABLE = 'border-collapse:collapse;width:100%;margin-bottom:8px;';
    var TITLE = 'font-size:14px;font-weight:700;margin:24px 0 10px;font-family:Malgun Gothic,sans-serif;';

    function buildNullTable(retailers, label, withLinks) {
        if (!retailers || retailers.length === 0) return '';

        var colSet = {};
        retailers.forEach(function(r) {
            (r.columns || []).forEach(function(c) { colSet[c.column] = true; });
        });
        var allColumns = Object.keys(colSet).sort();

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
        retailers.forEach(function(r) { html += '<th style="' + TH + '" colspan="2">' + r.retailer + '</th>'; });
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

    function renderEmailReport(dailyData, tvData, date) {
        var container = document.getElementById('cs-email-container');

        var dailyRows = buildDailyRows(dailyData, { expandYoutube: true });
        var totalExpected = 0, totalActual = 0;
        dailyRows.forEach(function(r) {
            if (typeof r.expected === 'number') totalExpected += r.expected;
            totalActual += r.actual;
        });

        var dateDisplay = date.replace(/-/g, '.');

        var FONT = 'font-size:13px;font-family:Malgun Gothic,sans-serif;';

        var html = '<div class="email-preview" id="email-preview-content">';
        html += '<span class="email-subject" style="display:none;">[데이터 수집 모니터링] ' + dateDisplay + ' 수집 현황</span>';

        // 전체를 하나의 table로 래핑 (Gmail 접힘 방지)
        html += '<table style="width:100%;border:none;border-collapse:collapse;" cellpadding="0" cellspacing="0"><tr><td style="border:none;' + FONT + 'line-height:1.7;">';

        html += dateDisplay + ' 기준 데이터 수집 모니터링 현황 공유드립니다.<br><br>';

        // 1. 일일 수집 현황
        html += '<b style="font-size:14px;">1. 일일 수집 현황</b><br><br>';
        html += '<b>&nbsp;기준일: ' + dateDisplay + '</b><br><br>';
        html += '<table style="' + TABLE + '"><tr>';
        html += '<th style="' + TH + '">No</th><th style="' + TH + '">카테고리</th><th style="' + TH + '">수집 항목</th><th style="' + TH + '">테이블명</th><th style="' + TH + '">예상건수</th><th style="' + TH + '">일일수집건수</th>';
        html += '</tr>';
        dailyRows.forEach(function(r) {
            html += '<tr>';
            html += '<td style="' + TD_NUM + '">' + r.no + '</td>';
            html += '<td style="' + TD + 'text-align:center;">' + r.category + '</td>';
            html += '<td style="' + TD + '">' + r.name + '</td>';
            html += '<td style="' + TD + '">' + r.table_name + '</td>';
            html += '<td style="' + TD_NUM + '">' + (typeof r.expected === 'number' ? L4.formatNumber(r.expected) : r.expected) + '</td>';
            html += '<td style="' + TD_NUM + '">' + L4.formatNumber(r.actual) + '</td>';
            html += '</tr>';
        });
        html += '<tr><td colspan="4" style="' + TH + 'text-align:center;">합 계</td>';
        html += '<td style="' + TH + 'text-align:right;">' + L4.formatNumber(totalExpected) + '</td>';
        html += '<td style="' + TH + 'text-align:right;">' + L4.formatNumber(totalActual) + '</td></tr>';
        html += '</table>';

        // 비고
        html += '<br><span style="font-size:12px;color:#888;line-height:1.8;">'
            + '&nbsp;&nbsp;※ YouTube 영상·댓글 데이터는 업로드 및 댓글 현황에 따라 수집 건수가 결정되어 예상 건수를 사전에 산정할 수 없습니다.<br>'
            + '&nbsp;&nbsp;※ Retail 항목은 중복 데이터 및 제외 키워드·비대상 제품을 필터링하여 수집하므로, 일일 수집건수가 예상건수보다 적을 수 있습니다.'
            + '</span><br><br>'
            + '<span style="font-size:12px;color:#555;line-height:1.8;">'
            + 'Retail 항목의 일일 수집건수가 예상건수보다 적은 이유는 아래 필터링 기준에 의한 정상 처리 결과입니다.<br><br>'
            + '1. 중복 제품: 동일 제품이 여러 페이지에 중복 노출되는 경우, item 기준으로 판별하여 중복 수집을 제외합니다.<br>'
            + '2. 제외 키워드: 제품명에 사전 정의된 제외 키워드가 포함된 경우 수집 대상에서 제외됩니다.<br>'
            + '3. 비대상 제품: 제외 키워드에 해당하지 않더라도, 수집 대상 제품이 아닌 것으로 확인된 경우 비제품으로 등록하여 이후 수집에서 제외됩니다.'
            + '</span><br><br>';

        // 2. R.com 수집 항목 Missing Value 현황
        html += '<b style="font-size:14px;">2. R.com 수집 항목 Missing Value 현황</b><br>';
        if (tvData.success) html += buildNullTable(tvData.retailers, 'TV');

        html += '<br>감사합니다.';

        // 래퍼 table 닫기
        html += '</td></tr></table>';
        html += '</div>';
        container.innerHTML = html;
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
                var selectedDate = getSelectedDate();
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
                    body: JSON.stringify({ subject: subject, html: htmlContent, date: getSelectedDate() })
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
