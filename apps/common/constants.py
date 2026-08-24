"""
공통 상수 정의

- REVIEW_REASONS: 정상 처리 사유 목록 (check_type별)
- VALIDATION_TYPE_LABELS: 형식 검증 타입 한글 라벨
- 추가 시 해당 리스트/딕셔너리에 값 추가하면 됨
"""

# 정상 처리 사유 (check_type → 사유 목록)
# 순서대로 드롭다운에 표시됨
REVIEW_REASONS = {
    'null_check': [
        '수집 대상 제품 아님',
        '상품페이지 내 항목 부재',
        '상품페이지 없음',
        'final_sku_price가 현재와 달라 보정 불가',
        '해당값정상 확인',
    ],
    'format_check': [
    ],
    'duplicate_check': [
    ],
    'cross_field': [
        '수집 대상 제품 아님',
        '상품페이지 내 항목 부재',
        '상품페이지 없음',
        'final_sku_price가 현재와 달라 보정 불가',
        '중간 텍스트 리뷰 없음',
        '해당 값 정상 확인',
        '리뷰수가 현재와 달라 보정 불가',
    ],
    'field_missing': [
        '수집 대상 제품 아님',
        '상품페이지 내 항목 부재',
        '상품페이지 없음',
        'final_sku_price가 현재와 달라 보정 불가',
        '중간 텍스트 리뷰 없음',
        '해당 값 정상 확인',
        '리뷰수가 현재와 달라 보정 불가',
    ],
}


# 형식 검증 타입 (DB value → 한글 라벨)
# 순서대로 select에 표시됨
VALIDATION_TYPE_LABELS = {
    'regex': '정규식 매칭',
    'regex_clean': '정규식 (정제 후)',
    'range': '정수 범위',
    'range_float': '실수 범위',
    'enum': '허용값 목록',
    'starts_with': '접두사 일치',
    'allowed_values': '허용값 (파이프)',
    'separator_count': '구분자 개수',
    'fk_check': 'FK 참조',
    'min': '최소값',
}


def get_reasons(check_type):
    """check_type에 해당하는 사유 목록 반환"""
    return REVIEW_REASONS.get(check_type, [])


def get_validation_type_label(vtype):
    """검증 타입 영문 키 → 한글 라벨"""
    return VALIDATION_TYPE_LABELS.get(vtype, vtype)
