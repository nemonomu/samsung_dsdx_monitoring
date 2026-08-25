/**
 * Unified inspection — read-only date mapping and existing TSE result reuse.
 */

(function() {
    'use strict';

    var requestVersion = 0;
    var TSE_STATUS_LABELS = {
        PENDING: '대기',
        COLLECTING: '수집 중',
        OK: '정상',
        WARNING: '주의',
        CRITICAL: '심각'
    };

    function escapeHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function showMessage(message, isError) {
        var body = document.getElementById('ui-mapping-body');
        body.innerHTML = '<tr><td colspan="5" class="ui-message' +
            (isError ? ' error' : '') + '">' + escapeHtml(message) +
            '</td></tr>';
    }

    function statusLabel(status) {
        var key = String(status || '').toUpperCase();
        return TSE_STATUS_LABELS[key] || key || '-';
    }

    function statusClass(status) {
        var key = String(status || '').toLowerCase();
        return ['ok', 'collecting', 'warning', 'critical'].indexOf(key) >= 0
            ? ' ' + key
            : '';
    }

    function formatCount(value) {
        return value == null ? '-' : String(value);
    }

    function showTseMessage(message, isError) {
        var body = document.getElementById('ui-tse-body');
        body.innerHTML = '<tr><td colspan="6" class="ui-message' +
            (isError ? ' error' : '') + '">' + escapeHtml(message) +
            '</td></tr>';
    }

    function resetTsePanel(message) {
        document.getElementById('ui-tse-contract').textContent =
            'TSE · D · offset_days=0';
        document.getElementById('ui-tse-inspection-date').textContent = '-';
        document.getElementById('ui-tse-source-date').textContent = '-';
        document.getElementById('ui-tse-status').textContent = '-';
        showTseMessage(message || 'TSE 조회를 준비하는 중입니다.', false);
    }

    function prepareTsePanel(mapping) {
        document.getElementById('ui-tse-contract').textContent =
            mapping.country + ' · ' + mapping.rule + ' · offset_days=' +
            mapping.offset_days;
        document.getElementById('ui-tse-inspection-date').textContent =
            mapping.inspection_date;
        document.getElementById('ui-tse-source-date').textContent =
            mapping.source_date;
        document.getElementById('ui-tse-status').textContent = '조회 중';
        showTseMessage('기존 Layer1 TSE 결과를 불러오는 중입니다.', false);
    }

    function validateTseMapping(mapping) {
        var isoDate = /^\d{4}-\d{2}-\d{2}$/;
        if (
            !mapping ||
            mapping.country !== 'TSE' ||
            mapping.rule !== 'D' ||
            mapping.offset_days !== 0 ||
            !isoDate.test(String(mapping.inspection_date || '')) ||
            !isoDate.test(String(mapping.source_date || '')) ||
            mapping.inspection_date !== mapping.source_date
        ) {
            throw new Error('TSE 날짜 매핑이 D 규칙과 일치하지 않습니다.');
        }
    }

    function renderTseSnapshot(mapping, data) {
        if (String(data.target_date || '') !== mapping.source_date) {
            throw new Error('TSE 실제 조회일이 매핑된 데이터일과 일치하지 않습니다.');
        }

        var checks = data.checks || [];
        var check = checks.find(function(item) {
            return item.check_type === 'tse_retail';
        });
        if (!check) {
            throw new Error('기존 Layer1 응답에서 TSE 결과를 찾지 못했습니다.');
        }

        var categories = {};
        (check.categories || []).forEach(function(category) {
            categories[category.product_line] = category;
        });

        var rows = mapping.sources.map(function(source) {
            var category = categories[source.source_key];
            if (!category) {
                throw new Error(
                    '기존 Layer1 응답에서 ' + source.source_key +
                    ' 결과를 찾지 못했습니다.'
                );
            }
            return '<tr>' +
                '<td class="ui-country">' + escapeHtml(source.product) + '</td>' +
                '<td><span class="ui-source-key">' +
                    escapeHtml(source.source_key) + '</span></td>' +
                '<td>' + escapeHtml(mapping.inspection_date) + '</td>' +
                '<td class="ui-source-date">' +
                    escapeHtml(mapping.source_date) + '</td>' +
                '<td class="ui-count">' + escapeHtml(formatCount(category.actual)) +
                    '<span class="expected"> / ' +
                    escapeHtml(formatCount(category.expected)) + '</span></td>' +
                '<td><span class="ui-status' + statusClass(category.status) + '">' +
                    escapeHtml(statusLabel(category.status)) + '</span></td>' +
                '</tr>';
        }).join('');

        document.getElementById('ui-tse-body').innerHTML = rows;
        document.getElementById('ui-tse-status').textContent =
            statusLabel(check.status) +
            (check.collection_window ? ' · ' + check.collection_window : '');
    }

    async function loadTseSnapshot(mapping, currentVersion) {
        try {
            validateTseMapping(mapping);
            prepareTsePanel(mapping);
            var response = await fetch(
                '/dx/layer1/api/stats/?date=' +
                encodeURIComponent(mapping.source_date) +
                '&check_type=tse_retail'
            );
            var data = await response.json();
            if (currentVersion !== requestVersion) return;
            if (!response.ok || data.error) {
                throw new Error(data.error || 'TSE 결과를 불러오지 못했습니다.');
            }
            renderTseSnapshot(mapping, data);
        } catch (error) {
            if (currentVersion !== requestVersion) return;
            document.getElementById('ui-tse-status').textContent = '조회 오류';
            showTseMessage(
                error.message || 'TSE 결과를 불러오지 못했습니다.',
                true
            );
        }
    }

    function renderMappings(data) {
        var rows = data.countries.map(function(item) {
            var sources = item.sources.map(function(source) {
                return '<span class="ui-source-key">' +
                    escapeHtml(source.source_key) + ' (' +
                    escapeHtml(source.product) + ')</span>';
            }).join('');
            var ruleClass = item.offset_days === 0 ? ' same-day' : '';

            return '<tr>' +
                '<td class="ui-country">' + escapeHtml(item.country) + '</td>' +
                '<td>' + escapeHtml(item.inspection_date) + '</td>' +
                '<td class="ui-source-date">' + escapeHtml(item.source_date) + '</td>' +
                '<td><span class="ui-rule' + ruleClass + '">' +
                    escapeHtml(item.rule) + '</span></td>' +
                '<td><div class="ui-source-list">' + sources + '</div></td>' +
                '</tr>';
        }).join('');

        document.getElementById('ui-mapping-body').innerHTML = rows;
        document.getElementById('ui-inspection-date').textContent = data.inspection_date;
        document.getElementById('ui-country-count').textContent = data.countries.length + '개국';
        document.getElementById('ui-source-count').textContent = data.source_count + '개';
    }

    async function loadDateMapping() {
        var currentVersion = ++requestVersion;
        var inspectionDate = getSelectedDate();
        if (!inspectionDate) {
            showMessage('검수일을 선택해 주세요.', true);
            document.getElementById('ui-inspection-date').textContent = '-';
            resetTsePanel('검수일을 선택해 주세요.');
            return;
        }

        showMessage('날짜 매핑을 불러오는 중입니다.', false);
        resetTsePanel('날짜 매핑을 기다리는 중입니다.');

        try {
            var response = await fetch(
                '/dx/layer4/api/unified-inspection/date-mapping/?date=' +
                encodeURIComponent(inspectionDate)
            );
            var data = await response.json();
            if (currentVersion !== requestVersion) return;
            if (!response.ok || !data.success) {
                throw new Error(data.error || '날짜 매핑을 불러오지 못했습니다.');
            }

            if (window.history && window.history.replaceState) {
                window.history.replaceState(
                    null,
                    '',
                    window.location.pathname + '?date=' +
                        encodeURIComponent(inspectionDate)
                );
            }
            renderMappings(data);

            var tseMapping = data.countries.find(function(item) {
                return item.country === 'TSE';
            });
            if (!tseMapping) {
                document.getElementById('ui-tse-status').textContent = '조회 오류';
                showTseMessage('날짜 매핑에서 TSE를 찾지 못했습니다.', true);
                return;
            }
            await loadTseSnapshot(tseMapping, currentVersion);
        } catch (error) {
            if (currentVersion !== requestVersion) return;
            showMessage(error.message || '날짜 매핑을 불러오지 못했습니다.', true);
            document.getElementById('ui-inspection-date').textContent = inspectionDate;
            resetTsePanel('유효한 날짜 매핑을 먼저 확인해 주세요.');
        }
    }

    window.L4._sectionHandler.unified_inspection = loadDateMapping;
})();
