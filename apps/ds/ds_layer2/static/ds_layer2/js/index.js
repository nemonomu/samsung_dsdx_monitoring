let statsData = null;
let currentBatchView = 'final'; // 'final' or 'all'
let reportStatus = { is_closed: false, saved_retailers: {} }; // 보고서 상태
const currentUserId = document.getElementById('app-data').dataset.userId;

// ── FilterBar 초기화 ──────────────────────────────
const layer2Bar = new FilterBar('#layer2FilterBar', {
    sticky: true,
    controls: [
        { type: 'date', key: 'targetDate', label: '조회 날짜' },
        { type: 'button', label: '조회', style: 'primary', onClick: () => loadData() },
        { type: 'button', label: '전날', style: 'cancel', color: '#1a365d', border: '1px solid #1a365d', onClick: () => setPrevDay('targetDate', loadData) },
        { type: 'button', label: '다음날', style: 'cancel', color: '#1a365d', border: '1px solid #1a365d', onClick: () => setNextDay('targetDate', loadData) },
    ],
    right: [
        { type: 'toggle', key: 'batchView', options: ['최종', '전체'], btnWidth: 80, onClick: (label, index) => {
            currentBatchView = index === 0 ? 'final' : 'all';
            loadData();
        }},
    ]
}).render();

document.addEventListener('DOMContentLoaded', function() {
    // 저장된 날짜 또는 오늘 날짜로 초기화
    document.getElementById('targetDate').value = getPersistedDate();
    loadData();
});

// 보고서 상태 조회
async function loadReportStatus() {
    const date = document.getElementById('targetDate').value;
    try {
        const response = await fetch(`/ds/layer2/api/status/?date=${date}`);
        const data = await response.json();
        if (data.success) {
            reportStatus = data;
            updateClosedBanner();
        }
    } catch (error) {
        console.error('Error loading report status:', error);
    }
}

// 마감 배너 업데이트
function updateClosedBanner() {
    const banner = document.getElementById('closedBanner');
    if (reportStatus.is_closed) {
        banner.classList.remove('hidden');
    } else {
        banner.classList.add('hidden');
    }
}

// 리테일러 저장 여부 확인
function isRetailerSaved(retailer) {
    return reportStatus.saved_retailers && reportStatus.saved_retailers[retailer];
}

async function loadData() {
    let date = document.getElementById('targetDate').value;
    if (!validateQueryDate(date, 'targetDate')) {
        date = document.getElementById('targetDate').value; // 보정된 날짜
    }
    setPersistedDate(date); // 날짜 저장
    document.getElementById('nullTableLoading').classList.remove('hidden');
    document.getElementById('nullTableContent').innerHTML = '';

    try {
        // 보고서 상태와 데이터를 병렬로 로드
        const [statsResponse, statusResponse] = await Promise.all([
            fetch(`/ds/layer2/api/stats/?date=${date}&batch_view=${currentBatchView}`),
            fetch(`/ds/layer2/api/status/?date=${date}`)
        ]);

        statsData = await statsResponse.json();
        const statusData = await statusResponse.json();

        if (statusData.success) {
            reportStatus = statusData;
            updateClosedBanner();
        }

        updateSummary(statsData);
        renderNullTable(statsData);
    } catch (error) {
        console.error('Error loading data:', error);
        document.getElementById('nullTableContent').innerHTML = '<div class="loading">데이터 로드 실패</div>';
    }

    document.getElementById('nullTableLoading').classList.add('hidden');
}

function updateSummary(data) {
    if (data.summary) {
        document.getElementById('totalTables').textContent = data.summary.total_tables || 0;
        document.getElementById('totalRecords').textContent = (data.summary.total_records || 0).toLocaleString();
        document.getElementById('totalError').textContent = (data.summary.total_error || 0).toLocaleString();

        const status = data.summary.status || 'pending';
        const statusEl = document.getElementById('overallStatus');
        statusEl.textContent = getStatusLabel(status);
        statusEl.className = 'summary-value ' + status;
    }
}
