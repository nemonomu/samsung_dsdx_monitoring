// SEM Mexico Liverpool retail renderer. The response shape matches TSE.
(function() {
    function render(check, checkIdx) {
        var original = window.L1.renderers.tse_retail;
        if (!original) return '';
        var html = original(check, checkIdx);
        return html
            .replace(/toggleTseCategory/g, 'toggleSemCategory')
            .replace(/tse-cat-/g, 'sem-cat-');
    }

    window.toggleSemCategory = function(element, checkIdx, catIdx) {
        var container = document.getElementById(
            'sem-cat-' + checkIdx + '-' + catIdx
        );
        var icon = element.querySelector('.toggle-icon-small');
        if (!container) return;
        container.classList.toggle('show');
        if (icon) icon.classList.toggle('expanded');
    };

    L1.renderers.sem_retail = render;
})();
