// 리테일러의 최종 배치 정보 조회 (이상치 조회용 시간 범위)
async function fetchFinalBatchInfo(retailer, date) {
    try {
        const response = await fetch(`/ds/layer2/api/stats/?date=${date}&batch_view=final`);
        const data = await response.json();
        if (data.results) {
            const retailerInfo = data.results.find(r => r.retailer === retailer);
            if (retailerInfo) {
                return {
                    table_name: retailerInfo.table_name,
                    country: retailerInfo.country,
                    final_start_time: retailerInfo.final_start_time,
                    final_end_time: retailerInfo.final_end_time
                };
            }
        }
    } catch (error) {
        console.error('Error fetching final batch info:', error);
    }
    return null;
}

// 리테일러의 이상치 데이터 조회 (최종 배치만, 중복 제거)
async function fetchAnomalies(tableName, date, country, startTime, endTime) {
    const errorTypes = ['title_null', 'imageurl_null', 'imageurl_invalid', 'price_zero', 'partial_null'];
    const anomalyMap = new Map(); // producturl을 키로 사용하여 중복 제거

    for (const errorType of errorTypes) {
        let url = `/ds/layer2/api/detail/?table=${tableName}&error_type=${errorType}&date=${date}&page=1&page_size=1000`;
        // 최종 배치 시간 범위 적용
        if (startTime) url += `&start_time=${startTime}`;
        if (endTime) url += `&end_time=${endTime}`;

        try {
            const response = await fetch(url);
            const data = await response.json();
            if (data.data && data.data.length > 0) {
                data.data.forEach(item => {
                    // producturl을 키로 사용 (없으면 title+retailprice 조합 사용)
                    const key = item.producturl || `${item.title}_${item.retailprice}`;
                    if (!anomalyMap.has(key)) {
                        anomalyMap.set(key, {
                            country_code: country,
                            title: item.title || '',
                            retailprice: item.retailprice || null,
                            ships_from: item.ships_from || '',
                            sold_by: item.sold_by || '',
                            imageurl: item.imageurl || '',
                            producturl: item.producturl || '',
                            retailersku: item.retailersku || ''
                        });
                    }
                });
            }
        } catch (error) {
            console.error(`Error fetching ${errorType}:`, error);
        }
    }

    return Array.from(anomalyMap.values());
}

// 리테일러 저장
async function saveRetailer(retailer, event) {
    if (event) event.stopPropagation();
    if (reportStatus.is_closed) {
        showToast('마감된 날짜는 수정할 수 없습니다');
        return;
    }

    const date = document.getElementById('targetDate').value;

    // statsData에서 해당 리테일러 정보 찾기
    const retailerData = statsData.results.find(r => r.retailer === retailer);
    if (!retailerData) {
        showToast('리테일러 정보를 찾을 수 없습니다');
        return;
    }

    // 파일서버 파일 확인
    showToast('파일서버 확인 중...', 'info');
    let fileMatches = [];
    try {
        const fsRes = await fetch(`/ds/layer1/api/fileserver/?date=${date}`);
        const fsData = await fsRes.json();
        const normalizeFs = name => name.toLowerCase().replace(/[-_]/g, '');
        fileMatches = (fsData.countries || []).filter(c => normalizeFs(c.retailer) === normalizeFs(retailer));
    } catch (e) {
        showToast('파일서버 조회 실패', 'error');
        return;
    }

    if (fileMatches.length === 0) {
        showToast(`${retailer}: 파일서버에 저장된 파일이 없습니다. 파일을 확인해주세요.`, 'error');
        return;
    }

    if (fileMatches.length >= 2) {
        const confirmed = await showConfirm(`${retailer}: 파일이 ${fileMatches.length}개 존재합니다.\n마감 전에 파일을 정리해주세요.`, 'warning');
        if (confirmed) {
            showToast('마감 전에 파일을 먼저 정리하여 주세요.', 'warning');
        }
        return;
    }

    // 저장 확인 팝업
    const fileNames = fileMatches.map(f => f.files[0]?.name).filter(Boolean).join('\n');
    const errorCount = (retailerData.null_union || 0)
        + (retailerData.imageurl_invalid || 0)
        + (retailerData.price_zero || 0)
        + (retailerData.partial_null || 0);
    let confirmMsg = errorCount > 0
        ? `${retailer} 이상치 데이터 ${errorCount}건을 저장하시겠습니까?`
        : `${retailer} 현황을 저장하시겠습니까?`;
    confirmMsg += `\n\n파일:\n${fileNames}`;
    const confirmed = await showConfirm(confirmMsg, errorCount > 0 ? 'warning' : 'info');
    if (!confirmed) {
        return;
    }

    showToast(`${retailer} 저장 중...`);

    try {
        // 최종 배치 정보를 가져옴 (이상치 조회용)
        let finalInfo = null;
        if (currentBatchView === 'final' && retailerData.final_start_time) {
            finalInfo = {
                table_name: retailerData.table_name,
                country: retailerData.country,
                final_start_time: retailerData.final_start_time,
                final_end_time: retailerData.final_end_time
            };
        } else {
            finalInfo = await fetchFinalBatchInfo(retailer, date);
            if (!finalInfo) {
                finalInfo = {
                    table_name: retailerData.table_name,
                    country: retailerData.country,
                    final_start_time: retailerData.final_start_time,
                    final_end_time: retailerData.final_end_time
                };
            }
        }

        // 이상치 상세 데이터 조회 (최종 배치만)
        const anomalies = await fetchAnomalies(
            finalInfo.table_name,
            date,
            finalInfo.country,
            finalInfo.final_start_time,
            finalInfo.final_end_time
        );

        // 백엔드에서 stats 직접 계산하므로 anomalies만 전송
        const response = await fetch('/ds/layer2/api/save/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify({
                crawl_date: date,
                retailer: retailer,
                anomalies: anomalies,
                user_id: currentUserId
            })
        });

        const result = await response.json();
        if (result.success) {
            showToast(`${retailer} 저장 완료 (이상치 ${result.anomaly_count}건)`);
            // 후속 작업
            await loadReportStatus();
            renderNullTable(statsData);
        } else {
            showToast(result.error || '저장 실패');
        }
    } catch (error) {
        showToast('저장 중 오류 발생');
    }
}

// 리테일러 삭제
async function deleteRetailer(retailer, event) {
    if (event) event.stopPropagation();
    if (reportStatus.is_closed) {
        showToast('마감된 날짜는 수정할 수 없습니다');
        return;
    }

    const confirmed = await showConfirm(`${retailer} 저장 데이터를 삭제하시겠습니까?`);
    if (!confirmed) {
        return;
    }

    const date = document.getElementById('targetDate').value;

    try {
        const response = await fetch('/ds/layer2/api/delete/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify({
                crawl_date: date,
                retailer: retailer,
                user_id: currentUserId
            })
        });

        const result = await response.json();
        if (result.success) {
            showToast(`${retailer} 삭제 완료`);
            await loadReportStatus();
            renderNullTable(statsData);
        } else {
            showToast(result.error || '삭제 실패');
        }
    } catch (error) {
        showToast('삭제 중 오류 발생');
    }
}

// 체크박스 전체선택
function toggleBulkSelectAll() {
    const selectAll = document.getElementById('bulkSelectAll');
    const checkboxes = document.querySelectorAll('.bulk-retailer-check:not(:disabled)');
    checkboxes.forEach(cb => cb.checked = selectAll.checked);
    updateBulkCount();
}

// 체크된 개수 업데이트
function updateBulkCount() {
    const checked = document.querySelectorAll('.bulk-retailer-check:checked');
    const countEl = document.getElementById('bulkCount');
    const btn = document.getElementById('bulkSaveBtn');
    if (!countEl || !btn) return;

    if (checked.length > 0) {
        countEl.textContent = `${checked.length}개 선택`;
        btn.disabled = false;
        btn.textContent = `일괄 마감 (${checked.length}개)`;
    } else {
        countEl.textContent = '';
        btn.disabled = true;
        btn.textContent = '일괄 마감';
    }

    // 전체선택 체크박스 상태 동기화
    const all = document.querySelectorAll('.bulk-retailer-check:not(:disabled)');
    const selectAll = document.getElementById('bulkSelectAll');
    if (selectAll && all.length > 0) {
        const allChecked = Array.from(all).every(cb => cb.checked);
        const someChecked = Array.from(all).some(cb => cb.checked);
        selectAll.checked = allChecked;
        selectAll.indeterminate = someChecked && !allChecked;
    }
}

// 리테일러 일괄 마감
async function bulkSaveRetailers() {
    const checked = document.querySelectorAll('.bulk-retailer-check:checked');
    if (checked.length === 0) return;

    const date = document.getElementById('targetDate').value;
    const selectedRetailers = Array.from(checked).map(cb => cb.dataset.retailer);

    // 최종 배치 데이터 + 파일서버 동시 조회
    showToast('마감 조건 확인 중...', 'info');
    let finalData = null;
    let fsData = null;
    try {
        const [finalRes, fsRes] = await Promise.all([
            fetch(`/ds/layer2/api/stats/?date=${date}&batch_view=final`),
            fetch(`/ds/layer1/api/fileserver/?date=${date}`)
        ]);
        finalData = await finalRes.json();
        fsData = await fsRes.json();
    } catch (e) {
        showToast('데이터 조회 실패', 'error');
        return;
    }

    // 파일서버 리테일러 매핑
    const normalizeFs = name => name.toLowerCase().replace(/[-_]/g, '');
    const fsRetailers = (fsData.countries || []);

    // 조건 체크: 최종 배치 수집 건수 >= 예상 건수 + 파일서버 파일 존재
    const eligible = [];
    const ineligible = [];

    for (const retailer of selectedRetailers) {
        const finalInfo = finalData.results?.find(r => r.retailer === retailer);
        const matchingFiles = fsRetailers.filter(c => normalizeFs(c.retailer) === normalizeFs(retailer));
        if (!finalInfo) {
            ineligible.push({ retailer, reason: '데이터 없음' });
        } else if (finalInfo.total < finalInfo.expected_count) {
            ineligible.push({ retailer, reason: `수집 미완료 (${finalInfo.total}/${finalInfo.expected_count})` });
        } else if (matchingFiles.length === 0) {
            ineligible.push({ retailer, reason: '저장된 zip 파일 없음' });
        } else if (matchingFiles.length >= 2) {
            ineligible.push({ retailer, reason: `파일 ${matchingFiles.length}개 (정리 필요)` });
        } else {
            eligible.push(retailer);
        }
    }

    // 전부 미충족
    if (eligible.length === 0) {
        let msg = '마감 가능한 리테일러가 없습니다.\n\n';
        ineligible.forEach(r => { msg += `- ${r.retailer}: ${r.reason}\n`; });
        const hasFileIssue = ineligible.some(r => r.reason.includes('정리 필요'));
        await showConfirm(msg, 'warning');
        if (hasFileIssue) {
            showToast('마감 전에 파일을 먼저 정리하여 주세요.', 'warning');
        }
        return;
    }

    // 일부 미충족
    let confirmMsg = '';
    if (ineligible.length > 0) {
        confirmMsg += '다음 리테일러는 마감 대상이 아닙니다.\n\n';
        ineligible.forEach(r => { confirmMsg += `- ${r.retailer}: ${r.reason}\n`; });
        confirmMsg += `\n나머지 ${eligible.length}개를 마감하시겠습니까?`;
    } else {
        confirmMsg = `${eligible.length}개 리테일러를 일괄 마감하시겠습니까?`;
    }

    const confirmed = await showConfirm(confirmMsg, ineligible.length > 0 ? 'warning' : 'info');
    if (!confirmed) return;

    // 순차 저장
    let successCount = 0;
    let failCount = 0;

    for (let i = 0; i < eligible.length; i++) {
        const retailer = eligible[i];
        showToast(`일괄 마감 중... (${i + 1}/${eligible.length}) ${retailer}`, 'info');

        try {
            const retailerData = statsData.results.find(r => r.retailer === retailer);
            if (!retailerData) { failCount++; continue; }

            // 최종 배치 정보
            const finalInfo = finalData.results.find(r => r.retailer === retailer);
            const batchInfo = {
                table_name: retailerData.table_name,
                country: retailerData.country,
                final_start_time: finalInfo.final_start_time,
                final_end_time: finalInfo.final_end_time
            };

            // 이상치 조회
            const anomalies = await fetchAnomalies(
                batchInfo.table_name, date, batchInfo.country,
                batchInfo.final_start_time, batchInfo.final_end_time
            );

            // 저장
            const response = await fetch('/ds/layer2/api/save/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
                body: JSON.stringify({
                    crawl_date: date,
                    retailer: retailer,
                    anomalies: anomalies,
                    user_id: currentUserId
                })
            });

            const result = await response.json();
            if (result.success) {
                successCount++;
            } else {
                failCount++;
            }
        } catch (e) {
            failCount++;
        }
    }

    // 결과
    if (failCount > 0) {
        showToast(`일괄 마감 완료 (성공 ${successCount}개, 실패 ${failCount}개)`, 'warning');
    } else {
        showToast(`일괄 마감 완료 (${successCount}개)`, 'success');
    }

    await loadReportStatus();
    renderNullTable(statsData);
}
