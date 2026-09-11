(function() {
    var categoryPrefixes = {
        retail: 'retail', siel_retail: 'siel', seg_retail: 'seg',
        sem_retail: 'sem', tse_retail: 'tse'
    };

    function isMissing(retailer) {
        if (retailer.status !== 'CRITICAL' && retailer.status !== 'WARNING') return false;
        // Some countries use MAIN for validation; raw rows still mean collection occurred.
        var fields = ['raw_count', 'actual_count', 'actual', 'count', 'total'];
        for (var i = 0; i < fields.length; i++) {
            var value = retailer[fields[i]];
            if (value !== undefined && value !== null && value !== '') {
                return Number(value) === 0;
            }
        }
        return false;
    }

    function render(check, checkIdx, checkType) {
        var prefix = categoryPrefixes[checkType];
        if (!prefix) return '';
        var items = [];
        var seen = new Set();
        (check.categories || []).forEach(function(cat, catIdx) {
            var product = String(cat.name || cat.category || cat.product_line || '').toUpperCase();
            if (!['TV', 'REF', 'LDY'].includes(product)) return;
            var retailers = (cat.retailers || []).slice();
            (cat.time_slots || []).forEach(function(slot) {
                retailers = retailers.concat(slot.retailers || []);
            });
            retailers.forEach(function(retailer) {
                var name = String(retailer.retailer || '').trim();
                var key = product + ':' + name.toLowerCase();
                if (!name || !isMissing(retailer) || seen.has(key)) return;
                seen.add(key);
                var href = '#' + prefix + '-cat-' + checkIdx + '-' + catIdx;
                var onclick = 'event.stopPropagation();L1.retailStatus.open(this, ' + checkIdx + ')';
                if (checkType === 'retail') {
                    href = '/dx/layer1/retail/?category=' + encodeURIComponent(product) +
                        '&retailer=' + encodeURIComponent(name) + '&period=' + encodeURIComponent('일일') +
                        '&date=' + encodeURIComponent(cat.inspection_date || check.inspection_date || getSelectedDate());
                    onclick = 'event.stopPropagation()';
                }
                items.push('<span class="retail-missing-item"><a href="' + esc(href) +
                    '" onclick="' + onclick + '">' + esc(name) + '</a> ' +
                    esc(product) + ' 미수집</span>');
            });
        });
        return items.length
            ? '<div class="retail-missing-summary" aria-label="수집 시간 경과 미수집">' + items.join('') + '</div>'
            : '';
    }

    function expandCategories(container) {
        container.querySelectorAll('.sentiment-two-column').forEach(function(category) {
            category.classList.add('show');
        });
        container.querySelectorAll('.toggle-icon-small').forEach(function(icon) {
            icon.classList.add('expanded');
        });
    }

    function toggle(element, checkIdx) {
        var container = document.getElementById('time-slots-' + checkIdx);
        if (!container) return;
        var show = container.classList.toggle('show');
        var icon = element.querySelector('.toggle-icon');
        if (icon) icon.classList.toggle('expanded', show);
        if (show) expandCategories(container);
    }

    function open(element, checkIdx) {
        var container = document.getElementById('time-slots-' + checkIdx);
        if (!container) return;
        container.classList.add('show');
        expandCategories(container);
        var icon = element.closest('.check-item').querySelector('.check-name .toggle-icon');
        if (icon) icon.classList.add('expanded');
    }

    L1.retailStatus = { render: render, toggle: toggle, open: open };
})();
