/** Server-owned session deadline. Status checks never extend the session. */
(function() {
    const countdownEl = document.getElementById('session-countdown');
    const timerContainer = document.querySelector('.session-timer');
    if (!countdownEl || !timerContainer) return;

    const WARNING_THRESHOLD = 10 * 60;
    const CRITICAL_THRESHOLD = 5 * 60;
    const RETRY_DELAY = 30 * 1000;
    const SYNC_INTERVAL = 5 * 60 * 1000;
    let expiresAt = null;
    let serverOffset = 0;
    let cookieName = null;
    let lastCookie = null;
    let nextSyncAt = 0;
    let syncing = false;
    let expired = false;

    function readExpiryCookie(cookies = document.cookie) {
        const prefix = cookieName + '=';
        const cookie = cookies.split(';').map(value => value.trim())
            .find(value => value.startsWith(prefix));
        return cookie ? cookie.slice(prefix.length) : null;
    }

    function formatTime(seconds) {
        return [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60]
            .map(value => String(value).padStart(2, '0')).join(':');
    }

    function showExpired() {
        if (expired) return;
        expired = true;
        countdownEl.textContent = '00:00:00';
        timerContainer.classList.add('critical');
        showConfirm('세션이 만료되었습니다. 다시 로그인해주세요.', 'warning').then(function() {
            // Do not call logout: another tab could have logged in meanwhile.
            window.location.href = timerContainer.dataset.loginUrl;
        });
    }

    async function syncStatus() {
        if (syncing || expired) return;
        syncing = true;
        nextSyncAt = Date.now() + RETRY_DELAY;
        const startedAt = Date.now();
        const cookiesAtStart = document.cookie;
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 10000);
        try {
            const response = await fetch(timerContainer.dataset.statusUrl, {
                credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
            });
            if (response.status === 401) {
                showExpired();
                return;
            }
            if (!response.ok) throw new Error('Session status unavailable');
            const data = await response.json();
            if (!data.authenticated || !Number.isFinite(data.expiresAt)
                || !Number.isFinite(data.serverTime) || !data.expiryCookie) {
                throw new Error('Invalid session status');
            }
            // Calibrate against server time even when the user's clock differs.
            // Counting the full round trip is conservative (never adds lifetime).
            serverOffset = data.serverTime - startedAt;
            expiresAt = data.expiresAt;
            cookieName = data.expiryCookie;
            lastCookie = readExpiryCookie(cookiesAtStart);
            nextSyncAt = Date.now() + Math.max(1000,
                Math.min(SYNC_INTERVAL, data.expiresAt - data.serverTime));
            countdownEl.removeAttribute('title');
        } catch (error) {
            countdownEl.title = '서버 연결 후 세션 만료 시간을 다시 확인합니다.';
        } finally {
            clearTimeout(timeout);
            syncing = false;
            renderTimer();
        }
    }

    function renderTimer() {
        if (expired) return;
        if (cookieName) {
            // Cookies are shared by tabs and updated by normal page/API responses.
            const cookie = readExpiryCookie();
            if (cookie !== lastCookie) {
                lastCookie = cookie;
                if (cookie && Number.isFinite(Number(cookie)) && Number(cookie) > 0) {
                    expiresAt = Number(cookie);
                    nextSyncAt = Math.min(nextSyncAt, Date.now() + Math.max(1000,
                        expiresAt - Date.now() - serverOffset));
                } else {
                    nextSyncAt = 0;
                }
            }
        }
        const seconds = expiresAt === null ? null
            : Math.max(0, Math.ceil((expiresAt - Date.now() - serverOffset) / 1000));
        countdownEl.textContent = seconds === null ? '--:--:--'
            : seconds === 0 ? '확인 중' : formatTime(seconds);
        timerContainer.classList.toggle('warning', seconds !== null && seconds > CRITICAL_THRESHOLD && seconds <= WARNING_THRESHOLD);
        timerContainer.classList.toggle('critical', seconds !== null && seconds <= CRITICAL_THRESHOLD);
        // Confirm expiry on the server; a failed network request must not log out.
        if (Date.now() >= nextSyncAt && !document.hidden) syncStatus();
    }

    function resume() {
        if (!document.hidden) {
            nextSyncAt = 0;
            renderTimer();
        }
    }
    document.addEventListener('visibilitychange', resume);
    window.addEventListener('pageshow', resume);
    window.addEventListener('focus', resume);
    window.addEventListener('online', resume);
    setInterval(renderTimer, 1000);
    syncStatus();
})();
