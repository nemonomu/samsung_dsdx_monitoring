# Layer1 수집데이터 통계

## 화면 확인

- Layer1 사이드바 **수집데이터 통계**: `/dx/layer1/collection-statistics/`
- 국가(SEA/SEDA/SIEL/SEG/SEM/TSE), 제품군, 업체, 최근 4/8/12주를 선택한다.
- 주간 합계, 완료된 대상일의 일평균, 미수집 일수, 일별 상세를 확인한다.
- 기준 데이터일이 속한 **월~일 주간 전체**를 마지막 주로 보여준다. 날짜까지의 누적 조회가 아니다.
- 진행 중인 주/일부 미집계 주는 부분 집계로 표시한다. 완료된 0건은 평균에 포함하고, 수집 중·조회 실패·미집계는 제외한다.
- 총 건수는 각 국가 Layer1 표의 총 건수와 동일하다. MAIN+BSR의 합산 값이 아니다. SEM과 TSE의 MAIN 기준 업체 등 기존 화면 기준을 유지한다.

기존 Layer1 대시보드 및 SEA Retail 페이지에서는 주간 통계를 불러오지 않는다. 업체 행, 제품군, 국가 상태에만 저장된 수집량 판정을 반영한다.

| 상황 | Layer1 표시 |
| --- | --- |
| 이전 28 데이터일 중 비교 가능한 7일 이상 중앙값보다 30% 이상 감소 | 빨간 **이상** |
| 같은 기준보다 30% 이상 증가 | 파란 **확인 필요** |
| 변동 폭 30% 미만 | 기존 상태 유지, 변동률 추가 표시 없음 |
| 기존 미수집/최소 건수 오류 | 기존 오류 우선 |
| 수집 중/이력 부족/집계 장애/최신 배치와 불일치 | 새로운 수집량 판정 보류, 기존 상태 유지 |

MAIN, BSR, 총 건수를 각각 비교한다. 감소와 증가가 함께 있으면 이상을 우선한다. 증가 자체를 수집 실패로 단정하지 않는다. BSR 비대상 업체는 비교에서 제외한다. 기존 수집 상태가 정상이어도 통계 이력 부족 때문에 수집량 비교를 못할 수 있으며, 통계 상세에서 확인 가능하다.

## 운영 서버 적용

Ubuntu 서버의 기존 프로젝트 폴더에서 일반 배포 사용자(예: `ubuntu`)로 실행한다. `venv/bin/python`과 기존 `gunicorn` 서비스가 있는 환경을 대상으로 한다. 개발 PC에서 운영 설정을 읽거나 운영 서버 명령을 실행하지 않았다.

배포 스크립트를 처음 받는 이번 한 번은:

```bash
git pull --ff-only
bash scripts/deploy.sh
```

이후 배포는 아래 한 줄이다. 현재 체크아웃된 브랜치를 갱신하며 브랜치를 자동 전환하거나 로컬 변경을 지우지 않는다.

```bash
bash scripts/deploy.sh
```

스크립트가 `git pull --ff-only` → Django 검사 → 통계 테이블 마이그레이션 → 정적 파일 반영 → gunicorn 재시작 → 통계 자동 갱신 등록/시작을 수행한다. 기존 추적 파일에 수정이 있거나 중간 단계가 실패하면 중단한다. 서버 관리에 필요한 `sudo`는 해당 명령에만 사용하며 스크립트 전체를 `sudo`로 실행하지 않는다.

통계는 별도 systemd 작업 `samsung-dsdx-collection-statistics.service`에서 처리하고, 같은 이름의 `.timer`가 15분마다 실행한다. 최초 배포 시에도 즉시 작업을 시작하되 배포 명령은 과거 집계 완료를 기다리지 않는다. 최근 3일을 모든 국가에 먼저 반영하고, 이후 실행마다 국가별 최대 14일의 미집계 이력을 채워 최대 112일을 준비한다. 최초에는 과거 주간 결과가 일부만 보일 수 있으며 차례로 채워진다. 이미 준비된 과거 이력은 반복 조회하지 않고, 오류가 난 이력은 재시도한다. 재부팅 후에도 타이머가 자동 실행된다.

서버에서 자동 갱신 등록 여부를 확인할 때:

```bash
systemctl is-enabled samsung-dsdx-collection-statistics.timer
systemctl list-timers samsung-dsdx-collection-statistics.timer
```

### 필요한 경우에만 수동 집계

자동 배포를 사용하면 아래 명령을 매번 입력할 필요가 없다. 최초 이력을 한 번에 전부 채우거나 특정 과거 날짜를 다시 집계할 때만 사용한다.

```console
python manage.py migrate dx_layer1
python manage.py refresh_collection_statistics --days 112
```

첫 집계는 12주 표시분과 비교 이력을 준비한다. 국가별 실행도 가능하다.

```console
python manage.py refresh_collection_statistics --country SEA --days 112
```

Ubuntu 자동 배포 외의 환경에서는 기존 운영 스케줄러에 다음 명령을 15분 간격으로 등록할 수 있다. 작업 디렉터리는 저장소 루트, 실행 파일은 운영 가상환경의 Python으로 지정한다. 작업이 중첩되면 국가별 DB 잠금으로 같은 국가 집계를 건너뛴다.

```console
python manage.py refresh_collection_statistics --automatic
```

3일보다 오래된 데이터의 재적재/삭제 후에는 해당 **데이터일**을 지정해 다시 집계한다. 이력이 변경되면 이후 28일 비교 결과와 관련 주간 합계도 갱신된다. 같은 명령을 반복해도 수집 건수를 더하지 않고 교체한다.

```console
python manage.py refresh_collection_statistics --country SEA --start 2026-09-15 --end 2026-09-21
```

수동 범위는 최대 120일씩 처리한다. SEA/SEDA는 데이터일에 1일을 더한 검수일을 이용하며 다른 국가는 당일이다. SEA HomeDepot는 2026-09-20부터 대상으로 취급한다. 운영 소스 조회 실패는 0건을 만들지 않으며 기존 건수를 보존하고 갱신 실패로 표시한다. 명령은 실패 건수가 있으면 실패 종료한다.

## 속도 및 갱신 구조

- 원본 테이블 집계는 관리 명령에서만 수행한다. 기존 국가별 Layer1 집계 로직을 재사용하며 개별 SQL에 30초 제한을 둔다.
- Django 기본 DB에 일별 요약, 주별 요약, 집계 잠금 테이블 3개를 추가한다. 기존 원본 테이블은 수정하지 않는다.
- 통계 API는 최대 12개 주간 요약을 한 번 조회한다. Layer1 판정 API는 선택 검수일의 최대 6개 국가 요약을 한 번 조회한다.
- 기존 Layer1 데이터 로딩과 수집량 판정 로딩은 독립적이다. 판정 응답 지연/장애 때문에 기본 화면을 기다리게 하지 않는다. 판정 요청은 3초 후 중단한다.
- 판정 적용 전에 날짜, 업체, 제품, 배치 ID, MAIN/BSR/총 건수를 대조한다. SEA의 별도 건수 API가 더 최신인 경우에도 이전 판정을 적용하지 않는다.
- 당일 검수 결과는 마지막 집계가 60분 이상 오래되면 추가 수집량 판정을 적용하지 않는다. 주간 화면에는 마지막 집계 시각을 보여준다.
- 집계 데이터가 없거나 요약 DB 조회가 실패해도 화면 요청에서 원본을 재집계하는 대체 동작은 없다.

## 검증

```console
python tests/test_collection_statistics_backend.py
python tests/test_collection_statistics_deploy.py
node tests/test_collection_volume.js
node tests/test_layer1_progressive_loading.js
python -m unittest tests.unit.test_layer1_sidebar_context
```

운영 설정 없이 합성 데이터로 실제 템플릿과 API를 확인하려면:

```console
python tests/preview_collection_statistics.py
```

`http://127.0.0.1:8766/dx/layer1/collection-statistics/?date=2026-09-21`에서 확인한다. 임시 메모리 DB만 사용하며 프로세스 종료 시 사라진다.

확인 순서: 통계 메뉴 → 주간 합계/일평균 → 9월 14일 주의 상세(감소·증가·0건) → 국가 필터의 미집계 표시. 운영 적용 후에는 기존 Layer1 업체 행의 빨간/파란 배지, 30% 미만일 때 추가 표시가 없는지, 재수집 후 이전 경고가 해제되는지를 함께 확인한다.
