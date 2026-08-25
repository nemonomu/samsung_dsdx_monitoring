/**
 * Unified inspection — read-only inspection/source-date mapping.
 */

(function() {
    'use strict';

    var requestVersion = 0;

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
            return;
        }

        showMessage('날짜 매핑을 불러오는 중입니다.', false);

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
        } catch (error) {
            if (currentVersion !== requestVersion) return;
            showMessage(error.message || '날짜 매핑을 불러오지 못했습니다.', true);
            document.getElementById('ui-inspection-date').textContent = inspectionDate;
        }
    }

    window.L4._sectionHandler.unified_inspection = loadDateMapping;
})();
