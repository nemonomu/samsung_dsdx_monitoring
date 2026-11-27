async function loadCollectionOverview() {
    const overview = document.querySelector('.dx-overview');
    const message = overview.querySelector('.dx-overview-message');
    const markets = overview.querySelector('.dx-overview-markets');
    const inspectionDate = overview.querySelector('time').dateTime;
    const countryNames = {SEA: '미국', SEDA: '브라질', SEM: '멕시코'};
    const productIcons = {TV: 'tv', REF: 'refrigerator', LDY: 'washer', LDY_DRYER: 'dryer'};
    const productNames = {TV: 'TV', REF: '냉장고', LDY: '세탁기', LDY_DRYER: '건조기'};
    const issueLabels = {
        error: '조회 실패', uncollected: '미수집', abnormal: 'BSR 이상',
        rank_mismatch: '순위 이상', partial: '일부 수집'
    };
    const routineStates = new Set(['scheduled', 'waiting', 'collecting', 'received']);

    async function loadCountries(url, options) {
        const response = await fetch(url, options);
        if (!response.ok) throw new Error('Collection status unavailable');
        const {countries} = await response.json();
        if (!Array.isArray(countries)) throw new Error('Collection status missing');
        return countries;
    }

    try {
        const results = await Promise.allSettled([
            loadCountries(overview.dataset.statusUrl),
            loadCountries(overview.dataset.semTvStatusUrl, {signal: AbortSignal.timeout(8000)}),
        ]);
        const countries = results.flatMap(result => result.status === 'fulfilled' ? result.value : []);
        const failures = results.filter(result => result.status === 'rejected').length;
        if (failures === results.length) throw new Error('No collection status available');

        for (const {country, source_date, retailers} of countries) {
            const issues = retailers.filter(row => !routineStates.has(row.status));
            if (!issues.length) continue;

            const market = document.createElement('section');
            const name = document.createElement('h3');
            name.innerHTML = window.renderCountryFlagLabel(country + ' Retail');
            if (Object.hasOwn(countryNames, country)) {
                name.querySelector('.country-flag-label > span').textContent = countryNames[country];
            }
            market.append(name);

            if (source_date && source_date !== inspectionDate) {
                const date = document.createElement('p');
                date.className = 'dx-overview-date';
                date.textContent = '수집 대상일 ' + source_date;
                market.append(date);
            }

            const list = document.createElement('ul');
            list.className = 'dx-overview-issues';
            list.setAttribute('role', 'list');

            for (const {status, retailer, product, status_reason} of issues) {
                const row = document.createElement('li');
                const seller = document.createElement('strong');
                seller.textContent = retailer || '리테일러 정보 없음';

                const category = document.createElement('span');
                category.className = 'dx-overview-category';
                category.textContent = Object.hasOwn(productNames, product)
                    ? productNames[product] : product || '제품군 정보 없음';
                if (Object.hasOwn(productIcons, product)) {
                    const icon = document.createElement('img');
                    icon.src = overview.dataset.productIconUrl + productIcons[product] + '.svg';
                    icon.alt = '';
                    icon.width = 24;
                    icon.height = 24;
                    category.prepend(icon);
                }

                const state = document.createElement('span');
                state.className = 'dx-overview-issue-state';
                const key = Object.hasOwn(issueLabels, status) ? status : 'unknown';
                state.dataset.status = key;
                state.textContent = key === 'unknown' ? '상태 확인 필요' : issueLabels[key];
                row.append(seller, category, state);

                if (typeof status_reason === 'string' && status_reason.trim()) {
                    const note = document.createElement('p');
                    note.textContent = status_reason;
                    row.append(note);
                }
                list.append(row);
            }

            market.append(list);
            markets.append(market);
        }

        message.hidden = !failures && markets.childElementCount > 0;
        if (failures) {
            message.classList.add('is-error');
            message.textContent = '일부 수집 현황을 조회하지 못했습니다.';
        } else if (!message.hidden) {
            message.textContent = countries.some(country => country.retailers.length > 0)
                ? '현재 확인이 필요한 크롤러가 없습니다.' : '조회할 수집 대상이 없습니다.';
        }
    } catch {
        markets.replaceChildren();
        message.classList.add('is-error');
        message.textContent = '수집 현황을 조회하지 못했습니다. 리테일러별 상세에서 다시 확인해 주세요.';
    }
}

loadCollectionOverview();
