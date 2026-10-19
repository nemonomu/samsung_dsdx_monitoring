// SEIB Spain MediaMarkt retail renderer. The response shape matches TSE.
(function() {
    function render(check, checkIdx) {
        var original = window.L1.renderers.tse_retail;
        if (!original) return '';
        var html = original(check, checkIdx);
        return html
            .replace(/toggleTseCategory/g, 'toggleSeibCategory')
            .replace(/tse-cat-/g, 'seib-cat-');
    }

    window.toggleSeibCategory = function(element, checkIdx, catIdx) {
        var container = document.getElementById(
            'seib-cat-' + checkIdx + '-' + catIdx
        );
        var icon = element.querySelector('.toggle-icon-small');
        if (!container) return;
        container.classList.toggle('show');
        if (icon) icon.classList.toggle('expanded');
    };

    L1.renderers.seib_retail = render;
})();
