// Current counts and historical rules travel together; never mix request dates.
(function () {
    const countries = {retail:'SEA', seda_retail:'SEDA', siel_retail:'SIEL', seg_retail:'SEG',
        sem_retail:'SEM', tse_retail:'TSE', seib_retail:'SEIB', seuk_retail:'SEUK'};
    const currentDay = () => getLayer1SeoulDate(0);
    const clone = value => JSON.parse(JSON.stringify(value));
    const isInspecting = () => Boolean(document.querySelector(
        'dialog[open], .modal.show, .modal-overlay.show, .l1-batch-toggle[aria-expanded="true"]'));

    function poll(context, receive, afterSweep) {
        let generation = 0, timer = null, running = false, stopped = false;
        let signature = afterSweep ? JSON.stringify(context()) : '';
        let startedAt = afterSweep ? Date.now() : -Infinity;
        const controllers = new Set();
        const schedule = (delay = 60000) => {
            clearTimeout(timer);
            if (!stopped && context()?.date === currentDay()) timer = setTimeout(() => refresh(), delay);
        };
        async function refresh(force = false) {
            if (stopped) return;
            if (running && afterSweep && !force) return;
            const scope = context();
            const key = JSON.stringify(scope);
            if (key === signature && !force) {
                if (running) return;
                const remaining = afterSweep ? 60000 - (Date.now() - startedAt) : 0;
                if (remaining > 0) {
                    schedule(remaining);
                    return;
                }
            }
            if (document.hidden || !scope || (!force && scope.date !== currentDay()) || isInspecting()) {
                schedule(); return;
            }
            const queue = [
                ...[...new Set(scope.countries)].map(country => ({country})),
                ...(scope.checkTypes || []).map(checkType => ({checkType}))
            ];
            if (!queue.length) { schedule(); return; }
            clearTimeout(timer);
            const request = ++generation;
            const stillSelected = () => afterSweep ? context()?.date === scope.date : JSON.stringify(context()) === key;
            signature = key;
            startedAt = Date.now();
            controllers.forEach(controller => controller.abort());
            controllers.clear();
            running = true;
            const updates = [];
            async function worker() {
                while (queue.length && request === generation) {
                    const {country, checkType} = queue.shift(), controller = new AbortController();
                    controllers.add(controller);
                    const timeout = setTimeout(() => controller.abort(), 30000);
                    let snapshot;
                    try {
                        const path = country ? 'collection-current' : 'stats';
                        const params = country ? {country, date:scope.date}
                            : {check_type:checkType, date:scope.date, dashboard:'1'};
                        const response = await fetch('/dx/layer1/api/' + path + '/?' + new URLSearchParams(params),
                            {signal:controller.signal, cache:'no-store'});
                        const payload = await response.json();
                        if (country) {
                            snapshot = payload.snapshots?.find(item => item.country === country);
                            if (!response.ok || payload.policy_version !== 4 || payload.inspection_date !== scope.date
                                || !snapshot?.live || !snapshot.available || snapshot.inspection_date !== scope.date) throw new Error('Unavailable');
                        } else {
                            const check = payload.checks?.find(item => item.check_type === checkType);
                            if (!response.ok || payload.error || payload.target_date !== scope.date || !check) throw new Error('Unavailable');
                            snapshot = {checkType, check};
                        }
                    } catch (_) {
                        snapshot = country ? {country, inspection_date:scope.date, available:false, live:true} : {checkType};
                    } finally {
                        clearTimeout(timeout);
                        controllers.delete(controller);
                    }
                    if (request === generation && !stopped && stillSelected()) {
                        if (afterSweep) updates.push(snapshot);
                        else receive(snapshot);
                    }
                }
            }
            // Bound DB concurrency even when the page displays every country.
            await Promise.allSettled([worker(), worker(), worker()]);
            if (request === generation) {
                running = false;
                schedule();
                if (afterSweep && stillSelected() && !isInspecting()) {
                    updates.forEach(receive);
                    afterSweep();
                }
            }
        }
        const visible = () => { if (!document.hidden) refresh(); };
        const hide = () => {
            if (!document.hidden) return visible();
            ++generation; running = false;
            controllers.forEach(controller => controller.abort());
            clearTimeout(timer);
        };
        document.addEventListener('visibilitychange', hide);
        window.addEventListener('focus', visible);
        const stop = () => {
            stopped = true; ++generation; clearTimeout(timer);
            controllers.forEach(controller => controller.abort());
            document.removeEventListener('visibilitychange', hide);
            window.removeEventListener('focus', visible);
            window.removeEventListener('pagehide', stop);
        };
        window.addEventListener('pagehide', stop);
        schedule();
        return {refresh, stop};
    }

    function applyDashboard(data, snapshot) {
        const index = (data.checks || []).findIndex(check => countries[check.check_type] === snapshot.country);
        if (index < 0) return;
        const old = data.checks[index];
        if (snapshot.available && snapshot.check) {
            const fresh = clone(snapshot.check);
            const updated = {...old, ...fresh, _volumeBaseStatus:fresh.status, _liveCollection:true};
            for (const field of ['error', 'batch_count_error', 'refresh_error']) {
                if (!fresh[field]) delete updated[field];
            }
            data.checks[index] = updated;
        } else {
            old.status = old._volumeBaseStatus = 'ERROR';
            old.refresh_error = true;
            for (const cat of old.categories || []) for (const slot of cat.time_slots || [{retailers:cat.retailers}]) {
                for (const row of slot.retailers || []) {
                    row.status = row._volumeBaseStatus = 'ERROR';
                    row.refresh_error = true;
                }
            }
        }
    }

    function preserveView(render) {
        const focus = document.activeElement;
        const focusCard = focus?.closest('[data-check-type]')?.dataset.checkType;
        const focusControl = 'button, a, input, select, [tabindex]';
        const sameControl = element => element.tagName === focus.tagName && element.textContent === focus.textContent
            && ['onclick', 'href', 'aria-label', 'title', 'id'].every(name => element.getAttribute(name) === focus.getAttribute(name));
        const expanded = [...document.querySelectorAll('[id].show')].map(element => element.id);
        const scrolls = [...document.querySelectorAll('.cs-table-scroll, .retail-rank-wrap')]
            .map(element => element.scrollLeft);
        render();
        expanded.forEach(id => {
            const element = document.getElementById(id);
            element?.classList.add('show');
            element?.previousElementSibling?.querySelectorAll('.toggle-icon, .toggle-icon-small')
                .forEach(icon => icon.classList.add('expanded'));
        });
        document.querySelectorAll('.cs-table-scroll, .retail-rank-wrap').forEach((element, index) => {
            if (scrolls[index] != null) element.scrollLeft = scrolls[index];
        });
        if (focusCard && !focus.isConnected) {
            const card = [...document.querySelectorAll('[data-check-type]')]
                .find(item => item.dataset.checkType === focusCard);
            const matches = [...(card?.querySelectorAll(focusControl) || [])].filter(sameControl);
            if (matches.length === 1) matches[0].focus({preventScroll:true});
        }
    }
    L1.liveCollection = {poll, applyDashboard, preserveView, countries, isInspecting};
})();
