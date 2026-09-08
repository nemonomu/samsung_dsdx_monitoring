/**
 * [DEPRECATED] 레거시 날짜 유지 및 검증 함수
 * 주의: 이 함수들은 향후 신규 AppDatePicker 컴포넌트로 완전히 대체되고 삭제될 예정입니다.
 * 신규 메뉴 개발 시에는 하단에 새롭게 정의된 통합 AppDatePicker 클래스를 직접 사용하거나 
 * FilterBar 인스턴스를 통해 주입받아 사용하십시오.
 *
 * (의존: format.js — formatLocalDate, ui.js — showToast)
 *
 * - getPersistedDate()             : 저장된 조회 날짜 반환 (URL파라미터 > sessionStorage > 오늘)
 * - setPersistedDate(dateStr)      : 조회 날짜를 sessionStorage에 저장
 * - validateQueryDate(dateStr)     : 미래 날짜 여부 체크 (미래면 false + 토스트)
 * - date input 자동 보정            : 년도 4자리 제한, 8자리 숫자 자동 포맷
 */

const DATE_STORAGE_KEY = 'monitoring_target_date';

function getPersistedDate() {
    // 1. URL 파라미터 확인
    const urlParams = new URLSearchParams(window.location.search);
    const urlDate = urlParams.get('date');
    if (urlDate && /^\d{4}-\d{2}-\d{2}$/.test(urlDate)) {
        setPersistedDate(urlDate);
        return urlDate;
    }

    // 2. sessionStorage 확인
    const storedDate = sessionStorage.getItem(DATE_STORAGE_KEY);
    if (storedDate && /^\d{4}-\d{2}-\d{2}$/.test(storedDate)) {
        return storedDate;
    }

    // 3. 기본값: 오늘
    return formatLocalDate(new Date());
}

function setPersistedDate(dateStr) {
    if (dateStr && /^\d{4}-\d{2}-\d{2}$/.test(dateStr)) {
        sessionStorage.setItem(DATE_STORAGE_KEY, dateStr);
    }
}

function validateQueryDate(dateStr, inputId) {
    const defaultDate = getPersistedDate();

    if (!dateStr || !/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) {
        showToast('날짜 형식이 맞지 않습니다. YYYY-MM-DD 형식으로 입력하세요.', 'warning');
        if (inputId) document.getElementById(inputId).value = defaultDate;
        return false;
    }

    const today = formatLocalDate(new Date());
    if (dateStr > today) {
        showToast('오늘 이후 날짜로는 조회할 수 없습니다.', 'warning');
        if (inputId) document.getElementById(inputId).value = defaultDate;
        return false;
    }
    return true;
}

/**
 * 전날/다음날 이동 (공통)
 * @param {string} inputId - date input 엘리먼트 ID (기본: 'targetDate')
 * @param {function} callback - 날짜 변경 후 호출할 함수
 */
function setPrevDay(inputId, callback) {
    var id = inputId || 'targetDate';
    var input = document.getElementById(id);
    var parts = input.value.split('-');
    var date = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
    date.setDate(date.getDate() - 1);
    input.value = formatLocalDate(date);
    if (callback) callback();
}

function setNextDay(inputId, callback) {
    var id = inputId || 'targetDate';
    var input = document.getElementById(id);
    var parts = input.value.split('-');
    var current = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
    current.setDate(current.getDate() + 1);
    var nextStr = formatLocalDate(current);
    var todayStr = formatLocalDate(new Date());
    if (nextStr > todayStr) {
        showToast('오늘 이후 날짜로는 조회할 수 없습니다.', 'warning');
        return;
    }
    input.value = nextStr;
    if (callback) callback();
}

// 날짜 입력 필드 자동 보정 (년도 4자리 제한)
document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('input[type="date"]').forEach(input => {
        if (!input.hasAttribute('max')) {
            input.max = '9999-12-31';
        }
        input.addEventListener('input', function() {
            const raw = this.value.replace(/-/g, '');
            if (/^\d{8}$/.test(raw)) {
                this.value = `${raw.substring(0,4)}-${raw.substring(4,6)}-${raw.substring(6,8)}`;
            } else if (this.value) {
                const parts = this.value.split('-');
                if (parts[0] && parts[0].length > 4) {
                    parts[0] = parts[0].substring(0, 4);
                    this.value = parts.join('-');
                }
            }
        });
    });
});

/**
 * ============================================================
 * 신규 통합 AppDatePicker 클래스 (단일 일자 / 기간 검색)
 * ============================================================
 * 
 * 모드 (mode): 'single' 또는 'range'
 * 옵션 (options): 
 *  - maxToday: true일 경우 오늘까지로 제한
 *  - preset: 'week' (1주일 전 ~ 오늘 세팅), 'month' 등 (range 모드 전용)
 *  - 시작일/종료일 교차 검증 (range 모드 전용) 내장
 */
class AppDatePicker {
    constructor(container, options = {}) {
        this.container = typeof container === 'string' ? document.querySelector(container) : container;
        this.options = { 
            mode: 'single', // 'single' | 'range'
            maxToday: false,
            preset: null,   // 'week', 'month', etc.
            ...options 
        };
        
        this.elements = {};
        this._defaults = {};
        this.ui = null;
        
        this.render();
    }
    
    _toLocalStr(d) {
        var yyyy = d.getFullYear();
        var mm = String(d.getMonth() + 1).padStart(2, '0');
        var dd = String(d.getDate()).padStart(2, '0');
        return yyyy + '-' + mm + '-' + dd;
    }

    _getTodayStr() {
        return this._toLocalStr(new Date());
    }

    _calcPresetDateStr(presetType) {
        if (!presetType) return '';
        const d = new Date();
        if (presetType === 'week') d.setDate(d.getDate() - 6);
        else if (presetType === 'month') d.setMonth(d.getMonth() - 1);
        return this._toLocalStr(d);
    }
    
    render() {
        this.container.innerHTML = '';
        const wrapper = document.createElement('div');
        wrapper.className = 'app-datepicker-wrapper fb-date' + (this.options.mode === 'range' ? ' fb-date-range' : '');
        if (this.options.mode === 'range') {
            wrapper.style.display = 'flex';
            wrapper.style.alignItems = 'center';
            wrapper.style.gap = '4px';
        }

        if (this.options.label) {
            const label = document.createElement('label');
            label.textContent = this.options.label;
            wrapper.appendChild(label);
        }
        
        const maxLimit = this.options.maxToday ? this._getTodayStr() : (this.options.max || '');
        
        if (this.options.mode === 'single') {
            const input = document.createElement('input');
            input.type = 'date';
            const key = this.options.key || 'date';
            input.id = key;
            if (maxLimit) input.max = maxLimit;
            
            const defVal = this.options.default !== undefined ? this.options.default : (this.options.value || '');
            this._defaults[key] = defVal;
            this.elements[key] = input;
            
            wrapper.appendChild(input);
            
            if (this.options.showWeekday) {
                const weekdayEl = document.createElement('span');
                weekdayEl.className = 'fb-weekday';
                wrapper.appendChild(weekdayEl);

                const weekdays = ['일', '월', '화', '수', '목', '금', '토'];
                const updateWeekday = () => {
                    var val = input.value;
                    if (!val) { weekdayEl.textContent = ''; return; }
                    var d = new Date(val + 'T00:00:00');
                    var day = d.getDay();
                    weekdayEl.textContent = '(' + weekdays[day] + ')';
                    weekdayEl.className = 'fb-weekday' + (day === 0 || day === 6 ? ' fb-weekday-weekend' : '');
                };
                input.addEventListener('change', updateWeekday);
                updateWeekday();
            }
        } else {
            // Range mode
            const keyFrom = this.options.keyFrom || 'dateFrom';
            const keyTo = this.options.keyTo || 'dateTo';
            
            const inputFrom = document.createElement('input');
            inputFrom.type = 'date';
            inputFrom.id = keyFrom;
            if (maxLimit) inputFrom.max = maxLimit;
            wrapper.appendChild(inputFrom);

            const sep = document.createElement('span');
            sep.textContent = '~';
            sep.style.color = 'var(--text-secondary)';
            sep.style.fontWeight = 'bold';
            sep.style.margin = '0 2px';
            wrapper.appendChild(sep);

            const inputTo = document.createElement('input');
            inputTo.type = 'date';
            inputTo.id = keyTo;
            if (maxLimit) inputTo.max = maxLimit;
            wrapper.appendChild(inputTo);

            this.elements[keyFrom] = inputFrom;
            this.elements[keyTo] = inputTo;
            
            let defFrom = this.options.defaultFrom !== undefined ? this.options.defaultFrom : '';
            let defTo = this.options.defaultTo !== undefined ? this.options.defaultTo : '';
            
            if (this.options.preset === 'week') {
                if (!defTo) defTo = this._getTodayStr();
                if (!defFrom) defFrom = this._calcPresetDateStr('week');
            } else if (this.options.preset === 'month') {
                if (!defTo) defTo = this._getTodayStr();
                if (!defFrom) defFrom = this._calcPresetDateStr('month');
            }
            
            this._defaults[keyFrom] = defFrom;
            this._defaults[keyTo] = defTo;

            // Cross validation
            inputFrom.addEventListener('change', () => {
                inputTo.min = inputFrom.value;
                if (inputTo.value && inputTo.value < inputFrom.value) {
                    inputTo.value = inputFrom.value;
                    inputTo.dispatchEvent(new Event('change'));
                }
            });
            inputTo.addEventListener('change', () => {
                const maxVal = inputTo.value > maxLimit && maxLimit ? maxLimit : inputTo.value;
                inputFrom.max = maxVal;
                if (inputFrom.value && inputFrom.value > inputTo.value) {
                    inputFrom.value = inputTo.value;
                    inputFrom.dispatchEvent(new Event('change'));
                }
            });
        }
        
        this.container.appendChild(wrapper);
        this.ui = wrapper;
        this.reset();
        
        // Ensure browser 'max' limit for native auto correction
        Array.from(wrapper.querySelectorAll('input[type="date"]')).forEach(el => {
            el.addEventListener('input', function() {
                const raw = this.value.replace(/-/g, '');
                if (/^\d{8}$/.test(raw)) {
                    this.value = `${raw.substring(0,4)}-${raw.substring(4,6)}-${raw.substring(6,8)}`;
                } else if (this.value) {
                    const parts = this.value.split('-');
                    if (parts[0] && parts[0].length > 4) {
                        parts[0] = parts[0].substring(0, 4);
                        this.value = parts.join('-');
                    }
                }
            });
        });
        
        return this;
    }

    reset() {
        for (const [key, defVal] of Object.entries(this._defaults)) {
            if (this.elements[key]) {
                this.elements[key].value = defVal;
                // Dispatch event so cross-validation resets limits too
                this.elements[key].dispatchEvent(new Event('change'));
            }
        }
    }
    
    getValue(key) {
        return this.elements[key] ? this.elements[key].value : null;
    }
    
    setValue(key, val) {
        if (this.elements[key]) {
            this.elements[key].value = val;
            this.elements[key].dispatchEvent(new Event('change'));
        }
    }
}

