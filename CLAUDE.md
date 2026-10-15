# DX Monitoring Project

## 프로젝트 개요
- DX 데이터 품질 모니터링 시스템 (Django)
- 미국 TV/HHP Retail, YouTube, Market Trend, LLM 분석 데이터 검증
- 레이어 구조: Layer1(기본 통계) → Layer2(형식/NULL) → Layer3(이상치) → Layer4(검수 확인)

## 기술 스택
- Backend: Django, PostgreSQL (AWS RDS)
- Frontend: Vanilla JS (프레임워크 없음)
- 배포: Ubuntu, Gunicorn

## 아키텍처 규칙
- Controller(API) → Service → Repository 패턴
- 파일 네이밍: `{모듈}_{역할}.py` (예: `retail_services.py`, `retail_api.py`, `retail_repositories.py`)
- 뷰(views.py): 페이지 렌더링만 담당, 비즈니스 로직 금지
- API: JsonResponse 반환, `dx_connection()` 컨텍스트 매니저로 DB 연결

## DB 규칙
- 테이블 참조: `dx_table()` 사용 (개발=테스트 테이블, 운영=운영 테이블 자동 분기). 하드코딩 금지
- 모니터링 관리 이력의 시간 저장: KST 기준 (`now() AT TIME ZONE 'Asia/Seoul'`). 수집 원본 일시는 변환하거나 덮어쓰지 않는다.
- Soft delete: `is_del` 컬럼 사용 (0=활성, 1=삭제)
- 파라미터 바인딩: `%s` 사용 (SQL injection 방지). f-string으로 값 삽입 금지

## 리테일 수집일 기준
- 신규 국가·리테일러의 수집일은 **DB 원본 수집 일시에 기록된 날짜**를 사용한다. 현재 서버 날짜, 배치 ID, 시간대 변환 결과로 대체하지 않는다.
- 기본 공통 함수: `apps.common.source_dates.source_date_sql`, `source_date_value`. `2026-10-14T21:37:34-04:00`은 10월 14일 수집분이다.
- SIEL의 기존 기준과 별도 조회 기능의 날짜·시각 변환은 예외로 유지한다. 이 예외를 신규 모니터링의 기본값으로 복사하지 않는다.
- 검수일(D-1 등), 예정/마감 시각, 표시 시각은 수집일 분류와 별개이다. 상세 원칙은 `AGENTS.md`를 따른다.

## 프론트엔드 규칙
- 날짜 비교: 로컬 시간 기준. `new Date('YYYY-MM-DD')` (UTC 파싱) 금지 → `new Date(year, month-1, day)` 사용
- 날짜 포맷: `toISOString()` 금지 → 로컬 날짜 포맷 함수 사용
- 공통 컴포넌트: FilterBar (`static/js/filter-bar.js`), CommonTable, AppModal
- 미래 날짜 조회 차단: 다음날/조회 버튼에 toast 경고 필수

## 검수 로직 (Layer1)
- 1차 확인 (confirm_step=1): 검증 결과 확인 + 이상치 기록
- 2차 완료 (confirm_step=2): 완료율 100% 필수 (retail 제외), 미해결 이슈 차단, NULL 항목 이슈 등록 필수
- 검수 테이블: `monitoring_check_log`, `monitoring_check_log_detail`, `monitoring_check_log_keywords`, `monitoring_check_log_issues`

## 커밋 규칙
- 영어 한 줄 (`feat:`, `fix:`, `refactor:` prefix)
- 예: `feat: add completion rate validation for market competitor monitoring`

## 문서화 규칙
- 수정사항 노션 정리 시 템플릿 사용:
  - 타이틀: 수정사항 전체 포함 한 줄 요약
  - 각 항목: 파일, 배경, 변경 내용, 효과

## 금지사항
- `dx_table()` 없이 테이블명 직접 사용
- UTC 기반 날짜 비교/파싱
- views.py에 비즈니스 로직 작성
- 불필요한 주석, docstring, 타입 힌트 추가
