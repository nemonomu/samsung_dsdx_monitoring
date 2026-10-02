/**
 * DS Document - 문서 목록 페이지
 *
 * 의존성:
 *   - security.js : getCsrfToken()
 *   - ui.js       : showToast(), showConfirm(), copyText()
 *   - format.js   : formatFileSize()
 *   - table.js    : CommonTable
 *   - button-bar.js : ButtonBar
 *   - filter-bar.js : FilterBar
 *   - buttons.js  : AppButton
 *
 * data attributes (id="app-data"):
 *   data-initial-category-id   : 첫 번째 카테고리 ID
 *   data-initial-category-type : 첫 번째 카테고리 타입
 *   data-new-doc-base-url      : 새 문서 기본 URL
 *   data-api-list-url          : 문서 목록 API URL
 *   data-api-detail-url        : 문서 상세 API URL
 *   data-api-share-token-url   : 공유 토큰 생성 API URL
 *   data-api-share-list-url    : 공유 목록 API URL
 *   data-api-share-revoke-url  : 공유 차단 API URL
 */

var currentCategoryId = '';
var currentCategoryType = 1;
var newDocBaseUrl = '';
var docFilterBar;
var docButtonBar;
var docTable;

// URL 파라미터에서 카테고리 복원
(function() {
    var appData = document.getElementById('app-data').dataset;
    currentCategoryId = appData.initialCategoryId || '';
    currentCategoryType = parseInt(appData.initialCategoryType) || 1;
    newDocBaseUrl = appData.newDocBaseUrl || '';

    var params = new URLSearchParams(window.location.search);
    var catParam = params.get('category');
    if (catParam) {
        var catEl = document.querySelector('.category-item[data-id="' + catParam + '"]');
        if (catEl) {
            currentCategoryId = catParam;
            currentCategoryType = parseInt(catEl.getAttribute('data-type')) || 1;
            document.querySelectorAll('.category-item').forEach(function(item) { item.classList.remove('active'); });
            catEl.classList.add('active');
            var titleEl = document.getElementById('contentTitle');
            if (titleEl) titleEl.textContent = catEl.querySelector('.category-item-text').textContent;
        }
    }
})();

// 버튼바 표시/숨김 (에디터 포함 타입=1,3 일 때만 표시)
function updateToolbar() {
    if (docButtonBar) docButtonBar.toggleBar(currentCategoryType === 1 || currentCategoryType === 3);
}

// 페이지 로드
document.addEventListener('DOMContentLoaded', function() {
    docTable = new CommonTable('#docTable', {
        variant: 'list',
        columns: [
            { key: 'checkbox', label: '', width: 40 },
            { key: 'no', label: 'No', width: 50 },
            { key: 'document_id', label: '문서번호', width: 160 },
            { key: 'title', label: '제목' },
            { key: 'created_id', label: '작성자', width: 120 },
            { key: 'created_at', label: '생성일', width: 150 },
            { key: 'actions', label: '관리', width: 80, align: 'center' }
        ]
    }).render();

    docButtonBar = new ButtonBar('#docButtonBar', {
        buttons: [
            { id: 'btnPrint', label: '출력', icon: 'print', style: 'outline', onClick: function() { openReportPopup(); } }
        ]
    }).render();

    docFilterBar = new FilterBar('#docFilterBar', {
        sticky: false,
        padding: '12px 20px',
        controls: [
            { type: 'date', key: 'dateFrom', label: '생성일', max: new Date().toISOString().slice(0, 10) },
            { type: 'select', key: 'searchField', options: [
                { value: 'title', label: '제목' },
                { value: 'document_id', label: '문서번호' },
                { value: 'created_id', label: '작성자' }
            ]},
            { type: 'input', key: 'searchText', placeholder: '검색어 입력', onEnter: function() { searchDocuments(); } },
            { type: 'button', label: '조회', style: 'primary', onClick: function() { searchDocuments(); } },
            { type: 'button', label: '해제', style: 'cancel', onClick: function() { clearSearch(); } },
        ]
    }).render();

    updateToolbar();

    if (currentCategoryId) {
        updateNewDocLink();
        renderDocuments(currentCategoryId);
    }
    const documentId = new URLSearchParams(window.location.search).get('document_id');
    if (documentId) openReportPopup(documentId);
});

// 새 문서 버튼 링크 업데이트
function updateNewDocLink() {
    var btn = document.getElementById('btnNewDoc');
    if (btn && currentCategoryId) {
        btn.href = newDocBaseUrl + '?category=' + encodeURIComponent(currentCategoryId) + '&type=' + currentCategoryType;
    }
}

// 카테고리 선택
function selectCategory(categoryId, element) {
    currentCategoryId = categoryId;
    currentCategoryType = parseInt(element.getAttribute('data-type')) || 1;

    document.querySelectorAll('.category-item').forEach(function(item) { item.classList.remove('active'); });
    element.classList.add('active');

    document.getElementById('contentTitle').textContent = element.querySelector('.category-item-text').textContent;

    updateNewDocLink();
    updateToolbar();
    renderDocuments(categoryId);
}

// 검색
function searchDocuments() {
    var df = docFilterBar.getValue('dateFrom');
    if (df && df > new Date().toISOString().slice(0, 10)) {
        showToast('오늘 이후 날짜로는 조회할 수 없습니다.', 'warning');
        return;
    }
    if (currentCategoryId) renderDocuments(currentCategoryId);
}

function clearSearch() {
    docFilterBar.setValue('searchText', '');
    docFilterBar.setValue('dateFrom', '');
    if (currentCategoryId) renderDocuments(currentCategoryId);
}

// 문서 목록 렌더링
function renderDocuments(categoryId) {
    var appData = document.getElementById('app-data').dataset;
    var tbody = docTable.getTable().querySelector('tbody');
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:40px;color:var(--text-secondary);">불러오는 중...</td></tr>';

    var url = appData.apiListUrl + '?category_id=' + encodeURIComponent(categoryId);
    if (docFilterBar) {
        var sf = docFilterBar.getValue('searchField');
        var st = docFilterBar.getValue('searchText');
        var df = docFilterBar.getValue('dateFrom');
        if (st) url += '&search_field=' + encodeURIComponent(sf) + '&search_text=' + encodeURIComponent(st);
        if (df) url += '&date_from=' + encodeURIComponent(df);
    }

    fetch(url)
        .then(function(r) { return r.json(); })
        .then(function(res) {
            // 카운트 업데이트
            var countEl = document.getElementById('count-' + categoryId);
            if (countEl) countEl.textContent = res.total || 0;

            if (!res.success || !res.documents || res.documents.length === 0) {
                tbody.innerHTML = '<tr>' +
                    '<td colspan="7" style="text-align: center; padding: 60px; color: var(--text-secondary);">' +
                        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="width:48px;height:48px;margin-bottom:12px;opacity:0.4;">' +
                            '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>' +
                            '<polyline points="14 2 14 8 20 8"/>' +
                        '</svg>' +
                        '<p>문서가 없습니다.</p>' +
                    '</td>' +
                '</tr>';
                return;
            }

            docTable.renderBody(res.documents, function(doc, idx) {
                return '<tr ondblclick="goToEdit(\'' + doc.document_id + '\')">' +
                    '<td class="ct-nc"><input type="checkbox" class="doc-checkbox" value="' + doc.document_id + '" onclick="event.stopPropagation();selectSingle(this);" data-title="' + escapeHtml(doc.title) + '"></td>' +
                    '<td>' + (idx + 1) + '</td>' +
                    '<td class="doc-meta">' + escapeHtml(doc.document_id) + '</td>' +
                    '<td class="doc-title">' + escapeHtml(doc.title) + '</td>' +
                    '<td class="doc-meta">' + escapeHtml(doc.created_id || '-') + '</td>' +
                    '<td class="doc-meta">' + (doc.created_at || '-') + '</td>' +
                    '<td class="ct-nc">' + AppButton.iconHtml('edit', "event.stopPropagation();goToEdit('" + doc.document_id + "')", { color: 'purple' }) + '</td>' +
                '</tr>';
            });
        });
}

// 단일 선택 (하나만 체크)
function selectSingle(el) {
    if (el.checked) {
        docTable.getTable().querySelectorAll('tbody .doc-checkbox').forEach(function(cb) {
            if (cb !== el) cb.checked = false;
        });
    }
}

// escapeHtml → esc() (security.js 공통)
var escapeHtml = esc;

// 편집 페이지로 이동
function goToEdit(documentId) {
    window.location.href = '/ds/documents/' + encodeURIComponent(documentId) + '/edit/';
}

// === 보고서 출력 팝업 ===
var currentReportDocId = '';

function openReportPopup(documentId) {
    var appData = document.getElementById('app-data').dataset;
    var title = '문서';
    if (typeof documentId !== 'string' || !documentId) {
        var checked = docTable.getTable().querySelectorAll('tbody .doc-checkbox:checked');
        if (checked.length === 0) {
            showToast('출력할 문서를 선택해주세요.', 'warning');
            return;
        }
        documentId = checked[0].value;
        title = checked[0].getAttribute('data-title') || '문서';
    }
    currentReportDocId = documentId;

    document.getElementById('reportPopupTitle').textContent = '문서 보기';
    var docTitleEl = document.getElementById('reportDocTitle');
    docTitleEl.textContent = title;
    docTitleEl.style.display = '';
    document.getElementById('reportPopupBody').querySelector('.ck-content').innerHTML = '<p style="text-align:center;padding:40px;color:var(--text-secondary);">불러오는 중...</p>';
    document.getElementById('reportPopupOverlay').classList.add('active');

    fetch(appData.apiDetailUrl + '?document_id=' + encodeURIComponent(documentId))
        .then(function(r) { return r.json(); })
        .then(function(res) {
            if (res.success && res.document) {
                docTitleEl.textContent = res.document.title || title;
                var _tmp = document.createElement('div');
                _tmp.innerHTML = res.document.content || '<p>내용이 없습니다.</p>';
                _tmp.querySelectorAll('script,iframe,object,embed').forEach(function(el) { el.remove(); });
                _tmp.querySelectorAll('*').forEach(function(el) {
                    [].slice.call(el.attributes).forEach(function(attr) { if (attr.name.startsWith('on')) el.removeAttribute(attr.name); });
                });
                document.getElementById('reportPopupBody').querySelector('.ck-content').innerHTML = _tmp.innerHTML;
            } else {
                document.getElementById('reportPopupBody').querySelector('.ck-content').innerHTML = '<p style="text-align:center;color:#dc2626;">문서를 불러올 수 없습니다.</p>';
            }
        })
        .catch(function() {
            document.getElementById('reportPopupBody').querySelector('.ck-content').innerHTML = '<p style="text-align:center;color:#dc2626;">문서를 불러오는 중 오류가 발생했습니다.</p>';
        });
}

function closeReportPopup(event) {
    if (event && event.target && event.target !== document.getElementById('reportPopupOverlay')) return;
    document.getElementById('reportPopupOverlay').classList.remove('active');
    document.getElementById('reportPopup').classList.remove('fullscreen');
}

// ESC 키로 닫기
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        if (document.getElementById('confirmOverlay') && document.getElementById('confirmOverlay').classList.contains('active')) {
            closeConfirm();
        } else if (document.getElementById('shareMemoOverlay').classList.contains('active')) {
            closeShareMemo();
        } else if (document.getElementById('shareMgmtOverlay').classList.contains('active')) {
            closeShareMgmt();
        } else {
            closeReportPopup();
        }
    }
});

// 전체화면 토글
function toggleFullscreen() {
    document.getElementById('reportPopup').classList.toggle('fullscreen');
}

// 인쇄
function printReportContent() {
    var docTitle = document.getElementById('reportDocTitle').textContent || '';
    var content = document.getElementById('reportPopupBody').querySelector('.ck-content').innerHTML || '';

    var iframe = document.createElement('iframe');
    iframe.style.position = 'fixed';
    iframe.style.left = '-9999px';
    iframe.style.width = '0';
    iframe.style.height = '0';
    document.body.appendChild(iframe);

    var doc = iframe.contentDocument || iframe.contentWindow.document;
    doc.open();
    doc.write([
        '<!DOCTYPE html><html><head><meta charset="utf-8">',
        '<title>' + docTitle + '</title>',
        '<style>',
        '  @page { margin: 15mm 20mm; }',
        '  * { box-sizing: border-box; }',
        '  body { font-family: "Malgun Gothic", "맑은 고딕", sans-serif; font-size: 12px; line-height: 1.4; color: #1e293b; max-width: 100%; overflow-x: hidden; }',
        '  .print-title { font-size: 18px; font-weight: 700; text-align: center; padding-bottom: 12px; margin-bottom: 20px; border-bottom: 2px solid #1e293b; }',
        '  h2 { font-size: 15px; margin-top: 0.6em; margin-bottom: 0.2em; }',
        '  h3 { font-size: 14px; margin-top: 0.6em; margin-bottom: 0.2em; }',
        '  h4 { font-size: 13px; margin-top: 0.5em; margin-bottom: 0.2em; }',
        '  p { margin: 0.2em 0; }',
        '  figure { margin: 0.4em 0; display: block; float: none !important; overflow: hidden; }',
        '  figure.table { margin: 0.4em 0; float: none !important; }',
        '  table { width: auto; max-width: 100%; border-collapse: collapse; margin: 0.5em 0; page-break-inside: auto; }',
        '  tr { page-break-inside: avoid; }',
        '  table td, table th { border: 1px solid #999; padding: 4px 6px; font-size: 11px; word-break: break-word; }',
        '  table th { background: #eee !important; font-weight: 600; -webkit-print-color-adjust: exact; print-color-adjust: exact; }',
        '  img { max-width: 100% !important; height: auto !important; page-break-inside: avoid; display: block; margin: 0.5em auto; }',
        '  figure.image { text-align: center; page-break-inside: avoid; }',
        '  hr { border: none; border-top: 1px solid #ccc; margin: 0.8em 0; }',
        '</style>',
        '</head><body>',
        docTitle ? '<div class="print-title">' + docTitle.replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</div>' : '',
        '<div class="ck-content">' + content + '</div>',
        '</body></html>'
    ].join(''));
    doc.close();

    iframe.contentWindow.onafterprint = function() {
        if (iframe.parentNode) document.body.removeChild(iframe);
    };

    iframe.contentWindow.onload = function() {
        setTimeout(function() {
            iframe.contentWindow.focus();
            iframe.contentWindow.print();
            setTimeout(function() {
                if (iframe.parentNode) document.body.removeChild(iframe);
            }, 5000);
        }, 200);
    };
}

// === 공유 기능 ===

// 기존 공유 링크 복사
function copyExistingShareLink(token) {
    var shareUrl = window.location.origin + '/ds-share/' + encodeURIComponent(token) + '/';
    copyText(shareUrl).then(function() {
        showToast('공유 링크가 복사되었습니다. (24시간 유효)', 'success');
    });
}

// 공유 링크 생성 (메모 팝업 열기)
function copyShareLink() {
    if (!currentReportDocId) {
        showToast('문서가 선택되지 않았습니다.', 'warning');
        return;
    }
    document.getElementById('shareMemoInput').value = '';
    document.getElementById('shareMemoOverlay').classList.add('active');
    document.getElementById('shareMemoInput').focus();
}

function closeShareMemo(event) {
    if (event && event.target && event.target !== document.getElementById('shareMemoOverlay')) return;
    document.getElementById('shareMemoOverlay').classList.remove('active');
}

// 메모 입력 후 토큰 생성
function submitShareMemo() {
    var appData = document.getElementById('app-data').dataset;
    var memo = document.getElementById('shareMemoInput').value.trim();
    if (!memo) {
        showToast('공유 대상 메모를 입력하세요.', 'warning');
        document.getElementById('shareMemoInput').focus();
        return;
    }
    var submitBtn = document.getElementById('shareMemoSubmitBtn');
    submitBtn.disabled = true;
    submitBtn.textContent = '생성 중...';

    fetch(appData.apiShareTokenUrl, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify({
            document_id: currentReportDocId,
            category_id: currentCategoryId,
            memo: memo
        })
    })
        .then(function(r) { return r.json(); })
        .then(function(res) {
            submitBtn.disabled = false;
            submitBtn.textContent = '링크 생성';
            if (res.success && res.token) {
                closeShareMemo();
                var shareUrl = window.location.origin + '/ds-share/' + encodeURIComponent(res.token) + '/';
                copyText(shareUrl).then(function() { showToast('공유 링크가 복사되었습니다. (24시간 유효)', 'success'); });
            } else {
                showToast(res.error || '링크 생성에 실패했습니다.', 'error');
            }
        })
        .catch(function() {
            submitBtn.disabled = false;
            submitBtn.textContent = '링크 생성';
            showToast('링크 생성 중 오류가 발생했습니다.', 'error');
        });
}

// 공유 관리 팝업
function openShareMgmt() {
    if (!currentReportDocId) {
        showToast('문서가 선택되지 않았습니다.', 'warning');
        return;
    }
    document.getElementById('shareMgmtOverlay').classList.add('active');
    loadShareList();
}

function closeShareMgmt(event) {
    if (event && event.target && event.target !== document.getElementById('shareMgmtOverlay')) return;
    document.getElementById('shareMgmtOverlay').classList.remove('active');
}

function loadShareList() {
    var appData = document.getElementById('app-data').dataset;
    var body = document.getElementById('shareMgmtBody');
    body.innerHTML = '<div class="share-mgmt-empty">불러오는 중...</div>';

    fetch(appData.apiShareListUrl + '?document_id=' + encodeURIComponent(currentReportDocId))
        .then(function(r) { return r.json(); })
        .then(function(res) {
            if (!res.success || !res.shares || res.shares.length === 0) {
                body.innerHTML = '<div class="share-mgmt-empty">공유 이력이 없습니다.</div>';
                return;
            }
            var statusTitle = { active: '활성', expired: '만료', revoked: '차단' };
            var html = '<table class="share-mgmt-table"><thead><tr>';
            html += '<th>메모</th><th>생성일</th><th>생성자</th><th>상태</th><th></th>';
            html += '</tr></thead><tbody>';
            res.shares.forEach(function(s) {
                html += '<tr>';
                html += '<td>' + escapeHtml(s.memo || '-') + '</td>';
                html += '<td>' + (s.created_at || '-') + '</td>';
                html += '<td>' + escapeHtml(s.created_id || '-') + '</td>';
                html += '<td><span class="share-status-dot ' + s.status + '" title="' + (statusTitle[s.status] || s.status) + '"></span></td>';
                html += '<td class="actions">';
                if (s.status === 'active') {
                    html += AppButton.iconHtml('copy', "copyExistingShareLink('" + escapeHtml(s.token) + "')", { style: 'ghost', title: '링크 복사' });
                    html += AppButton.iconHtml('ban', "revokeShareToken('" + escapeHtml(s.id) + "')", { style: 'ghost', title: '차단', color: 'red' });
                }
                html += '</td>';
                html += '</tr>';
            });
            html += '</tbody></table>';
            body.innerHTML = html;
        })
        .catch(function() {
            body.innerHTML = '<div class="share-mgmt-empty">불러오는 중 오류가 발생했습니다.</div>';
        });
}

// 공유 토큰 차단
function revokeShareToken(tokenId) {
    var appData = document.getElementById('app-data').dataset;
    showConfirmCustom('공유 링크 차단', '이 공유 링크를 차단하시겠습니까?\n차단된 링크는 더 이상 접근할 수 없습니다.', '차단', function() {
        fetch(appData.apiShareRevokeUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({ token_id: tokenId })
        })
            .then(function(r) { return r.json(); })
            .then(function(res) {
                if (res.success) {
                    showToast('공유 링크가 차단되었습니다.', 'success');
                    loadShareList();
                } else {
                    showToast(res.error || '차단에 실패했습니다.', 'error');
                }
            })
            .catch(function() {
                showToast('차단 중 오류가 발생했습니다.', 'error');
            });
    });
}

// 확인 팝업 (index 전용 - DOM 기반)
function showConfirmCustom(title, message, okText, onConfirm) {
    document.getElementById('confirmTitle').textContent = title;
    document.getElementById('confirmMessage').textContent = message;
    var okBtn = document.getElementById('confirmOkBtn');
    okBtn.textContent = okText;
    okBtn.onclick = function() {
        closeConfirm();
        onConfirm();
    };
    document.getElementById('confirmOverlay').classList.add('active');
}

function closeConfirm() {
    document.getElementById('confirmOverlay').classList.remove('active');
}
