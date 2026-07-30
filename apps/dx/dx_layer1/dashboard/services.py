"""
Layer 1 Dashboard Services: 통계 오케스트레이션 비즈니스 로직
"""

from datetime import datetime
from apps.common.db import dx_connection
from apps.common.response import log_error
from apps.common.dx_schedules import load_collection_schedules, is_target_date as check_target_date

from apps.dx.dx_layer1.retail import retail_services as retail_svc
from apps.dx.dx_layer1.sentiment import sentiment_services as sentiment_svc
from apps.dx.dx_layer1.youtube import youtube_services as youtube_svc
from apps.dx.dx_layer1.market_trend import market_trend_services as market_trend_svc
from apps.dx.dx_layer1.market_demand import market_demand_services as market_demand_svc
from apps.dx.dx_layer1.market_competitor import market_competitor_services as market_competitor_svc
from apps.dx.dx_layer1.market_competitor_event import market_competitor_event_services as market_competitor_event_svc
from apps.dx.dx_layer1.market_promotion import market_promotion_services as market_promotion_svc
from apps.dx.dx_layer1.macro.macro_services import (
    macro_capital_stock_svc, macro_net_interest_svc, macro_potential_gdp_svc,
    macro_gdp_ppp_nominal_svc, macro_gdp_ppp_real_svc, macro_disposable_income_real_svc,
    macro_cpi_svc, macro_disposable_income_nominal_svc, macro_household_debt_svc, macro_rpi_svc,
)


EXPECTED_PER_RETAILER = 300
OK_THRESHOLD = 200

_SERVICE_MAP = {
    'retail': retail_svc,
    'sentiment': sentiment_svc,
    'youtube': youtube_svc,
    'market_trend': market_trend_svc,
    'market_demand': market_demand_svc,
    'market_competitor': market_competitor_svc,
    'market_competitor_event': market_competitor_event_svc,
    'market_promotion': market_promotion_svc,
    'macro_capital_stock': macro_capital_stock_svc,
    'macro_net_interest': macro_net_interest_svc,
    'macro_potential_gdp': macro_potential_gdp_svc,
    'macro_gdp_ppp_nominal': macro_gdp_ppp_nominal_svc,
    'macro_gdp_ppp_real': macro_gdp_ppp_real_svc,
    'macro_disposable_income_real': macro_disposable_income_real_svc,
    'macro_cpi': macro_cpi_svc,
    'macro_disposable_income_nominal': macro_disposable_income_nominal_svc,
    'macro_household_debt': macro_household_debt_svc,
    'macro_rpi': macro_rpi_svc,
}

_YOUTUBE_SAVEPOINT = 'layer1_youtube_monitoring'


def _rollback_youtube_savepoint(cursor):
    cursor.execute(f'ROLLBACK TO SAVEPOINT {_YOUTUBE_SAVEPOINT}')
    cursor.execute(f'RELEASE SAVEPOINT {_YOUTUBE_SAVEPOINT}')


def _get_youtube_stats_isolated(cursor, svc, target_date, now):
    """YouTube 조회 실패가 다른 Layer1 수집 결과를 무효화하지 않게 한다."""
    cursor.execute(f'SAVEPOINT {_YOUTUBE_SAVEPOINT}')
    try:
        svc_result = svc.get_layer1_stats(cursor, target_date, now)
        if not isinstance(svc_result, dict) or not isinstance(
            svc_result.get('check'), dict
        ):
            _rollback_youtube_savepoint(cursor)
            return None
    except Exception as exc:
        _rollback_youtube_savepoint(cursor)
        log_error(exc)
        return None

    cursor.execute(f'RELEASE SAVEPOINT {_YOUTUBE_SAVEPOINT}')
    return svc_result


def _get_active_services(target_date=None):
    """스케줄 DB에서 활성 서비스 목록, daily 여부, target_date 여부를 동적으로 구성"""
    schedules = load_collection_schedules()
    seen = set()
    service_order = []
    daily_types = set()
    target_date_types = set()

    for s in schedules:
        ct = s['check_type']
        if ct not in _SERVICE_MAP:
            continue
        if ct not in seen:
            seen.add(ct)
            service_order.append((ct, _SERVICE_MAP[ct]))
        if s['schedule_type'] == 'daily':
            daily_types.add(ct)
        if target_date and check_target_date(s, target_date):
            target_date_types.add(ct)

    return service_order, daily_types, target_date_types


def get_dashboard_stats(target_date, check_type_filter=None):
    """Layer 1 통계 - 8개 서비스 오케스트레이션"""
    now = datetime.now()
    today = now.date()

    results = {
        'timestamp': now.isoformat(),
        'target_date': str(target_date),
        'today': str(today),
        'layer': 1,
        'name': '기본 통계 검수',
        'checks': [],
        'failed_items': [],
        'thresholds': {
            'expected': EXPECTED_PER_RETAILER,
            'ok': OK_THRESHOLD,
            'description': f'정상: {OK_THRESHOLD}건 이상 | 위험: {OK_THRESHOLD}건 미만'
        },
        'summary': {
            'total_checked': 0,
            'passed': 0,
            'failed': 0,
            'pass_rate': 0,
            'status': 'OK'
        }
    }

    try:
        with dx_connection() as (conn, cursor):
            service_order, daily_types, target_date_types = _get_active_services(target_date)
            comp_batch_id = None

            for check_type, svc in service_order:
                if check_type_filter and check_type_filter != check_type:
                    continue

                if check_type == 'youtube':
                    svc_result = _get_youtube_stats_isolated(
                        cursor, svc, target_date, now
                    )
                    if svc_result is None:
                        results['failed_items'].append({
                            'source': 'Consumer (YouTube)',
                            'error_type': '조회 오류',
                            'expected': '국가 수집 데이터',
                            'actual': 0,
                            'timestamp': str(target_date),
                        })
                        continue
                elif check_type == 'market_competitor_event':
                    svc_result = svc.get_layer1_stats(cursor, target_date, now, comp_batch_id=comp_batch_id)
                else:
                    svc_result = svc.get_layer1_stats(cursor, target_date, now)

                if check_type == 'market_competitor' and 'comp_batch_id' in svc_result:
                    comp_batch_id = svc_result['comp_batch_id']

                check_data = svc_result['check']
                check_data['display_group'] = 'daily' if check_type in daily_types else 'periodic'
                check_data['is_target_date'] = check_type in target_date_types
                results['checks'].append(check_data)
                results['failed_items'].extend(svc_result.get('failed_items', []))

        if not check_type_filter:
            check_items = [
                {'status': c['status'], 'is_target': c.get('is_target_date', False)}
                for c in results['checks']
            ]
            target_items = [item for item in check_items if item['is_target']]
            target_statuses = [item['status'] for item in target_items]
            completed_statuses = [s for s in target_statuses if s not in ('PENDING', 'COLLECTING', 'ANALYZING')]

            passed = len([s for s in completed_statuses if s == 'OK'])
            failed = len([s for s in completed_statuses if s == 'CRITICAL'])

            results['summary'] = {
                'total_checked': len(target_items),
                'total_completed': len(completed_statuses),
                'passed': passed,
                'failed': failed,
                'pass_rate': round((passed / len(target_items) * 100), 1) if target_items else 0,
                'status': 'CRITICAL' if failed > 0 else 'OK'
            }

    except Exception as e:
        results['error'] = log_error(e)
        results['summary']['status'] = 'ERROR'

    return results
