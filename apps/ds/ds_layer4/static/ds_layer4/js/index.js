/* ================================================================
 *  DS Layer4 – index.js
 *  초기화, FilterBar, 뷰 토글, 날짜 이동, 유틸리티, 데이터 로드
 * ================================================================ */

const currentUserId = document.getElementById('app-data').dataset.userId;
let reportData = null;
let isClosed = false;
let currentReportView = 'status'; // 'status' or 'detail'
let expandedRetailers = new Set(); // 펼쳐진 아코디언 리테일러 추적
let causeOptions = {}; // 리테일러별 원인 옵션
const INTERNAL_CAUSE_MARKERS = new Set(['crawler_null_capture']);

function normalizeReportCause(value) {
    const cause = String(value || '').trim();
    return INTERNAL_CAUSE_MARKERS.has(cause.toLowerCase()) ? '' : cause;
}

// 리테일러별 원인 옵션 드롭다운 HTML 생성
function getCauseOptionsHtml(retailer, selectedValue) {
    const options = causeOptions[retailer] || [];
    const selected = normalizeReportCause(selectedValue);
    let html = '<option value="">선택</option>';
    options.forEach(opt => {
        const safeOption = esc(opt);
        html += `<option value="${safeOption}" ${selected === opt ? 'selected' : ''}>${safeOption}</option>`;
    });
    if (selected && !options.includes(selected)) {
        const safeSelected = esc(selected);
        html += `<option value="${safeSelected}" selected>기타: ${safeSelected}</option>`;
    }
    return html;
}

// ── FilterBar 초기화 ──────────────────────────────
const reportBar = new FilterBar('#reportControlsBar', {
    fit: true,
    controls: [
        { type: 'date', key: 'targetDate', label: '수집일자' },
        { type: 'button', label: '조회', style: 'primary', onClick: () => loadReportData() },
        { type: 'button', label: '전날', style: 'cancel', color: '#1a365d', border: '1px solid #1a365d', onClick: () => setPrevDay('targetDate', loadReportList) },
        { type: 'button', label: '다음날', style: 'cancel', color: '#1a365d', border: '1px solid #1a365d', onClick: () => setNextDay('targetDate', loadReportList) },
    ]
}).render();

// ── 뷰 토글 초기화 ──────────────────────────────
(function() {
    const wrapper = document.getElementById('reportViewToggle');
    const options = ['현황', '파일', '상세'];
    const views = ['status', 'file', 'detail'];
    options.forEach((opt, i) => {
        const btn = document.createElement('button');
        btn.textContent = opt;
        btn.style.minWidth = '80px';
        btn.className = 'app-btn app-btn-md ' + (i === 0 ? 'app-btn-primary' : 'app-btn-cancel');
        btn.addEventListener('click', () => {
            wrapper.querySelectorAll('button').forEach(b => {
                b.className = 'app-btn app-btn-md app-btn-cancel';
            });
            btn.className = 'app-btn app-btn-md app-btn-primary';
            setReportView(views[i]);
        });
        wrapper.appendChild(btn);
    });
})();

// 페이지 로드 시 초기화
document.addEventListener('DOMContentLoaded', () => {
    // 모달 생성
    AppModal.create('fileHistory', { style: 'wide' });

    // 저장된 날짜 또는 어제 날짜로 초기화 (URL파라미터 우선)
    document.getElementById('targetDate').value = getPersistedDate();
    loadReportList();
});

// 파일 크기 포맷 (bytes -> KB/MB)
// formatFileSize → format.js 공통
// setPrevDay, setNextDay → date.js 공통

// formatLocalDate는 format.js에서 로드

async function loadReportList() {
    expandedRetailers.clear();
    let date = document.getElementById('targetDate').value;
    if (!validateQueryDate(date, 'targetDate')) {
        date = document.getElementById('targetDate').value; // 보정된 날짜
    }
    setPersistedDate(date); // 날짜 저장
    const content = document.getElementById('reportContent');

    content.innerHTML = '<div class="loading-spinner"><div class="spinner"></div></div>';

    try {
        const response = await fetch(`/ds/layer4/api/report-list/?date=${date}&view=${currentReportView}`);
        const data = await response.json();

        if (!data.success) {
            throw new Error(data.error || '데이터 로드 실패');
        }

        reportData = data;
        isClosed = data.is_closed;
        causeOptions = data.cause_options || {};

        updateSummary(data);
        updateCloseButton(data);
        renderReportTable(data);

        // running 캡쳐가 있으면 자동 폴링 재개
        checkRunningCaptures(data);

    } catch (error) {
        console.error('Error loading report list:', error);
        content.innerHTML = `
            <div class="empty-state">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"/>
                    <line x1="12" y1="8" x2="12" y2="12"/>
                    <line x1="12" y1="16" x2="12.01" y2="16"/>
                </svg>
                <h3>오류 발생</h3>
                <p>${esc(error.message)}</p>
            </div>
        `;
    }
}

function updateSummary(data) {
    document.getElementById('totalRetailers').textContent = data.daily_reports.length;
    document.getElementById('totalAnomalies').textContent = data.total_anomalies;
    document.getElementById('screenshotStatus').textContent = data.captured_screenshots || 0;
    document.getElementById('filledCause').textContent = data.filled_cause || 0;
    document.getElementById('reportCount').textContent = `${data.daily_reports.length}개`;
}

function updateCloseButton(data) {
    const closeBtn = document.getElementById('closeBtn');
    const closeBtnText = document.getElementById('closeBtnText');
    const cancelCloseBtn = document.getElementById('cancelCloseBtn');
    const saveFileInfoBtn = document.getElementById('saveFileInfoBtn');
    const saveFileInfoBtnText = document.getElementById('saveFileInfoBtnText');
    const banner = document.getElementById('closedBanner');
    const bannerText = document.getElementById('closedBannerText');

    // 전체 리테일러 수 (API 응답에 추가되어야 함, 없으면 기본값 사용)
    const totalRetailers = data.total_retailers || 0;
    const savedCount = data.daily_reports.length;
    const allSaved = totalRetailers > 0 && savedCount >= totalRetailers;

    if (data.is_closed) {
        // 마감된 상태: 저장 버튼들 숨기고, 마감 완료 + 마감 취소 버튼 표시
        saveFileInfoBtn.style.display = 'none';
        closeBtn.disabled = true;
        closeBtn.style.background = '#7e6b9b';
        closeBtn.style.borderColor = '#7e6b9b';
        closeBtn.style.opacity = '1';
        closeBtnText.textContent = '마감 완료';
        cancelCloseBtn.style.display = 'inline-flex';
        banner.classList.remove('hidden');
        bannerText.textContent = `이 날짜는 ${data.closed_at}에 ${data.closed_id}님이 마감했습니다.`;
    } else {
        // 마감되지 않은 상태: 모든 버튼 표시, 마감 취소 숨김
        saveFileInfoBtn.style.display = 'inline-flex';
        banner.classList.add('hidden');
        closeBtn.style.background = '#7e6b9b';
        closeBtn.style.borderColor = '#7e6b9b';
        cancelCloseBtn.style.display = 'none';

        // 파일용량 저장 버튼: 마감 전까지는 계속 수정(저장)될 수 있으므로 disabled 처리 해제
        const fileSavedCount = data.daily_reports.filter(r => r.file_size > 0).length;
        saveFileInfoBtn.disabled = false;
        if (allSaved && fileSavedCount >= totalRetailers) {
            saveFileInfoBtnText.textContent = `파일용량 저장 (${fileSavedCount}/${totalRetailers})`;
        } else {
            saveFileInfoBtnText.textContent = '파일용량 저장';
        }

        // 마감 버튼: 항상 활성화 (클릭 시 조건 체크)
        closeBtn.disabled = false;
        closeBtnText.textContent = '마감';
    }
}

// 뷰 전환
function setReportView(view) {
    currentReportView = view;
    const reportTableArea = document.getElementById('reportTableArea');
    const fileSection = document.getElementById('fileTabSection');

    if (view === 'file') {
        reportTableArea.style.display = 'none';
        fileSection.style.display = 'block';
        loadFileTab();
    } else {
        reportTableArea.style.display = 'block';
        fileSection.style.display = 'none';
        loadReportList();
    }
}

// loadReportData alias (조회 버튼에서 사용)
function loadReportData() {
    loadReportList();
}
