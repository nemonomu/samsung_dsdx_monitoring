// Current counts and historical rules travel together; never mix request dates.
(function () {
    const countries = {retail:'SEA', seda_retail:'SEDA', siel_retail:'SIEL', seg_retail:'SEG',
        sem_retail:'SEM', tse_retail:'TSE', seib_retail:'SEIB'};
    const clone = value => JSON.parse(JSON.stringify(value));
    const isInspecting = () => Boolean(document.querySelector(
        'dialog[open], .modal.show, .modal-overlay.show, .l1-batch-toggle[aria-expanded="true"]'));

    function poll(context, receive) {
        let generation = 0, timer = null, running = false, stopped = false, signature = '';
        const controllers = new Set();
        const schedule = () => {
            clearTimeout(timer);
            if (!stopped) timer = setTimeout(() => refresh(), 15000);
        };
        async function refresh(force = false) {
            if (stopped) return;
            const scope = context();
            const key = JSON.stringify(scope);
            if (running && key === signature && !force) return;
            if (document.hidden || !scope || !scope.countries.length || isInspecting()) {
                schedule(); return;
            }
            clearTimeout(timer);
            const request = ++generation;
            signature = key;
            controllers.forEach(controller => controller.abort());
            controllers.clear();
            running = true;
            const queue = [...new Set(scope.countries)];
            async function worker() {
                while (queue.length && request === generation) {
                    const country = queue.shift(), controller = new AbortController();
                    controllers.add(controller);
                    const timeout = setTimeout(() => controller.abort(), 30000);
                    let snapshot;
                    try {
                        const response = await fetch('/dx/layer1/api/collection-current/?' + new URLSearchParams({
                            country, date:scope.date}), {signal:controller.signal, cache:'no-store'});
                        const payload = await response.json();
                        snapshot = payload.snapshots?.find(item => item.country === country);
                        if (!response.ok || payload.policy_version !== 4 || payload.inspection_date !== scope.date
                            || !snapshot?.live || !snapshot.available || snapshot.inspection_date !== scope.date) throw new Error('Unavailable');
                    } catch (_) {
                        snapshot = {country, inspection_date:scope.date, available:false, live:true};
                    } finally {
                        clearTimeout(timeout);
                        controllers.delete(controller);
                    }
                    if (request === generation && !stopped && JSON.stringify(context()) === key) receive(snapshot);
                }
            }
            // Bound DB concurrency even when the page displays every country.
            await Promise.all([worker(), worker(), worker()]);
            if (request === generation) { running = false; schedule(); }
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
            data.checks[index] = {...old, ...fresh, _volumeBaseStatus:fresh.status, _liveCollection:true};
            delete data.checks[index].batch_count_error;
        } else {
            for (const cat of old.categories || []) for (const slot of cat.time_slots || [{retailers:cat.retailers}]) {
                for (const row of slot.retailers || []) {
                    row.status = row._volumeBaseStatus = 'ERROR';
                    row.refresh_error = true;
                }
            }
        }
    }

    function preserveView(render) {
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
    }
    L1.liveCollection = {poll, applyDashboard, preserveView, countries, isInspecting};
})();
