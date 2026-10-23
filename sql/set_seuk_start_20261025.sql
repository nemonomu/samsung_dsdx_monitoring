-- 기존 SEUK 등록 환경용: 운영 시작일 안내 문구만 2026-10-25로 갱신.
-- 실제 검수 시작일은 앱의 FIRST_SOURCE_DATE 설정으로 적용됩니다.
-- 이 변경을 포함한 코드를 배포하고 웹/모니터링 프로세스를 재시작하세요.
-- 수집 프로그램의 실행 예약 및 원본 데이터/통계/검수 이력은 변경하지 않습니다.
BEGIN;
DO $seuk_start$
DECLARE
    prefix text := ''; -- 운영 ''. 테스트는 'test_'.
    schedule_table text;
    matched integer;
    products integer;
BEGIN
    IF prefix NOT IN ('','test_') THEN RAISE EXCEPTION 'Invalid prefix'; END IF;
    schedule_table := prefix || 'monitoring_collection_schedule';
    EXECUTE format('LOCK TABLE public.%I IN SHARE ROW EXCLUSIVE MODE',schedule_table);
    EXECUTE format('SELECT COUNT(*),COUNT(DISTINCT category) FROM public.%I
        WHERE check_type=''seuk_retail'' AND country=''SEUK''
          AND LOWER(BTRIM(retailer))=''currys'' AND is_active AND is_del=0
          AND category IN (''TV'',''REF'',''LDY'',''LDY_DRYER'')',schedule_table)
    INTO matched,products;
    IF matched<>4 OR products<>4 THEN
        RAISE EXCEPTION 'Expected four active SEUK Currys schedules; run setup_seuk_layer1.sql first';
    END IF;
    EXECUTE format('UPDATE public.%I
        SET description=$1,updated_at=NOW(),updated_id=''set_seuk_start_20261025''
        WHERE check_type=''seuk_retail'' AND country=''SEUK''
          AND LOWER(BTRIM(retailer))=''currys'' AND is_active AND is_del=0
          AND category IN (''TV'',''REF'',''LDY'',''LDY_DRYER'')',schedule_table)
    USING '영국 Currys 당일(D) · KST 01:00~04:00 · 최초 2026-10-25 · BSR 5일 관찰 후 기준 결정';
END
$seuk_start$;
COMMIT;
