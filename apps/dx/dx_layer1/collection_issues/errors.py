"""Safe, actionable storage diagnostics without exposing SQL or credentials."""
import logging

logger = logging.getLogger(__name__)


def storage_error(exc, operation):
    logger.error('Collection issue storage failed: %s', operation, exc_info=True)
    detail = str(exc).lower()
    if any(text in detail for text in ('no such table', 'no such column',
                                       'undefined table', 'undefined column')):
        return {
            'code': 'issue_storage_schema',
            'error': '미해결 이력 저장소 업데이트가 필요합니다.',
            'action': '운영 서버의 DB 마이그레이션 적용 여부를 확인해야 합니다. 새로고침만으로 해결되지 않습니다.',
        }
    if 'database is locked' in detail or 'database table is locked' in detail:
        return {
            'code': 'issue_storage_busy',
            'error': '미해결 이력 저장소가 다른 작업에 사용 중입니다.',
            'action': '잠시 후 다시 조회하세요. 반복되면 서버의 동시 집계 작업과 DB 잠금을 확인해야 합니다.',
        }
    return {
        'code': 'issue_storage_error',
        'error': '미해결 이력 저장소에 오류가 발생했습니다.',
        'action': '서버 로그의 Collection issue storage failed 오류를 확인해야 합니다.',
    }
