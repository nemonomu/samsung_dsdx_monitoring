# 크로스필드 수정 체크리스트

기준일: 2026-09-10. 브랜치: `fix/sem-crossfield-history-3days`.
체크 표시는 로컬 구현·검증 완료를 뜻한다. 운영 반영은 별도 확인한다.
기존 규칙 ID를 유지하고, 신규 규칙만 추가한다. main 병합은 사용자 지시 시에만 한다.

## 1. SEG Mediamarkt·OTTO

- [x] Mediamarkt: 할인율 10% 이하이면 savings 누락을 정상 처리한다. 정확히 10%도 포함한다.
- [x] 두 리테일러: 리뷰 수와 별점 수가 다르면 이상치로 표시한다.
- [x] 두 리테일러: 기존 별점·카운트 규칙에서 별점과 리뷰 수의 0 여부도 검사한다. 같은 규칙 내 중복 집계는 하지 않는다.
- [x] 두 리테일러: 별점 형식·범위 검사는 Layer 2에서 처리하고 Layer 3 적용 대상에서는 제외한다.
- [x] OTTO: Lowes처럼 네 가지 본문 조건을 확인 필요로 표시한다. 리뷰 수가 있는데 본문 없음 / 리뷰 수 0인데 본문 있음 / 본문 최대 번호가 리뷰 수보다 큼 / 리뷰 수 20 이상인데 review20 미달.
- [x] 두 리테일러: 같은 상품의 전날 대비 리뷰본문 감소를 리뷰 수·별점 수 변화와 함께 판정한다. 날짜별 최신 MAIN 배치를 비교하고, 전날 데이터가 없거나 본문·카운트를 해석할 수 없으면 감소로 판정하지 않는다.
- [x] 감소 상세에는 전날·당일 본문 개수와 실제 비교 행을 표시한다. 기본 3일·100행, 기존 수정·정상 확인 UI를 유지한다.

## 2. 국가 공통 가격·카운트 관계

- [x] 최종가 > 원가를 >=로 변경: SEA TV 및 Bestbuy REF/LDY, SIEL Amazon·Flipkart, SEG 전체, TSE Homepro 및 Lotuss TV, SEM Liverpool.
- [x] SEA Lowes REF/LDY는 이미 >=이므로 중복 추가하지 않는다. SEM 원가 0 전용 규칙은 유지한다.
- [x] 기존 별점 규칙에 리뷰 수 0 여부 비교 추가: SEA Bestbuy TV/REF/LDY, Lowes REF/LDY, SEG Mediamarkt·OTTO, TSE Homepro, SEM Liverpool.
- [x] SIEL Flipkart의 리뷰 수 <= 별점 수 정책, Amazon 및 SEA Walmart의 별점 수 정책, TSE 제외 리테일러·미지원 필드 정책을 유지한다.
- [x] SEA TV 운영 화면의 규칙 10/12/14 확인: 가격은 기존 규칙 12 수정, 별점·리뷰 수 0 관계는 Bestbuy에만 규칙 10 확장. Amazon/Walmart는 리뷰 수와 별점 수가 같아야 하는 대상이 아니다.
- [x] 검수 기준 안내 문구도 변경된 가격·카운트 조건에 맞춘다.

## 3. SQL·검증·배포

- [x] SEG 신규 규칙 3개를 상품별로 등록하는 재실행 가능한 SQL을 준비한다. 기존 규칙 ID는 유지한다.
- [x] 같은 행이 이상치와 확인 필요에 모두 해당하면 대시보드 행 수는 이상치로 한 번 집계한다. 개별 규칙 상세는 각각 유지한다.
- [x] 가격 경계·카운트 0값·Amazon 예외·전날 비교·정상 확인·수정을 검증한다. 관련 Python 테스트 총 108개, JavaScript 테스트 파일 2개 통과.
- [x] 변경 SQL 4개 파일의 PostgreSQL SQL/PL/pgSQL 문법 파싱과 diff 검사를 완료한다. 운영 DB 실행 결과는 별도 확인한다.
- [x] 현재 작업 브랜치에 커밋·푸시한다. main 병합은 하지 않는다.
- [ ] 운영 SQL 적용과 서버 배포 후 결과를 확인한다.

## 운영 반영 순서

1. 서버에서 아래 브랜치의 최신 커밋을 받는다.
2. DBeaver에서 다음 두 파일을 각각 전체 실행한다.
   - `sql/seed_seg_layer3_crossfield.sql`: 기존 SEG 규칙 ID 유지, 신규 규칙 추가. 결과는 TV/REF/LDY 각각 13개, 합계 39개.
   - `sql/update_crossfield_price_and_review_zero.sql`: 기존 SEA TV SQL과 국가별 규칙 설명 수정. 원본 상품 데이터 수정 없음. 검토 당시의 SEA TV 규칙과 다르면 예외로 중단하므로 트랜잭션을 롤백한 뒤 해당 규칙을 다시 확인한다.
3. Django 검사·정적 파일 반영·gunicorn 재시작을 수행한다.
4. SEG 이상치·확인 필요 건수와 상세를 확인한다.

```bash
git switch fix/sem-crossfield-history-3days
git pull --ff-only
git log -1 --oneline
# 위의 SQL 2개 실행 후
venv/bin/python manage.py check &&
venv/bin/python manage.py collectstatic --noinput &&
sudo systemctl restart gunicorn &&
systemctl is-active gunicorn
```

SEA REF/LDY 및 SIEL seed 파일도 최신 설명으로 갱신했다. 이번 운영 반영에서는 위의 SQL 2개만 실행하면 된다. main에는 병합하지 않는다.

## 후속 수정: 카운트 변화에 따른 리뷰본문 감소

- [x] 카운트 유지·증가 중 본문 감소는 이상치로 처리한다.
- [x] 리뷰 수·별점 수 모두 0이고 본문도 0이면 본문 감소에서 제외한다. 별점 값과 카운트의 기존 논리 검증은 별도로 유지한다.
- [x] 두 카운트 모두 0인데 본문이 남아 있으면 기존 본문 확인 규칙에서 확인 필요로 표시한다. Mediamarkt에도 이 조건을 적용한다.
- [x] 두 카운트가 함께 감소하면 당일 두 카운트가 같고 본문이 `min(당일 리뷰 수, 20)` 이상일 때 감소를 허용한다. 50→10/본문 20→10은 정상, 50→10/본문 20→5 및 50→30/본문 20→15는 이상치다.
- [x] 한 카운트만 0이거나 두 카운트가 불일치하면 감소 허용 예외로 처리하지 않는다. NULL·빈값·잘못된 숫자는 0으로 취급하지 않는다.
- [x] 당일 감소 판정은 KST 12:00부터 수행한다. 이전 날짜는 판정하고 미래 날짜는 판정하지 않는다. 수집이 지연되면 실제 완료 여부를 별도로 확인해야 한다.
- [x] 카운트 유지·증가·감소, 0·NULL·잘못된 값, KST 종료 경계, 기존 정상 확인·수정 등 관련 Python 테스트 30개 통과.
- [ ] 후속 수정 운영 반영: 최신 코드 배포와 `sql/seed_seg_layer3_crossfield.sql` 재실행. 기존 규칙의 설명·표시 컬럼을 갱신하며 규칙 수는 상품별 13개, 총 39개로 유지한다. 앞서 안내한 SQL 2개를 아직 실행하지 않았다면 기존 운영 반영 순서도 수행한다.
