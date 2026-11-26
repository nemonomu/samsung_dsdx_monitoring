async function loadCollectionOverview() {
    const overview = document.querySelector('.dx-overview');
    const message = overview.querySelector('.dx-overview-message');
    const markets = overview.querySelector('.dx-overview-markets');
    const inspectionDate = overview.querySelector('time').dateTime;
    const formatter = new Intl.NumberFormat('ko-KR');
    const countryNames = {SEA: '미국', SEDA: '브라질'};
    const productIcons = {TV: '📺', REF: '🧊', LDY: '🧺', LDY_DRYER: '🌬️'};
    const statusLabels = {
        scheduled: '수집 예정', waiting: '수집 대기', collecting: '수집 중',
        received: '수집 확인', partial: '일부 수집', error: '조회 실패',
        uncollected: '미수집', abnormal: 'BSR 이상', rank_mismatch: '순위 이상'
    };
    const attention = new Set(['error', 'uncollected', 'abnormal', 'rank_mismatch', 'partial']);

    try {
        const response = await fetch(overview.dataset.statusUrl);
        if (!response.ok) throw new Error('Collection status unavailable');
        const {countries} = await response.json();
        if (!Array.isArray(countries)) throw new Error('Collection status missing');

        for (const {country, source_date, retailers} of countries) {
            const market = document.createElement('section');
            const identity = document.createElement('div');
            const name = document.createElement('h3');
            name.innerHTML = window.renderCountryFlagLabel(country + ' Retail');
            if (Object.hasOwn(countryNames, country)) {
                name.querySelector('.country-flag-label > span').textContent = countryNames[country];
                const region = document.createElement('p');
                region.className = 'dx-overview-date';
                region.textContent = country + ' Retail';
                identity.append(name, region);
            } else {
                identity.append(name);
            }

            if (source_date && source_date !== inspectionDate) {
                const date = document.createElement('p');
                date.className = 'dx-overview-date';
                date.textContent = '수집 대상일 ' + source_date;
                identity.append(date);
            }
            market.append(identity);

            const counts = new Map();
            let storedRows = 0;
            let countAvailable = false;
            const issues = [];
            for (const {status, count, retailer, product, status_reason} of retailers) {
                const key = Object.hasOwn(statusLabels, status) ? status : 'error';
                counts.set(key, (counts.get(key) || 0) + 1);
                const hasCount = Number.isFinite(count) && key !== 'error';
                if (attention.has(key)) {
                    issues.push({key, retailer, product, reason: status_reason});
                }
                if (hasCount) {
                    storedRows += count;
                    countAvailable = true;
                }
            }

            const status = document.createElement('ul');
            status.className = 'dx-overview-status';
            status.setAttribute('role', 'list');
            status.setAttribute('aria-label', '수집 상태');
            for (const key of [...attention, ...Object.keys(statusLabels).filter(key => !attention.has(key))]) {
                if (!counts.has(key)) continue;
                const item = document.createElement('li');
                item.dataset.status = key;
                item.textContent = statusLabels[key] + ' ' + formatter.format(counts.get(key)) + '개';
                status.append(item);
            }
            if (!counts.size) {
                const empty = document.createElement('li');
                empty.textContent = '수집 대상 없음';
                status.append(empty);
            }
            market.append(status);

            const stored = document.createElement('dl');
            stored.className = 'dx-overview-stored';
            const label = document.createElement('dt');
            label.textContent = 'DB 적재 확인';
            const value = document.createElement('dd');
            value.textContent = countAvailable ? formatter.format(storedRows) + '건' : '확인 불가';
            stored.append(label, value);
            if (countAvailable && counts.has('error')) {
                const scope = document.createElement('dd');
                scope.className = 'dx-overview-date';
                scope.textContent = '조회 성공 범위';
                stored.append(scope);
            }
            market.append(stored);

            if (issues.length) {
                const list = document.createElement('ul');
                list.className = 'dx-overview-issues';
                list.setAttribute('role', 'list');
                list.setAttribute('aria-label', '확인이 필요한 리테일러와 제품군');

                for (const {key, retailer, product, reason} of issues) {
                    const row = document.createElement('li');
                    const seller = document.createElement('strong');
                    seller.textContent = retailer || '리테일러 정보 없음';
                    const category = document.createElement('span');
                    category.className = 'dx-overview-category';
                    category.textContent = product || '제품군 정보 없음';
                    if (Object.hasOwn(productIcons, product)) {
                        const icon = document.createElement('span');
                        icon.setAttribute('aria-hidden', 'true');
                        icon.textContent = productIcons[product];
                        category.prepend(icon);
                    }
                    const state = document.createElement('span');
                    state.className = 'dx-overview-issue-state';
                    state.dataset.status = key;
                    state.textContent = statusLabels[key];
                    row.append(seller, category, state);
                    if (typeof reason === 'string' && reason.trim()) {
                        const note = document.createElement('p');
                        note.textContent = reason;
                        row.append(note);
                    }
                    list.append(row);
                }
                market.append(list);
            }
            markets.append(market);
        }
        message.hidden = countries.length > 0;
        if (!countries.length) message.textContent = '표시할 수집 현황이 없습니다.';
    } catch {
        markets.replaceChildren();
        message.classList.add('is-error');
        message.textContent = '당일 수집 현황 조회에 실패했습니다. 상세 화면에서 다시 조회해 주세요.';
    }
}

loadCollectionOverview();
