(function() {
    'use strict';

    var currentPage = 1;
    var pageSize = 20;
    var productsByCountry = {
        SEA: ['TV'],
        SIEL: ['TV', 'REF', 'LDY']
    };

    function escapeHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function dateText(date) {
        return date.getFullYear() + '-'
            + String(date.getMonth() + 1).padStart(2, '0') + '-'
            + String(date.getDate()).padStart(2, '0');
    }

    function shiftDate(days) {
        var input = document.getElementById('redirectDate');
        var date = new Date((input.value || dateText(new Date())) + 'T00:00:00');
        date.setDate(date.getDate() + days);
        input.value = dateText(date);
        loadData(1);
    }

    function selectedScope() {
        return {
            country: document.getElementById('redirectCountry').value,
            product: document.getElementById('redirectProduct').value
        };
    }

    function syncProductOptions() {
        var country = document.getElementById('redirectCountry').value;
        var productSelect = document.getElementById('redirectProduct');
        var previous = productSelect.value;
        var products = productsByCountry[country] || [];

        productSelect.innerHTML = '';
        products.forEach(function(product) {
            var option = document.createElement('option');
            option.value = product;
            option.textContent = product;
            productSelect.appendChild(option);
        });
        if (products.indexOf(previous) !== -1) productSelect.value = previous;
        document.getElementById('redirectScopeTitle').textContent =
            country + ' ' + productSelect.value;
    }

    function displayValue(value) {
        if (value === null || value === undefined || value === '') return '-';
        if (value === true) return 'TRUE';
        if (value === false) return 'FALSE';
        if (typeof value === 'object') return JSON.stringify(value);
        return String(value);
    }

    function renderTable(data) {
        var container = document.getElementById('redirectTable');
        var summary = document.getElementById('redirectSummary');
        var columns = data.columns || [];
        var items = data.items || [];

        summary.innerHTML = escapeHtml(data.country) + ' '
            + escapeHtml(data.product) + ' / ' + escapeHtml(data.date)
            + ' / Amazon redirect=TRUE / 총 <strong>'
            + Number(data.total || 0).toLocaleString() + '</strong>건';

        if (!items.length) {
            container.innerHTML = '<div class="redirect-empty">조회된 데이터가 없습니다.</div>';
            return;
        }

        var html = '<table class="redirect-table"><thead><tr>';
        columns.forEach(function(column) {
            html += '<th>' + escapeHtml(column) + '</th>';
        });
        html += '</tr></thead><tbody>';

        items.forEach(function(item) {
            html += '<tr>';
            columns.forEach(function(column) {
                var value = displayValue(item[column]);
                html += '<td title="' + escapeHtml(value) + '">'
                    + escapeHtml(value) + '</td>';
            });
            html += '</tr>';
        });
        html += '</tbody></table>';
        container.innerHTML = html;
    }

    function renderPagination(total, page) {
        var container = document.getElementById('redirectPagination');
        var totalPages = Math.max(1, Math.ceil(total / pageSize));
        container.innerHTML = '';

        var prev = document.createElement('button');
        prev.className = 'redirect-btn';
        prev.textContent = '이전';
        prev.disabled = page <= 1;
        prev.addEventListener('click', function() { loadData(page - 1); });

        var info = document.createElement('span');
        info.textContent = page + ' / ' + totalPages;

        var next = document.createElement('button');
        next.className = 'redirect-btn';
        next.textContent = '다음';
        next.disabled = page >= totalPages;
        next.addEventListener('click', function() { loadData(page + 1); });

        container.appendChild(prev);
        container.appendChild(info);
        container.appendChild(next);
    }

    async function loadData(page) {
        var input = document.getElementById('redirectDate');
        if (!input.value) return;
        currentPage = page;
        var scope = selectedScope();
        document.getElementById('redirectScopeTitle').textContent =
            scope.country + ' ' + scope.product;

        document.getElementById('redirectSummary').textContent = '조회 중...';
        document.getElementById('redirectTable').innerHTML = '';

        var params = new URLSearchParams({
            date: input.value,
            country: scope.country,
            product: scope.product,
            page: currentPage,
            page_size: pageSize
        });

        try {
            var response = await fetch('/dx/data/api/redirect-data/list/?' + params.toString());
            var data = await response.json();
            if (!response.ok || data.error) throw new Error(data.error || '조회 실패');
            renderTable(data);
            renderPagination(data.total || 0, data.page || 1);
        } catch (error) {
            document.getElementById('redirectSummary').textContent = '조회 오류';
            document.getElementById('redirectTable').innerHTML = '<div class="redirect-empty">'
                + escapeHtml(error.message) + '</div>';
            document.getElementById('redirectPagination').innerHTML = '';
        }
    }

    document.addEventListener('DOMContentLoaded', function() {
        var initial = new Date();
        initial.setDate(initial.getDate() - 1);
        document.getElementById('redirectDate').value = dateText(initial);
        syncProductOptions();

        document.getElementById('redirectCountry').addEventListener('change', function() {
            syncProductOptions();
            loadData(1);
        });
        document.getElementById('redirectProduct').addEventListener('change', function() {
            loadData(1);
        });

        document.getElementById('redirectSearch').addEventListener('click', function() {
            loadData(1);
        });
        document.getElementById('redirectPrev').addEventListener('click', function() {
            shiftDate(-1);
        });
        document.getElementById('redirectNext').addEventListener('click', function() {
            shiftDate(1);
        });

        loadData(1);
    });
})();
