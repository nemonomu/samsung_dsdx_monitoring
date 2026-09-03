/* ================================================================
 *  DS Layer4 – screenshot.js
 *  스크린샷 뷰어, 업로드, 캡쳐, 폴링
 * ================================================================ */

// 스크린샷 모달
let currentScreenshotAnomalyId = null;
let screenshotList = []; // { fileId, anomalyId, retailer } 리스트
let screenshotIndex = -1;
let screenshotCauseBaseline = '';
let screenshotCauseDirty = false;
let screenshotCauseSaving = false;
const SCREENSHOT_CUSTOM_CAUSE = '__custom__';

function getScreenshotAnomaly(anomalyId) {
    if (!reportData || !reportData.anomalies) return null;
    return reportData.anomalies.find(a => a.id === anomalyId) || null;
}

function getScreenshotCauseValue() {
    const select = document.getElementById('screenshotCauseSelect');
    const customInput = document.getElementById('screenshotCustomCause');
    if (!select) return '';
    if (select.value === SCREENSHOT_CUSTOM_CAUSE) {
        return String(customInput.value || '').trim();
    }
    return normalizeReportCause(select.value);
}

function updateScreenshotCauseDirty() {
    const saveBtn = document.getElementById('screenshotCauseSaveBtn');
    const customInput = document.getElementById('screenshotCustomCause');
    if (customInput) customInput.title = String(customInput.value || '').trim();
    screenshotCauseDirty = getScreenshotCauseValue() !== screenshotCauseBaseline;
    if (saveBtn) saveBtn.disabled = !screenshotCauseDirty || screenshotCauseSaving;
}

function handleScreenshotCauseChange() {
    const select = document.getElementById('screenshotCauseSelect');
    const customInput = document.getElementById('screenshotCustomCause');
    const isCustom = select.value === SCREENSHOT_CUSTOM_CAUSE;
    select.title = isCustom ? '기타(직접 입력)' : select.value;
    customInput.hidden = !isCustom;
    if (isCustom) customInput.focus();
    updateScreenshotCauseDirty();
}

function handleScreenshotCauseKeydown(event) {
    if (event.key === 'Enter') {
        event.preventDefault();
        saveScreenshotCause();
    }
}

function renderScreenshotCauseEditor(anomalyId) {
    const editor = document.getElementById('screenshotCauseEditor');
    const select = document.getElementById('screenshotCauseSelect');
    const customInput = document.getElementById('screenshotCustomCause');
    const saveBtn = document.getElementById('screenshotCauseSaveBtn');
    const readonly = document.getElementById('screenshotCauseReadonly');
    const anomaly = getScreenshotAnomaly(anomalyId);

    if (!anomaly) {
        editor.style.display = 'none';
        return;
    }

    editor.style.display = 'flex';
    const currentCause = normalizeReportCause(anomaly.cause);
    const options = causeOptions[anomaly.retailer] || [];
    screenshotCauseBaseline = currentCause;
    screenshotCauseDirty = false;
    screenshotCauseSaving = false;

    if (isClosed) {
        select.hidden = true;
        customInput.hidden = true;
        saveBtn.hidden = true;
        readonly.hidden = false;
        readonly.textContent = currentCause || '원인 미입력';
        readonly.title = currentCause;
        readonly.classList.toggle('empty', !currentCause);
        return;
    }

    select.hidden = false;
    select.disabled = false;
    customInput.disabled = false;
    saveBtn.hidden = false;
    readonly.hidden = true;
    select.innerHTML = '<option value="">선택</option>'
        + options.map(option => `<option value="${esc(option)}">${esc(option)}</option>`).join('')
        + `<option value="${SCREENSHOT_CUSTOM_CAUSE}">기타(직접 입력)</option>`;

    if (currentCause && options.includes(currentCause)) {
        select.value = currentCause;
        select.title = currentCause;
        customInput.value = '';
        customInput.hidden = true;
    } else if (currentCause) {
        select.value = SCREENSHOT_CUSTOM_CAUSE;
        select.title = '기타(직접 입력)';
        customInput.value = currentCause;
        customInput.title = currentCause;
        customInput.hidden = false;
    } else {
        select.value = '';
        select.title = '원인 선택';
        customInput.value = '';
        customInput.title = '';
        customInput.hidden = true;
    }
    saveBtn.disabled = true;
    saveBtn.textContent = '저장';
}

async function confirmDiscardScreenshotCause() {
    if (screenshotCauseSaving) {
        showToast('원인을 저장하고 있습니다. 잠시만 기다려 주세요.', 'info');
        return false;
    }
    if (!screenshotCauseDirty) return true;
    return await showConfirm(
        '수정한 원인이 저장되지 않았습니다. 변경사항을 버릴까요?',
        'warning',
        { okText: '버리기', cancelText: '계속 수정' }
    );
}

function refreshCauseAfterScreenshotSave(anomaly, previousCause) {
    if (!previousCause && anomaly.cause) {
        reportData.filled_cause = (reportData.filled_cause || 0) + 1;
    }
    updateSummary(reportData);
    renderReportTable(reportData);
}

async function saveScreenshotCause() {
    if (isClosed || screenshotCauseSaving || !currentScreenshotAnomalyId) return;

    const cause = getScreenshotCauseValue();
    if (!cause) {
        showToast('원인을 선택하거나 직접 입력해 주세요.', 'warning');
        const select = document.getElementById('screenshotCauseSelect');
        const customInput = document.getElementById('screenshotCustomCause');
        (select.value === SCREENSHOT_CUSTOM_CAUSE ? customInput : select).focus();
        return;
    }

    const anomaly = getScreenshotAnomaly(currentScreenshotAnomalyId);
    if (!anomaly) return;

    const saveBtn = document.getElementById('screenshotCauseSaveBtn');
    const select = document.getElementById('screenshotCauseSelect');
    const customInput = document.getElementById('screenshotCustomCause');
    const deleteBtn = document.getElementById('screenshotDeleteBtn');
    const previousCause = normalizeReportCause(anomaly.cause);
    screenshotCauseSaving = true;
    saveBtn.disabled = true;
    saveBtn.textContent = '저장 중...';
    select.disabled = true;
    customInput.disabled = true;
    deleteBtn.disabled = true;

    try {
        const response = await fetch('/ds/layer4/api/update/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({
                anomaly_id: anomaly.id,
                cause: cause,
                user_id: currentUserId
            })
        });
        const result = await response.json();
        if (!result.success) {
            throw new Error(result.error || '원인 저장 실패');
        }

        anomaly.cause = cause;
        screenshotCauseBaseline = cause;
        screenshotCauseDirty = false;
        refreshCauseAfterScreenshotSave(anomaly, previousCause);
        renderScreenshotCauseEditor(anomaly.id);
        showToast('원인이 저장되었습니다.', 'success');
    } catch (error) {
        showToast(error.message || '원인 저장 중 오류가 발생했습니다.', 'error');
    } finally {
        screenshotCauseSaving = false;
        saveBtn.textContent = '저장';
        select.disabled = false;
        customInput.disabled = false;
        deleteBtn.disabled = false;
        updateScreenshotCauseDirty();
    }
}

// 같은 리테일러의 스크린샷 목록 구성
function buildScreenshotList(anomalyId) {
    screenshotList = [];
    screenshotIndex = -1;

    if (!reportData || !reportData.anomalies) return;

    // 현재 anomaly의 리테일러 찾기
    const current = reportData.anomalies.find(a => a.id === anomalyId);
    if (!current) return;

    // 같은 리테일러의 스크린샷 있는 항목만
    reportData.anomalies.forEach(a => {
        if (a.retailer === current.retailer && a.screenshot_id) {
            screenshotList.push({ fileId: a.screenshot_id, anomalyId: a.id });
        }
    });

    screenshotIndex = screenshotList.findIndex(s => s.anomalyId === anomalyId);
}

function updateScreenshotNav() {
    const prevBtn = document.getElementById('screenshotPrev');
    const nextBtn = document.getElementById('screenshotNext');
    const counter = document.getElementById('screenshotCounter');

    if (screenshotList.length <= 1) {
        prevBtn.style.display = 'none';
        nextBtn.style.display = 'none';
        counter.textContent = '';
    } else {
        prevBtn.style.display = 'flex';
        nextBtn.style.display = 'flex';
        prevBtn.disabled = screenshotIndex <= 0;
        nextBtn.disabled = screenshotIndex >= screenshotList.length - 1;
        counter.textContent = `${screenshotIndex + 1} / ${screenshotList.length}`;
    }
}

async function navigateScreenshot(direction) {
    const newIndex = screenshotIndex + direction;
    if (newIndex < 0 || newIndex >= screenshotList.length) return;
    if (!await confirmDiscardScreenshotCause()) return;
    screenshotIndex = newIndex;
    const item = screenshotList[screenshotIndex];
    currentScreenshotAnomalyId = item.anomalyId;
    loadScreenshotImage(item.fileId, item.anomalyId);
    updateScreenshotNav();
}

async function showScreenshot(fileId, anomalyId) {
    const modal = document.getElementById('screenshotModal');

    buildScreenshotList(anomalyId);
    currentScreenshotAnomalyId = anomalyId || null;

    modal.classList.add('show');
    loadScreenshotImage(fileId, anomalyId);
    updateScreenshotNav();
}

async function loadScreenshotImage(fileId, anomalyId) {
    const body = document.getElementById('screenshotBody');
    const title = document.getElementById('screenshotTitle');
    const deleteBtn = document.getElementById('screenshotDeleteBtn');

    deleteBtn.style.display = (!isClosed && anomalyId) ? 'inline-block' : 'none';
    body.innerHTML = '<div class="screenshot-loading">로딩 중...</div>';
    renderScreenshotCauseEditor(anomalyId);

    try {
        const response = await fetch(`/ds/layer4/api/screenshot/?file_id=${fileId}`);
        const data = await response.json();

        if (data.success) {
            title.textContent = data.file_name || '스크린샷';
            title.title = data.file_name || '스크린샷';
            body.innerHTML = `<img src="${safeUrl(data.url)}" alt="스크린샷" style="max-width:100%; max-height:80vh;">`;
        } else {
            body.innerHTML = `<div class="screenshot-loading" style="color: #dc2626;">이미지를 불러올 수 없습니다: ${esc(data.error)}</div>`;
        }
    } catch (error) {
        body.innerHTML = '<div class="screenshot-loading" style="color: #dc2626;">이미지 로드 실패</div>';
        console.error('Screenshot error:', error);
    }
}

function deleteScreenshot() {
    if (!currentScreenshotAnomalyId) return;
    if (screenshotCauseSaving) {
        showToast('원인을 저장하고 있습니다. 잠시만 기다려 주세요.', 'info');
        return;
    }

    var existing = document.getElementById('screenshotConfirmOverlay');
    if (existing) existing.remove();

    var overlay = document.createElement('div');
    overlay.id = 'screenshotConfirmOverlay';
    overlay.style.cssText = 'position:fixed; inset:0; background:rgba(0,0,0,0.45); z-index:10003; display:flex; justify-content:center; align-items:center;';
    overlay.innerHTML =
        '<div style="background:#fff; border-radius:12px; padding:28px 32px 20px; min-width:320px; max-width:400px; box-shadow:0 12px 40px rgba(0,0,0,0.25); text-align:center;">' +
            '<div style="margin-bottom:12px;"><svg viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2" width="40" height="40"><path d="M12 9v2m0 4h.01M5.07 19H19a2 2 0 0 0 1.75-2.96L13.74 4a2 2 0 0 0-3.5 0L3.32 16.04A2 2 0 0 0 5.07 19z"/></svg></div>' +
            '<div style="font-size:15px; font-weight:500; color:#1a1a1a; line-height:1.5; margin-bottom:6px;">스크린샷을 삭제하시겠습니까?</div>' +
            '<div style="font-size:13px; color:#6b7280; margin-bottom:20px;">S3 파일도 함께 삭제됩니다.</div>' +
            '<div style="display:flex; gap:10px; justify-content:center;">' +
                '<button id="ssDeleteOk" style="padding:9px 28px; border-radius:8px; font-size:14px; font-weight:600; border:none; cursor:pointer; background:#ef4444; color:#fff;">삭제</button>' +
                '<button id="ssDeleteCancel" style="padding:9px 28px; border-radius:8px; font-size:14px; font-weight:600; border:none; cursor:pointer; background:#f3f4f6; color:#1a1a1a;">취소</button>' +
            '</div>' +
        '</div>';
    document.body.appendChild(overlay);

    overlay.onclick = function(e) { if (e.target === overlay) overlay.remove(); };
    document.getElementById('ssDeleteCancel').onclick = function() { overlay.remove(); };
    document.getElementById('ssDeleteOk').onclick = async function() {
        overlay.remove();
        try {
            const response = await fetch('/ds/layer4/api/screenshot-delete/', {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken()},
                body: JSON.stringify({anomaly_ids: [currentScreenshotAnomalyId]})
            });
            const data = await response.json();

            if (data.success) {
                hideScreenshotModal();
                showToast('스크린샷이 삭제되었습니다.', 'success');
                loadReportList();
            } else {
                showToast(data.error || '삭제 실패', 'error');
            }
        } catch (error) {
            showToast('삭제 중 오류가 발생했습니다.', 'error');
        }
    };
}

function hideScreenshotModal() {
    document.getElementById('screenshotModal').classList.remove('show');
    screenshotCauseBaseline = '';
    screenshotCauseDirty = false;
}

async function closeScreenshotModal(event) {
    if (event && event.target !== event.currentTarget) return;
    if (!await confirmDiscardScreenshotCause()) return;
    hideScreenshotModal();
}

// 스크린샷 수동 업로드
var uploadTargetAnomalyId = null;

function triggerUpload(anomalyId) {
    uploadTargetAnomalyId = anomalyId;
    document.getElementById('screenshotFileInput').click();
}

async function handleScreenshotUpload(input) {
    if (!input.files.length || !uploadTargetAnomalyId) return;
    var file = input.files[0];
    var anomalyId = uploadTargetAnomalyId;
    uploadTargetAnomalyId = null;

    if (file.size > 10 * 1024 * 1024) {
        showToast('파일 크기가 10MB를 초과합니다.', 'error');
        input.value = '';
        return;
    }

    var confirmed = await showConfirm(`스크린샷을 업로드하시겠습니까?\n\n파일: ${file.name}`, 'info');
    if (!confirmed) {
        input.value = '';
        return;
    }

    showToast('스크린샷 업로드 중...', 'info');

    var formData = new FormData();
    formData.append('file', file);
    formData.append('anomaly_id', anomalyId);

    fetch('/ds/layer4/api/screenshot-upload/', {
        method: 'POST',
        headers: { 'X-CSRFToken': getCsrfToken() },
        body: formData
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success) {
            showToast('스크린샷이 업로드되었습니다.', 'success');
            loadReportList();
        } else {
            showToast('업로드 실패: ' + (data.error || '알 수 없는 오류'), 'error');
        }
    })
    .catch(function(err) {
        showToast('업로드 중 오류가 발생했습니다.', 'error');
    });

    input.value = '';
}

// 스크린샷 캡쳐 버튼 렌더링 (아이콘만)
function renderCaptureButton(report) {
    const hasError = (report.anomaly_total || 0) > 0;
    const hasScreenshot = report.has_screenshot || false;
    const allCaptured = report.all_screenshots_captured || false;

    // 이상치가 있고, instance_id가 있고, 아직 모든 스크린샷이 캡쳐되지 않은 경우만 활성화
    // + 마감되지 않은 날짜만 캡쳐 가능
    const screenshotEnabled = hasError && hasScreenshot && !allCaptured && !isClosed;

    if (allCaptured) {
        return AppButton.iconHtml('check', null, { size: 'sm', bg: 'transparent', color: '#10b981', disabled: true, cls: 'completed', title: '캡쳐 완료' });
    } else if (screenshotEnabled) {
        return AppButton.iconHtml('camera', `captureScreenshot('${report.retailer}')`, { size: 'sm', bg: '#8b5cf6', title: report.retailer + ' 스크린샷 캡쳐', data: { retailer: report.retailer } });
    } else {
        return AppButton.iconHtml('minus', null, { size: 'sm', bg: 'transparent', color: '#9ca3af', disabled: true, title: '캡쳐 불가' });
    }
}

// 페이지 로드 시 running 캡쳐 자동 폴링 재개
function checkRunningCaptures(data) {
    if (!data.daily_reports) return;
    const date = document.getElementById('targetDate').value;

    // 기존 폴링 모두 정리
    Object.keys(capturePollers).forEach(r => stopCapturePolling(r));

    for (const report of data.daily_reports) {
        if (report.capture_running && !report.all_screenshots_captured) {
            // 버튼을 로딩 상태로 변경
            const btn = document.querySelector(`button.app-icon-btn-solid[data-retailer="${report.retailer}"]`);
            AppButton.setLoading(btn);
            // 폴링 시작 (팝업 없이)
            startCapturePolling(report.retailer, date, true);
        }
    }
}

// 스크린샷 캡쳐 폴링 관리
const capturePollers = {}; // { retailer: { pollId, timeoutId } }

function stopCapturePolling(retailer) {
    if (capturePollers[retailer]) {
        clearInterval(capturePollers[retailer].pollId);
        clearTimeout(capturePollers[retailer].timeoutId);
        delete capturePollers[retailer];
    }
}

// 캡쳐 진행 팝업
function showCaptureProgress(retailer) {
    var existing = document.getElementById('captureProgressOverlay');
    if (existing) existing.remove();

    var overlay = document.createElement('div');
    overlay.id = 'captureProgressOverlay';
    overlay.style.cssText = 'position:fixed; inset:0; background:rgba(0,0,0,0.45); z-index:10002; display:flex; justify-content:center; align-items:center;';
    overlay.innerHTML =
        '<div style="background:#fff; border-radius:12px; padding:28px 32px 20px; min-width:340px; max-width:440px; box-shadow:0 12px 40px rgba(0,0,0,0.25); text-align:center;">' +
            '<div style="margin-bottom:16px;">' +
                '<svg class="capture-spinner" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2">' +
                    '<circle cx="12" cy="12" r="10" stroke-dasharray="30" stroke-dashoffset="10"/>' +
                '</svg>' +
            '</div>' +
            '<div style="font-size:16px; font-weight:600; color:#1a1a1a; margin-bottom:8px;">' + retailer + ' 캡쳐 진행 중</div>' +
            '<div id="captureProgressStatus" style="font-size:20px; font-weight:700; color:#2563eb; margin-bottom:12px;">확인 중...</div>' +
            '<div style="font-size:13px; color:#6b7280; margin-bottom:20px;">캡쳐 프로그램은 약 1~10분 정도 소요됩니다.</div>' +
            '<button id="captureProgressClose" style="padding:9px 28px; border-radius:8px; font-size:14px; font-weight:600; border:none; cursor:pointer; background:#f3f4f6; color:#1a1a1a; transition:opacity 0.15s;">닫기</button>' +
        '</div>';
    document.body.appendChild(overlay);

    document.getElementById('captureProgressClose').addEventListener('click', function() {
        overlay.remove();
    });
    overlay.addEventListener('click', function(e) {
        if (e.target === overlay) overlay.remove();
    });
}

function updateCaptureProgress(captured, total) {
    var el = document.getElementById('captureProgressStatus');
    if (el) el.textContent = captured + ' / ' + total + ' 완료';
}

function closeCaptureProgress(success, retailer, captured, total) {
    var overlay = document.getElementById('captureProgressOverlay');
    if (!overlay) return;

    // 아이콘과 텍스트를 완료/타임아웃으로 변경
    var box = overlay.querySelector('div > div');
    if (success) {
        overlay.querySelector('svg').outerHTML =
            '<svg class="capture-spinner" style="animation:none" viewBox="0 0 24 24" fill="none" stroke="#22c55e" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>';
        overlay.querySelector('div > div:nth-child(2)').textContent = retailer + ' 캡쳐 완료';
        overlay.querySelector('div > div:nth-child(2)').style.color = '#22c55e';
        document.getElementById('captureProgressStatus').textContent = captured + ' / ' + total + ' 완료';
        document.getElementById('captureProgressStatus').style.color = '#22c55e';
    } else {
        overlay.querySelector('svg').outerHTML =
            '<svg class="capture-spinner" style="animation:none" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>';
        overlay.querySelector('div > div:nth-child(2)').textContent = retailer + ' 캡쳐 시간 초과';
        overlay.querySelector('div > div:nth-child(2)').style.color = '#ef4444';
        document.getElementById('captureProgressStatus').textContent = captured + ' / ' + total + ' 완료';
        document.getElementById('captureProgressStatus').style.color = '#ef4444';
    }
    // 안내 메시지 숨김
    var hint = overlay.querySelector('div > div:nth-child(4)');
    if (hint) hint.style.display = 'none';
}

function startCapturePolling(retailer, date, silent) {
    // 이미 폴링 중이면 중복 방지
    stopCapturePolling(retailer);

    const btn = document.querySelector(`button.app-icon-btn-solid[data-retailer="${retailer}"]`);

    // 진행 팝업 표시 (silent=true면 팝업 없이 폴링만)
    if (!silent) {
        showCaptureProgress(retailer);
    }

    const pollId = setInterval(async () => {
        try {
            const res = await fetch(`/ds/layer4/api/screenshot-status/?retailer=${retailer}&crawl_date=${date}`);
            const data = await res.json();

            // 팝업 진행상황 업데이트
            if (!silent) {
                updateCaptureProgress(data.captured, data.total);
            }

            if (data.completed) {
                stopCapturePolling(retailer);
                if (!silent) {
                    closeCaptureProgress(true, retailer, data.captured, data.total);
                } else {
                    showToast(`${retailer} 캡쳐 완료 (${data.captured}/${data.total})`, 'success');
                }
                // 버튼을 완료 상태로 변경
                if (btn) {
                    btn.classList.add('completed');
                    btn.onclick = null;
                    AppButton.clearLoading(btn, 'check', { disabled: true, bg: 'transparent', color: '#10b981', title: '캡쳐 완료' });
                }
                // 목록 갱신
                loadReportList();
            }
        } catch (e) {
            // 폴링 실패는 무시 (다음 주기에 재시도)
        }
    }, 10000);

    // 10분 후 자동 중지
    const timeoutId = setTimeout(() => {
        clearInterval(pollId);
        const poller = capturePollers[retailer];
        delete capturePollers[retailer];
        if (!silent) {
            closeCaptureProgress(false, retailer, '?', '?');
        }
        // 버튼 복구
        if (btn) {
            AppButton.clearLoading(btn, 'camera', { bg: '#8b5cf6', color: '#fff' });
        }
    }, 20 * 60 * 1000);

    capturePollers[retailer] = { pollId, timeoutId };
}

// 스크린샷 캡쳐 함수
async function captureScreenshot(retailer) {
    // 확인 팝업
    const confirmed = await showConfirm(`${retailer} 캡쳐 프로그램을 실행하시겠습니까?`, 'info');
    if (!confirmed) {
        return;
    }

    const date = document.getElementById('targetDate').value;

    // 버튼 찾기
    const btn = document.querySelector(`button.app-icon-btn-solid[data-retailer="${retailer}"]`);

    AppButton.setLoading(btn);

    try {
        const response = await fetch('/ds/layer4/api/screenshot-capture/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({
                retailer: retailer,
                crawl_date: date
            })
        });

        const result = await response.json();

        if (result.success) {
            // 폴링 시작 (30초 간격, 10분 타임아웃) + 진행 팝업 표시
            startCapturePolling(retailer, date);
        } else {
            showToast('캡쳐 실패: ' + result.error, 'error');
            if (btn) {
                AppButton.clearLoading(btn, 'camera', { bg: '#8b5cf6', color: '#fff' });
            }
        }
    } catch (error) {
        showToast('캡쳐 요청 실패: ' + error, 'error');
        if (btn) {
            AppButton.clearLoading(btn, 'camera', { bg: '#8b5cf6', color: '#fff' });
        }
    }
}

// ESC / 좌우 화살표 키
document.addEventListener('keydown', async function(e) {
    const screenshotModal = document.getElementById('screenshotModal');
    if (screenshotModal.classList.contains('show')) {
        const tagName = String(e.target && e.target.tagName || '').toLowerCase();
        const isEditing = ['input', 'select', 'textarea'].includes(tagName);
        if (!isEditing && e.key === 'ArrowLeft') {
            e.preventDefault();
            await navigateScreenshot(-1);
            return;
        }
        if (!isEditing && e.key === 'ArrowRight') {
            e.preventDefault();
            await navigateScreenshot(1);
            return;
        }
    }
    if (e.key === 'Escape') {
        const detailModal = document.getElementById('detailModalOverlay');
        if (screenshotModal.classList.contains('show')) {
            await closeScreenshotModal();
            return;
        }
        if (detailModal.classList.contains('show')) {
            detailModal.classList.remove('show');
        }
    }
});
