/**
 * Layer 4 공통 모듈 — 상수, 유틸, 사이드바, 초기화 디스패처
 */

(function() {
    'use strict';

    var section = (window.LAYER4 && window.LAYER4.section) || 'dashboard';

    window.L4 = {
        section: section,

        // 상수
        TYPE_NAMES: {
            'null_check': 'NULL 검증',
            'format_check': '형식 검증',
            'duplicate_check': '중복 검증',
            'cross_field': '크로스필드 검증',
            'field_missing': '누락필드 검증'
        },
        STATUS_NAMES: {
            'corrected': '수정',
            'normal': '확인',
            'reverted': '취소'
        },
        CHECK_SECTION_NAMES: {
            retail: 'Retail',
            sentiment: '감성분석',
            youtube: 'YouTube',
            market_trend: 'Market Trend',
            market_competitor: 'Market Competitor',
            market_competitor_event: 'Competitor Event',
            market_demand: '수요증감율',
            market_promotion: 'Promotion'
        },

        // 유틸
        escapeHtml: function(str) {
            if (!str) return '';
            return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        },
        formatNumber: function(n) {
            return (n || 0).toLocaleString();
        },

        // 섹션별 핸들러/초기화 등록소
        _sectionHandler: {},
        _sectionInit: {}
    };

    // 사이드바 클릭 핸들러
    window.onSubitemClick = function(groupKey, itemName) {
        var date = section === 'unified_inspection'
            ? ''
            : (typeof getSelectedDate === 'function' ? getSelectedDate() : '');
        var params = [];
        if (date) params.push('date=' + date);
        if (itemName) params.push('focus=' + encodeURIComponent(itemName));
        var qs = params.length > 0 ? '?' + params.join('&') : '';

        if (groupKey === 'check_log') {
            window.location.href = '/dx/layer4/check-log/' + qs;
        } else if (groupKey === 'corrections') {
            window.location.href = '/dx/layer4/corrections/' + qs;
        } else if (groupKey === 'report') {
            window.location.href = '/dx/layer4/report/' + qs;
        } else if (groupKey === 'collection_status') {
            window.location.href = '/dx/layer4/collection-status/' + qs;
        } else if (groupKey === 'tools') {
            window.location.href = '/dx/layer4/tools/' + qs;
        }
    };

    // 조회 디스패처
    window.handleSearch = function() {
        var fn = L4._sectionHandler[section];
        if (fn) fn();
    };

    // 초기화
    document.addEventListener('DOMContentLoaded', function() {
        var init = L4._sectionInit[section];
        if (init) init();
        initFilterBar();
        handleSearch();
    });

})();
