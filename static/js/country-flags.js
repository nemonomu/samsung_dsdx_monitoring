(function(global) {
    'use strict';

    function escapeHtml(value) {
        return String(value === null || value === undefined ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function getFlagCode(text) {
        if (/^SEA(?:\s|$)/.test(text)) return 'us';
        if (/^SIEL(?:\s|$)/.test(text)) return 'in';
        if (/^TSE(?:\s|$)/.test(text)) return 'th';
        return '';
    }

    global.renderCountryFlagLabel = function(value) {
        var text = String(value === null || value === undefined ? '' : value);
        var code = getFlagCode(text);
        var safeText = escapeHtml(text);
        if (!code) return safeText;

        var baseUrl = global.COUNTRY_FLAG_BASE_URL || '/static/img/flags/';
        return '<span class="country-flag-label">'
            + '<img class="country-flag-icon" src="' + escapeHtml(baseUrl + code + '.svg') + '" alt="" aria-hidden="true">'
            + '<span>' + safeText + '</span>'
            + '</span>';
    };
})(window);
