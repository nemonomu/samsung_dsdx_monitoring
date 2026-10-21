
// window.DX_DOC_CONFIG 브릿지 변수 매핑
const CONFIG = window.DX_DOC_CONFIG || {};
let currentCategoryId = CONFIG.initialCategory || '';
let currentCategoryType = CONFIG.initialCategoryType || 1;
const newDocBaseUrl = CONFIG.urls?.new_doc || '';

let dataTable = null;

// URL 파라미터에서 카테고리 복원
(function() {
    const params = new URLSearchParams(window.location.search);
    const catParam = params.get('category');
    if (catParam) {
        const catEl = document.querySelector('.category-item[data-id="' + catParam + '"]');
        if (catEl) {
            currentCategoryId = catParam;
            currentCategoryType = parseInt(catEl.getAttribute('data-type')) || 1;
            document.querySelectorAll('.category-item').forEach(item => item.classList.remove('active'));
            catEl.classList.add('active');
            const titleEl = document.getElementById('contentTitle');
            if (titleEl) titleEl.textContent = catEl.querySelector('.category-item-text').textContent;
        }
    }
})();

let docButtonBar = null;
let docFilterBar = null;

function updateToolbar() {
    if (currentCategoryType === 1 || currentCategoryType === 3) {
        if (!docButtonBar && typeof ButtonBar !== 'undefined') {
            document.getElementById('tableToolbar').innerHTML = '';
            docButtonBar = new ButtonBar('#tableToolbar', {
                align: 'between',
                margin: '0 0 16px 0',
                buttons: [
                    { id: 'btnNew', label: '신규', icon: 'plus', style: 'primary', size: 'sm', position: 'left', onClick: function() { goToNewDoc(); } },
                    { id: 'btnEdit', label: '수정', icon: 'edit', style: 'outline', size: 'sm', position: 'left', onClick: function() { goToEditSelected(); } },
                    { id: 'btnDel', label: '삭제', icon: 'delete', style: 'danger', size: 'sm', position: 'left', onClick: function() { deleteSelectedDocs(); } },
                    { id: 'btnPrint', label: '출력', icon: 'print', style: 'outline', size: 'sm', position: 'right', onClick: function() { openReportPopup(); } }
                ]
            }).render();
        } else if (docButtonBar) {
            docButtonBar.showBar();
        }
    } else if (docButtonBar) {
        docButtonBar.hideBar();
    }
}

document.addEventListener('DOMContentLoaded', function() {
    docFilterBar = new FilterBar('#docFilterBar', {
        sticky: false,
        padding: '12px 20px',
        controls: [
            { type: 'date-range', keyFrom: 'dateFrom', keyTo: 'dateTo', label: '생성일' },
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
    initTable();

    if (currentCategoryId) {
        renderDocuments(currentCategoryId);
    }
});

function searchDocuments() {
    if (currentCategoryId) renderDocuments(currentCategoryId);
}

function clearSearch() {
    if (docFilterBar) {
        docFilterBar.setValue('searchText', '');
        docFilterBar.setValue('dateFrom', '');
        docFilterBar.setValue('dateTo', '');
    }
    if (currentCategoryId) renderDocuments(currentCategoryId);
}

function initTable() {
    if (typeof CommonTable === 'undefined') return;
    
    // 테이블 인스턴스 초기화
    dataTable = new CommonTable(document.getElementById('tableContainer'), {
        columns: [
            { key: '_index', label: 'No', width: 50, align: 'center' },
            { key: 'document_id', label: '문서번호', width: 160 },
            { key: 'title', label: '제목', align: 'left' },
            { key: 'created_id', label: '작성자', width: 120 },
            { key: 'created_at', label: '생성일', width: 200 }
        ],
        emptyMessage: '문서가 없습니다.',
        hover: true,
        selectable: true
    });
    dataTable.render();
}

function selectCategory(categoryId, element) {
    if (element.dataset.manualUrl) {
        window.location.assign(element.dataset.manualUrl);
        return;
    }
    currentCategoryId = categoryId;
    currentCategoryType = parseInt(element.getAttribute('data-type')) || 1;
    document.querySelectorAll('.category-item').forEach(item => item.classList.remove('active'));
    element.classList.add('active');
    document.getElementById('contentTitle').textContent = element.querySelector('.category-item-text').textContent;
    updateToolbar();
    renderDocuments(categoryId);
}

function renderDocuments(categoryId) {
    if (dataTable && typeof window.showLoading === 'function') {
        window.showLoading('#tableContainer');
    } else {
        const tbody = document.getElementById('documentsBody');
        if (tbody) tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:40px;color:var(--text-secondary);">불러오는 중...</td></tr>';
    }

    let url = (CONFIG.urls?.api_list || '') + '?category_id=' + encodeURIComponent(categoryId);
    if (docFilterBar) {
        const sf = docFilterBar.getValue('searchField');
        const st = docFilterBar.getValue('searchText');
        const df = docFilterBar.getValue('dateFrom');
        const dt = docFilterBar.getValue('dateTo');
        if (st) url += '&search_field=' + encodeURIComponent(sf) + '&search_text=' + encodeURIComponent(st);
        if (df) url += '&date_from=' + encodeURIComponent(df);
        if (dt) url += '&date_to=' + encodeURIComponent(dt);
    }

    fetch(url)
        .then(r => r.json())
        .then(res => {
            if (dataTable) {
                if (typeof window.hideLoading === 'function') window.hideLoading('#tableContainer');
                
                if (!res.success || !res.documents || res.documents.length === 0) {
                    dataTable.renderBody([], () => '');
                    dataTable.tableEl.querySelector('tbody').innerHTML = '<tr><td colspan="7" style="text-align:center;padding:60px;">문서가 없습니다.</td></tr>';
                } else {
                    dataTable.renderBody(res.documents, (doc, idx) => {
                        // row object MUST have doc.id for CommonTable checkbox to track correctly
                        doc.id = doc.document_id;
                        return `
                        <tr ondblclick="goToEdit('${escapeHtml(doc.document_id)}')">
                            <td style="text-align:center;">${idx + 1}</td>
                            <td>${escapeHtml(doc.document_id)}</td>
                            <td><span class="doc-title">${escapeHtml(doc.title)}</span></td>
                            <td>${escapeHtml(doc.created_id || '-')}</td>
                            <td>${doc.created_at || '-'}</td>
                        </tr>
                        `;
                    });
                }
            } else {
                // 구형 fallback
                const tbody = document.getElementById('documentsBody');
                if (!tbody) return;
                if (!res.success || !res.documents || res.documents.length === 0) {
                    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:60px;">문서가 없습니다.</td></tr>`;
                    return;
                }
                tbody.innerHTML = res.documents.map((doc, idx) => `
                    <tr ondblclick="goToEdit('${escapeHtml(doc.document_id)}')">
                        <td><input type="checkbox" class="doc-checkbox" value="${escapeHtml(doc.document_id)}" onclick="event.stopPropagation();selectSingle(this);" data-title="${escapeHtml(doc.title)}"></td>
                        <td>${idx + 1}</td>
                        <td>${escapeHtml(doc.document_id)}</td>
                        <td>${escapeHtml(doc.title)}</td>
                        <td>${escapeHtml(doc.created_id || '-')}</td>
                        <td>${doc.created_at || '-'}</td>
                    </tr>
                `).join('');
            }
        });
}

function goToNewDoc() {
    window.location.href = newDocBaseUrl + '?category=' + encodeURIComponent(currentCategoryId) + '&type=' + currentCategoryType;
}

function goToEditSelected() {
    if (!dataTable) return;
    const checkedRows = dataTable.getSelectedRows();
    if (checkedRows.length === 0) {
        showToast('수정할 문서를 선택해주세요.', 'warning');
        return;
    }
    if (checkedRows.length > 1) {
        showToast('문서는 하나씩만 수정 가능합니다.', 'warning');
        return;
    }
    goToEdit(checkedRows[0].document_id);
}

function deleteSelectedDocs() {
    if (!dataTable) return;
    const checkedRows = dataTable.getSelectedRows();
    if (checkedRows.length === 0) {
        showToast('삭제할 문서를 선택해주세요.', 'warning');
        return;
    }
    
    const msg = checkedRows.length + '개의 문서를 삭제하시겠습니까?';
    if (typeof showConfirm !== 'undefined') {
        showConfirm(msg, 'warning', { okText: '삭제' }).then(confirmed => {
            if (confirmed) executeDelete(checkedRows);
        });
    } else if (confirm(msg)) {
        executeDelete(checkedRows);
    }
}

function executeDelete(rows) {
    if (typeof window.showLoading === 'function') window.showLoading('#tableContainer');
    
    const deletePromises = rows.map(r => {
        const url = (window.DX_DOC_CONFIG?.urls?.delete_base || '/api/dx/documents/') + encodeURIComponent(r.document_id) + '/delete/';
        return fetch(url, {
            method: 'POST',
            headers: { 'X-CSRFToken': getCsrfToken() }
        })
        .then(res => res.json())
        .catch(() => ({ success: false }));
    });

    Promise.all(deletePromises).then(results => {
        const successCount = results.filter(res => res.success).length;
        if (successCount > 0) {
            showToast(successCount + '개의 문서가 삭제되었습니다.', 'success');
        } else {
            showToast('삭제에 실패했습니다.', 'error');
        }
        renderDocuments(currentCategoryId);
    });
}

function toggleAllCheckboxes(el) {
    document.querySelectorAll('.doc-checkbox').forEach(cb => {
        cb.checked = el.checked;
    });
}

function selectSingle(el) {
    if (el.checked) {
        document.querySelectorAll('.doc-checkbox').forEach(cb => {
            if (cb !== el) cb.checked = false;
        });
    }
}

function copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function() {
            showToast('공유 링크가 복사되었습니다. (24시간 유효)', 'success');
        }).catch(function() {
            fallbackCopy(text);
        });
    } else {
        fallbackCopy(text);
    }
}
function fallbackCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    showToast('공유 링크가 복사되었습니다. (24시간 유효)', 'success');
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

window.esc = window.esc || escapeHtml;

function goToEdit(documentId) {
    window.location.href = (CONFIG.urls?.edit_base || '/dx/documents/') + encodeURIComponent(documentId) + '/edit/';
}

// === 보고서 출력 팝업 ===
let currentReportDocId = '';

function openReportPopup() {
    if (!dataTable) return;
    const checkedRows = dataTable.getSelectedRows();
    if (checkedRows.length === 0) {
        showToast('출력할 문서를 선택해주세요.', 'warning');
        return;
    }
    const documentId = checkedRows[0].document_id;
    currentReportDocId = documentId;
    const title = checkedRows[0].title || '문서';

    document.getElementById('reportPopupTitle').textContent = '문서 보기';
    var docTitleEl = document.getElementById('reportDocTitle');
    docTitleEl.textContent = title;
    docTitleEl.style.display = '';
    document.getElementById('reportPopupBody').querySelector('.ck-content').innerHTML = '<p style="text-align:center;padding:40px;color:var(--text-secondary);">불러오는 중...</p>';
    document.getElementById('reportPopupOverlay').classList.add('active');

    fetch((CONFIG.urls?.api_detail || '') + '?document_id=' + encodeURIComponent(documentId))
        .then(r => r.json())
        .then(res => {
            if (res.success && res.document) {
                const _tmp = document.createElement('div');
                _tmp.innerHTML = res.document.content || '<p>내용이 없습니다.</p>';
                _tmp.querySelectorAll('script,iframe,object,embed').forEach(el => el.remove());
                _tmp.querySelectorAll('*').forEach(el => {
                    [...el.attributes].forEach(attr => { if (attr.name.startsWith('on')) el.removeAttribute(attr.name); });
                });
                document.getElementById('reportPopupBody').querySelector('.ck-content').innerHTML = _tmp.innerHTML;
            } else {
                document.getElementById('reportPopupBody').querySelector('.ck-content').innerHTML = '<p style="text-align:center;color:#dc2626;">문서를 불러올 수 없습니다.</p>';
            }
        })
        .catch(() => {
            document.getElementById('reportPopupBody').querySelector('.ck-content').innerHTML = '<p style="text-align:center;color:#dc2626;">문서를 불러오는 중 오류가 발생했습니다.</p>';
        });
}

function closeReportPopup(event) {
    if (event && event.target && event.target !== document.getElementById('reportPopupOverlay')) return;
    document.getElementById('reportPopupOverlay').classList.remove('active');
    document.getElementById('reportPopup').classList.remove('fullscreen');
}

document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        if (document.getElementById('confirmOverlay') && document.getElementById('confirmOverlay').classList.contains('active')) {
            closeConfirm();
        } else if (document.getElementById('shareMemoOverlay') && document.getElementById('shareMemoOverlay').classList.contains('active')) {
            closeShareMemo();
        } else if (document.getElementById('shareMgmtOverlay') && document.getElementById('shareMgmtOverlay').classList.contains('active')) {
            closeShareMgmt();
        } else if (document.getElementById('reportPopupOverlay') && document.getElementById('reportPopupOverlay').classList.contains('active')) {
            closeReportPopup();
        }
    }
    if (e.key === 'Enter') {
        const shareMemo = document.getElementById('shareMemoOverlay');
        if (shareMemo && shareMemo.classList.contains('active')) {
            e.preventDefault();
            submitShareMemo();
        }
    }
});

function toggleFullscreen() {
    document.getElementById('reportPopup').classList.toggle('fullscreen');
}

function copyReportContent() {
    const content = document.getElementById('reportPopupBody').querySelector('.ck-content');
    if (content) {
        const range = document.createRange();
        range.selectNodeContents(content);
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
        document.execCommand('copy');
        selection.removeAllRanges();
        showToast('내용이 복사되었습니다.', 'success');
    }
}

function copyExistingShareLink(token) {
    const shareUrl = window.location.origin + '/dx-share/' + encodeURIComponent(token) + '/';
    copyToClipboard(shareUrl);
}

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

function submitShareMemo() {
    const memo = document.getElementById('shareMemoInput').value.trim();
    if (!memo) {
        showToast('공유 대상 메모를 입력하세요.', 'warning');
        document.getElementById('shareMemoInput').focus();
        return;
    }
    const submitBtn = document.getElementById('shareMemoSubmitBtn');
    submitBtn.disabled = true;
    submitBtn.textContent = '생성 중...';

    fetch(CONFIG.urls?.api_share_token || '', {
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
    .then(r => r.json())
    .then(res => {
        submitBtn.disabled = false;
        submitBtn.textContent = '링크 생성';
        if (res.success && res.token) {
            closeShareMemo();
            const shareUrl = window.location.origin + '/dx-share/' + encodeURIComponent(res.token) + '/';
            copyToClipboard(shareUrl);
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
    const body = document.getElementById('shareMgmtBody');
    body.innerHTML = '<div class="share-mgmt-empty">불러오는 중...</div>';

    fetch((CONFIG.urls?.api_share_list || '') + '?document_id=' + encodeURIComponent(currentReportDocId))
        .then(r => r.json())
        .then(res => {
            if (!res.success || !res.shares || res.shares.length === 0) {
                body.innerHTML = '<div class="share-mgmt-empty">공유 이력이 없습니다.</div>';
                return;
            }
            const statusTitle = { active: '활성', expired: '만료', revoked: '차단' };
            let html = '<table class="share-mgmt-table"><thead><tr>';
            html += '<th>메모</th><th>생성일</th><th>생성자</th><th>상태</th><th></th>';
            html += '</tr></thead><tbody>';
            res.shares.forEach(s => {
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

function revokeShareToken(tokenId) {
    showConfirm('이 공유 링크를 차단하시겠습니까?\n차단된 링크는 더 이상 접근할 수 없습니다.', 'warning', { okText: '차단' }).then(function(confirmed) {
        if (!confirmed) return;
        
        fetch(CONFIG.urls?.api_share_revoke || '', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({ token_id: tokenId })
        })
        .then(r => r.json())
        .then(res => {
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


function getCsrfToken() {
    const cookie = document.cookie.split(';').find(c => c.trim().startsWith('csrftoken='));
    return cookie ? cookie.split('=')[1] : '';
}

function printReportContent() {
    const docTitle = document.getElementById('reportDocTitle').textContent || '';
    const content = document.getElementById('reportPopupBody').querySelector('.ck-content').innerHTML || '';

    var iframe = document.createElement('iframe');
    iframe.style.position = 'fixed';
    iframe.style.left = '-9999px';
    iframe.style.width = '0';
    iframe.style.height = '0';
    document.body.appendChild(iframe);

    var doc = iframe.contentDocument || iframe.contentWindow.document;
    doc.open();
    // Use the dynamic index.css path instead of django template tag
    const cssPath = document.querySelector('link[href*="index.css"]')?.href || '';
    
    doc.write([
        '<!DOCTYPE html><html><head><meta charset="utf-8">',
        '<title>' + docTitle + '</title>',
        cssPath ? '<link rel="stylesheet" href="' + cssPath + '">' : '',
        '<style>@page { margin: 15mm 20mm; } * { box-sizing: border-box; } body { font-family: "Malgun Gothic", sans-serif; }</style>',
        '</head><body>',
        docTitle ? '<div class="print-title" style="font-size:18px;font-weight:bold;margin-bottom:20px;padding-bottom:10px;border-bottom:2px solid #000;text-align:center;">' + escapeHtml(docTitle) + '</div>' : '',
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
        }, 300);
    };
}
