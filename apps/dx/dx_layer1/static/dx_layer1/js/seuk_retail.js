// SEUK UK Currys retail renderer. The response shape matches TSE.
(function() {
    function render(check, checkIdx) {
        var original = window.L1.renderers.tse_retail;
        if (!original) return '';
        var html = original(check, checkIdx);
        if (check.source_date < check.active_from) {
            html = html.replace(/설정된 리테일러 데이터 없음/g, '2026-10-25부터 수집 여부를 점검합니다.')
                .replace(/0\/0건/g, '운영 시작 전');
        }
        return html
            .replace(/toggleTseCategory/g, 'toggleSeukCategory')
            .replace(/tse-cat-/g, 'seuk-cat-');
    }

    window.toggleSeukCategory = function(element, checkIdx, catIdx) {
        var container = document.getElementById(
            'seuk-cat-' + checkIdx + '-' + catIdx
        );
        var icon = element.querySelector('.toggle-icon-small');
        if (!container) return;
        container.classList.toggle('show');
        if (icon) icon.classList.toggle('expanded');
    };

    L1.renderers.seuk_retail = render;
})();
