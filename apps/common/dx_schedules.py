"""
DX 수집 스케줄 설정 로드
DB에서 수집 시간대 설정을 읽어옴
US(NY) 시간 → KST 자동 변환 (서머타임 고려)
"""

from datetime import datetime, timedelta
import pytz
from apps.common.db import execute_dx_query, dx_table

# 타임존 설정
NY_TZ = pytz.timezone('America/New_York')
KST_TZ = pytz.timezone('Asia/Seoul')

# 캐시된 데이터
_schedules_cache = None


def us_to_kst(us_hour, reference_date=None):
    """
    US(NY) 시간을 KST로 변환 (서머타임 자동 고려)

    Args:
        us_hour: US(NY) 시간 (0-24)
        reference_date: 기준 날짜 (date 객체, 기본값: 오늘)

    Returns:
        tuple: (kst_hour, next_day, is_dst)
        - kst_hour: KST 시간 (0-23)
        - next_day: 다음날 여부 (True/False)
        - is_dst: 서머타임 적용 여부 (True/False)
    """
    if reference_date is None:
        reference_date = datetime.now().date()

    # us_hour가 24인 경우 다음날 0시로 처리
    if us_hour == 24:
        us_hour = 0
        reference_date = reference_date + timedelta(days=1)

    # NY 시간으로 datetime 생성
    ny_dt = NY_TZ.localize(datetime(reference_date.year, reference_date.month, reference_date.day, us_hour, 0, 0))

    # KST로 변환
    kst_dt = ny_dt.astimezone(KST_TZ)

    # 서머타임 여부 확인 (NY 기준)
    is_dst = bool(ny_dt.dst())

    # 다음날 여부 확인
    next_day = kst_dt.date() > reference_date

    return kst_dt.hour, next_day, is_dst


def get_kst_time_info(us_hour, reference_date=None):
    """
    US(NY) 시간의 KST 변환 정보를 문자열로 반환

    Args:
        us_hour: US(NY) 시간 (0-24)
        reference_date: 기준 날짜 (date 객체)

    Returns:
        dict: {
            'hour': KST 시간,
            'next_day': 다음날 여부,
            'is_dst': 서머타임 여부,
            'display': 표시용 문자열 (예: "14:00" 또는 "+1 02:00"),
            'date': KST 날짜 (date 객체),
            'full_display': 날짜 포함 표시용 문자열 (예: "2026-01-05 14:00")
        }
    """
    kst_hour, next_day, is_dst = us_to_kst(us_hour, reference_date)

    if reference_date is None:
        reference_date = datetime.now().date()

    # KST 날짜 계산
    if next_day:
        kst_date = reference_date + timedelta(days=1)
        display = f"+1 {kst_hour:02d}:00"
    else:
        kst_date = reference_date
        display = f"{kst_hour:02d}:00"

    full_display = f"{kst_date} {kst_hour:02d}:00"

    return {
        'hour': kst_hour,
        'next_day': next_day,
        'is_dst': is_dst,
        'display': display,
        'date': kst_date,
        'full_display': full_display
    }


def load_collection_schedules():
    """
    DB에서 수집 스케줄 목록을 로드

    Returns:
        list of dict: 스케줄 정보 리스트
    """
    global _schedules_cache

    if _schedules_cache is not None:
        return _schedules_cache

    try:
        table = dx_table('monitoring_collection_schedule')
        query = f"""
            SELECT check_group, check_type, check_name, category,
                   schedule_type, schedule_value, us_start_hour,
                   retailer, expected_count, country,
                   collection_duration_min, view_table_name,
                   sort_order, description
            FROM {table}
            WHERE is_active = TRUE AND is_del = 0
            ORDER BY sort_order, id
        """
        rows = execute_dx_query(query)

        schedules = []
        for row in rows:
            schedules.append({
                'check_group': row['check_group'],
                'check_type': row['check_type'],
                'check_name': row['check_name'],
                'category': row['category'],
                'schedule_type': row['schedule_type'],
                'schedule_value': row['schedule_value'],
                'us_start_hour': int(row['us_start_hour']) if row['us_start_hour'] is not None else None,
                'retailer': row['retailer'],
                'expected_count': row['expected_count'],
                'country': row['country'],
                'collection_duration_min': int(row['collection_duration_min']),
                'view_table_name': row['view_table_name'],
                'sort_order': row['sort_order'],
                'description': row['description']
            })
        _schedules_cache = schedules
    except Exception as e:
        print(f"Error loading collection schedules from DB: {e}")
        _schedules_cache = []

    return _schedules_cache


def get_schedules_by_type(check_type, category=None):
    """
    check_type과 category로 스케줄 필터링

    Args:
        check_type: 검수 항목 유형 (retail, sentiment, youtube 등)
        category: 카테고리 (TV, HHP, ALL) - None이면 전체

    Returns:
        list of dict: 필터링된 스케줄 리스트
    """
    schedules = load_collection_schedules()
    filtered = [s for s in schedules if s['check_type'] == check_type]

    if category:
        cat_upper = category.upper()
        filtered = [s for s in filtered if (s['category'] or '').upper() in (cat_upper, 'ALL')]

    return filtered


def get_time_status(schedule, target_date, now=None):
    """
    현재 시간 기준으로 수집 상태 반환 (US→KST 자동 변환)

    Args:
        schedule: 스케줄 dict
        target_date: 조회 대상 날짜 (date 객체)
        now: 현재 시간 (datetime 객체, 기본값: datetime.now())

    Returns:
        str: 'PENDING', 'COLLECTING', or None (결과 표시)
    """
    if now is None:
        now = datetime.now()

    # US 시간에서 KST 자동 계산
    us_start = schedule['us_start_hour'] if schedule['us_start_hour'] is not None else 0
    duration_min = schedule['collection_duration_min']

    kr_start_hour, kr_start_next_day, _ = us_to_kst(us_start, target_date)

    # KST 수집 시작 datetime 계산
    if kr_start_next_day:
        kr_start_date = target_date + timedelta(days=1)
    else:
        kr_start_date = target_date

    kr_start_dt = datetime(kr_start_date.year, kr_start_date.month, kr_start_date.day, kr_start_hour, 0, 0)

    # 수집 종료 시간 = 시작 시간 + collection_duration_min
    kr_end_dt = kr_start_dt + timedelta(minutes=duration_min)

    # 현재 시간이 수집 시간대에 있는지 확인
    if now < kr_start_dt:
        return 'PENDING'
    elif now < kr_end_dt:
        return 'COLLECTING'
    else:
        return None  # 결과 표시


def get_time_slots(check_type, category, target_date, now=None):
    """
    특정 검수 항목의 시간대 슬롯 정보 반환 (US→KST 자동 변환, 서머타임 고려)

    Args:
        check_type: 검수 항목 유형
        category: 카테고리 (TV, HHP)
        target_date: 조회 대상 날짜 (date 객체)
        now: 현재 시간 (기본값: datetime.now())

    Returns:
        list of dict: 시간대 슬롯 정보 (is_dst 포함)
    """
    if now is None:
        now = datetime.now()

    schedules = get_schedules_by_type(check_type, category)

    # 같은 us_start_hour 끼리 묶어서 하나의 슬롯으로 (리테일러별 행 중복 방지)
    # 슬롯별 리테일러 목록도 수집
    hour_groups = {}  # us_start_hour → { schedule, retailers: [] }
    for schedule in schedules:
        us_start = schedule['us_start_hour'] if schedule['us_start_hour'] is not None else 0
        if check_type == 'retail' and (category or '').upper() == 'TV' and us_start >= 12:
            continue
        if us_start not in hour_groups:
            hour_groups[us_start] = {'schedule': schedule, 'retailers': []}
        if schedule.get('retailer'):
            hour_groups[us_start]['retailers'].append({
                'name': schedule['retailer'],
                'expected_count': schedule.get('expected_count', 0) or 0,
            })

    time_slots = []
    for us_start, group in sorted(hour_groups.items()):
        schedule = group['schedule']
        slot_retailers = group['retailers']
        duration_min = schedule['collection_duration_min']

        # 시작 시간 문자열 생성
        start_str = f'{target_date} {us_start:02d}:00:00'

        # 종료 시간 계산
        # retail의 경우: 오전(00:00~12:00), 오후(12:00~다음날00:00) 고정 범위
        # 기타: duration 기준
        us_start_dt = datetime(target_date.year, target_date.month, target_date.day, us_start, 0, 0)
        if check_type == 'retail':
            # retail은 12시간 단위로 고정
            if us_start == 0:
                # 오전: 00:00 ~ 12:00
                us_end_dt = datetime(target_date.year, target_date.month, target_date.day, 12, 0, 0)
            else:
                # 오후: 12:00 ~ 다음날 00:00
                next_day = target_date + timedelta(days=1)
                us_end_dt = datetime(next_day.year, next_day.month, next_day.day, 0, 0, 0)
        else:
            us_end_dt = us_start_dt + timedelta(minutes=duration_min)
        end_str = us_end_dt.strftime('%Y-%m-%d %H:%M:%S')

        # KST 시간 자동 계산 (서머타임 고려)
        kst_start_info = get_kst_time_info(us_start, target_date)

        # KST 종료 시간 = 시작 시간 + duration
        kr_start_hour, kr_start_next_day, _ = us_to_kst(us_start, target_date)
        if kr_start_next_day:
            kr_start_date = target_date + timedelta(days=1)
        else:
            kr_start_date = target_date
        kr_start_dt = datetime(kr_start_date.year, kr_start_date.month, kr_start_date.day, kr_start_hour, 0, 0)
        kr_end_dt = kr_start_dt + timedelta(minutes=duration_min)

        kst_end_info = {
            'hour': kr_end_dt.hour,
            'next_day': kr_end_dt.date() > target_date,
            'is_dst': kst_start_info['is_dst'],
            'display': f"{kr_end_dt.hour:02d}:00",
            'date': kr_end_dt.date(),
            'full_display': f"{kr_end_dt.date()} {kr_end_dt.hour:02d}:00"
        }

        # 상태 판정
        time_status = get_time_status(schedule, target_date, now)
        is_pending = time_status in ['PENDING', 'COLLECTING']

        time_slots.append({
            'name': '오전' if us_start < 12 else '오후',
            'start': start_str,
            'end': end_str,
            'us_time': f'{target_date} {us_start:02d}:00',
            'kr_time': kst_start_info['full_display'],
            'kr_time_end': kst_end_info['full_display'],
            'is_dst': kst_start_info['is_dst'],
            'is_pending': is_pending,
            'time_status': time_status,
            'schedule': schedule,
            'retailers': slot_retailers
        })

    return time_slots


def is_target_date(schedule, target_date):
    """
    스케줄 DB 기반으로 해당 날짜가 수집 대상일인지 판단

    Args:
        schedule: 스케줄 dict (schedule_type, schedule_value 포함)
        target_date: 조회 대상 날짜 (date 객체)

    Returns:
        bool: 수집 대상일이면 True
    """
    if schedule.get('check_type') == 'seuk_retail':
        from apps.common.seuk_retail import enabled
        if not enabled(target_date):
            return False

    st = schedule['schedule_type']
    sv = schedule.get('schedule_value') or ''

    if st == 'daily':
        return True

    elif st == 'weekly':
        day_map = {'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4, 'sat': 5, 'sun': 6}
        days = [d.strip().lower() for d in sv.split(',') if d.strip()]
        return target_date.weekday() in [day_map.get(d, -1) for d in days]

    elif st == 'monthly':
        # 'first_mon', 'first_tue' 등: 매월 첫 번째 특정 요일
        if sv and sv.startswith('first_'):
            day_map = {'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4, 'sat': 5, 'sun': 6}
            weekday = day_map.get(sv.split('_', 1)[1], -1)
            if weekday < 0:
                return False
            first_day = target_date.replace(day=1)
            days_until = (weekday - first_day.weekday()) % 7
            first_target = first_day.day + days_until
            return target_date.day == first_target
        try:
            return target_date.day == int(sv) if sv else target_date.day == 1
        except (ValueError, TypeError):
            return False

    elif st == 'quarterly':
        # 분기 첫 월(1,4,7,10)의 첫 날 또는 지정일
        if target_date.month not in (1, 4, 7, 10):
            return False
        try:
            return target_date.day == int(sv) if sv else target_date.day == 1
        except (ValueError, TypeError):
            return target_date.day == 1

    elif st == 'yearly':
        # 'MM-DD' 형식
        try:
            parts = sv.split('-')
            return target_date.month == int(parts[0]) and target_date.day == int(parts[1])
        except (ValueError, TypeError, IndexError):
            return False

    return False


def reload_schedules():
    """캐시 초기화 후 다시 로드 (DB 데이터 변경 시 사용)"""
    global _schedules_cache
    _schedules_cache = None
    return load_collection_schedules()


# 편의 함수들
def get_retail_time_slots(category, target_date, now=None):
    """Retail 검수용 시간대 슬롯"""
    return get_time_slots('retail', category, target_date, now)


def get_sentiment_time_slots(category, target_date, now=None):
    """Sentiment 검수용 시간대 슬롯"""
    return get_time_slots('sentiment', category, target_date, now)


def get_youtube_time_slots(target_date, now=None):
    """YouTube 검수용 시간대 슬롯"""
    return get_time_slots('youtube', 'ALL', target_date, now)


def get_market_time_slots(check_type, target_date, now=None):
    """Market 관련 검수용 시간대 슬롯"""
    return get_time_slots(check_type, 'ALL', target_date, now)


def get_schedule_kst_info(check_type, target_date, now=None, category=None):
    """
    특정 check_type의 스케줄 KST 변환 정보를 한 번에 계산하여 반환

    Args:
        check_type: 검수 항목 유형 (market_trend, market_demand, market_promotion 등)
        target_date: 조회 대상 날짜 (date 객체)
        now: 현재 시간 (datetime 객체, 기본값: datetime.now())
        category: 카테고리 (TV, HHP, ALL) - None이면 전체에서 첫 번째 스케줄 사용

    Returns:
        dict: {
            'us_start_hour': US 시작 시간,
            'collection_duration_min': 수집 소요 시간(분),
            'kst_start': KST 시작 정보 (get_kst_time_info 반환값),
            'kst_end': KST 종료 정보,
            'time_status': 'PENDING', 'COLLECTING', or None,
            'is_pending': 대기중 여부,
            'is_collecting': 수집중 여부,
            'collection_done': 수집 완료 여부
        }
    """
    if now is None:
        now = datetime.now()

    schedules = get_schedules_by_type(check_type, category)
    if not schedules:
        return None

    schedule = schedules[0]  # 첫 번째 스케줄 사용
    us_start = schedule['us_start_hour']
    duration_min = schedule['collection_duration_min']

    # KST 시작 시간 계산
    kst_start = get_kst_time_info(us_start, target_date)

    # KST 종료 시간 = 시작 시간 + duration
    kr_start_hour, kr_start_next_day, _ = us_to_kst(us_start, target_date)
    if kr_start_next_day:
        kr_start_date = target_date + timedelta(days=1)
    else:
        kr_start_date = target_date
    kr_start_dt = datetime(kr_start_date.year, kr_start_date.month, kr_start_date.day, kr_start_hour, 0, 0)
    kr_end_dt = kr_start_dt + timedelta(minutes=duration_min)

    kst_end = {
        'hour': kr_end_dt.hour,
        'next_day': kr_end_dt.date() > target_date,
        'is_dst': kst_start['is_dst'],
        'display': f"{kr_end_dt.hour:02d}:00",
        'date': kr_end_dt.date(),
        'full_display': f"{kr_end_dt.date()} {kr_end_dt.hour:02d}:00"
    }

    # 상태 판정
    time_status = get_time_status(schedule, target_date, now)
    is_pending = time_status == 'PENDING'
    is_collecting = time_status == 'COLLECTING'
    collection_done = time_status is None

    return {
        'us_start_hour': us_start,
        'collection_duration_min': duration_min,
        'kst_start': kst_start,
        'kst_end': kst_end,
        'time_status': time_status,
        'is_pending': is_pending,
        'is_collecting': is_collecting,
        'collection_done': collection_done,
        'schedule': schedule
    }
