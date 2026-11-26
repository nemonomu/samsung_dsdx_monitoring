async function loadCollectionOverview() {
    const overview = document.querySelector('.dx-overview');
    const message = overview.querySelector('.dx-overview-message');
    const markets = overview.querySelector('.dx-overview-markets');
    const formatter = new Intl.NumberFormat('ko-KR');
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
            const name = document.createElement('h3');
            name.textContent = country + ' Retail';
            market.append(name);

            const date = document.createElement('p');
            date.className = 'dx-overview-date';
            date.textContent = '수집 대상일 ' + source_date;
            market.append(date);

            const counts = new Map();
            let storedRows = 0;
            let countAvailable = false;
            for (const {status, count} of retailers) {
                const key = Object.hasOwn(statusLabels, status) ? status : 'error';
                counts.set(key, (counts.get(key) || 0) + 1);
                if (typeof count === 'number' && Number.isFinite(count) && key !== 'error') {
                    storedRows += count;
                    countAvailable = true;
                }
            }

            const status = document.createElement('p');
            status.className = 'dx-overview-status';
            status.textContent = counts.size ? [...counts]
                .sort(([left], [right]) => Number(attention.has(right)) - Number(attention.has(left)))
                .map(([key, count]) => statusLabels[key] + ' ' + formatter.format(count) + '개')
                .join(' · ') : '수집 대상 없음';
            market.append(status);

            const stored = document.createElement('p');
            stored.className = 'dx-overview-stored';
            stored.textContent = countAvailable
                ? 'DB 적재 확인 ' + formatter.format(storedRows) + '건'
                : 'DB 적재 건수 확인 불가';
            if (countAvailable && counts.has('error')) stored.textContent += ' (조회 성공 범위)';
            market.append(stored);
            markets.append(market);
        }
        message.textContent = countries.length ? '당일 조회 지원 범위 · SEA 및 SEDA(Casas Bahia)' : '표시할 수집 현황이 없습니다.';
    } catch {
        markets.replaceChildren();
        message.textContent = '당일 수집 현황 조회에 실패했습니다. 상세 화면에서 다시 조회해 주세요.';
    }
}

loadCollectionOverview();
