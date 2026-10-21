"""
DX Document 뷰
DX 문서 관리 (이슈보고서, 검수 보고서, 검수 매뉴얼 등)
"""

from django.shortcuts import render, redirect
from django.core.signing import TimestampSigner, SignatureExpired, BadSignature
from django.http import HttpResponse, HttpResponseNotFound
from apps.common.response import log_error
from apps.dx.dx_document.document.document_services import (
    get_categories_list,
    get_categories_for_edit,
    is_token_revoked,
    get_shared_document,
    get_shared_file,
)

# 문서 공유 토큰 서명
SHARE_SIGNER = TimestampSigner(salt='document-share')
SHARE_MAX_AGE = 86400  # 24시간


def index(request):
    """DX 문서 페이지"""
    try:
        categories = get_categories_list()
    except Exception as e:
        categories = []
        log_error(e, 'db')

    from .manual import is_manual_category
    for category in categories:
        category['is_manual'] = is_manual_category(category)
    selected_id = request.GET.get('category') or (categories[0]['category_id'] if categories else '')
    if any(cat['is_manual'] and cat['category_id'] == selected_id for cat in categories):
        return redirect('dx_document:manual')

    context = {
        'data_source': {
            'id': 'dx',
            'name': 'DX Retail',
            'name_en': 'TV/HHP Retail Monitoring',
            'color': '#0d9488',
        },
        'categories': categories,
    }
    return render(request, 'dx_document/index.html', context)


def edit(request, document_id=None):
    """DX 문서 편집 페이지"""
    selected_category = request.GET.get('category', '')
    template_content = ''

    try:
        categories = get_categories_for_edit()
    except Exception as e:
        categories = []
        log_error(e, 'db')

    selected_category_name = ''
    try:
        selected_category_type = int(request.GET.get('type', 1))
    except (ValueError, TypeError):
        selected_category_type = 1
    if selected_category:
        for cat in categories:
            if cat['category_id'] == selected_category:
                selected_category_name = cat['category_name']
                template_content = cat.get('template_content') or ''
                selected_category_type = cat.get('category_type') or 1
                break

    context = {
        'data_source': {
            'id': 'dx',
            'name': 'DX Retail',
            'name_en': 'TV/HHP Retail Monitoring',
            'color': '#0d9488',
        },
        'document_id': document_id,
        'is_new': document_id is None,
        'categories': categories,
        'selected_category': selected_category,
        'selected_category_name': selected_category_name,
        'selected_category_type': selected_category_type,
        'template_content': template_content,
    }
    return render(request, 'dx_document/edit.html', context)


def share(request, token):
    """문서 공유 페이지 (로그인 불필요, 1일 만료)"""
    # 토큰 검증
    try:
        signed_value = SHARE_SIGNER.unsign(token, max_age=SHARE_MAX_AGE)
    except SignatureExpired:
        return render(request, 'dx_document/share.html', {
            'error': '만료된 링크입니다. 공유 링크는 생성 후 24시간 동안만 유효합니다.',
            'error_type': 'expired',
        })
    except BadSignature:
        return render(request, 'dx_document/share.html', {
            'error': '유효하지 않은 링크입니다.',
            'error_type': 'invalid',
        })

    # category_id:document_id 분리
    if ':' in signed_value:
        category_id, document_id = signed_value.split(':', 1)
    else:
        # 하위 호환: 기존 토큰은 document_id만 포함
        document_id = signed_value
        category_id = None

    # DB에서 토큰 차단 여부 + 문서 조회
    try:
        if is_token_revoked(token):
            return render(request, 'dx_document/share.html', {
                'error': '공유가 취소된 링크입니다.',
                'error_type': 'revoked',
            })

        document = get_shared_document(document_id)
        if not document:
            return render(request, 'dx_document/share.html', {
                'error': '문서를 찾을 수 없습니다.',
                'error_type': 'not_found',
            })

        # 이미지 URL을 공유 전용 프록시로 치환
        if document.get('content'):
            document['content'] = document['content'].replace(
                '/api/dx/documents/file/',
                f'/dx-share/file/{token}/'
            )
    except Exception as e:
        log_error(e, 'db')
        return render(request, 'dx_document/share.html', {
            'error': '문서를 불러오는 중 오류가 발생했습니다.',
            'error_type': 'error',
        })

    return render(request, 'dx_document/share.html', {
        'document': document,
    })


def share_file(request, token, file_name):
    """공유 문서 이미지 프록시 (토큰 검증 후 S3에서 직접 전달)"""
    import mimetypes
    import boto3
    from config.config import S3_CONFIG

    # 토큰 검증 (동일 만료 시간)
    try:
        SHARE_SIGNER.unsign(token, max_age=SHARE_MAX_AGE)
    except (SignatureExpired, BadSignature):
        return HttpResponseNotFound('유효하지 않은 링크입니다.')

    # 토큰 차단 여부 확인
    try:
        if is_token_revoked(token):
            return HttpResponseNotFound('유효하지 않은 링크입니다.')
    except Exception:
        pass

    # 파일 조회 + S3에서 직접 읽어서 전달
    try:
        file_info = get_shared_file(file_name)
        if not file_info:
            return HttpResponseNotFound('파일을 찾을 수 없습니다.')

        s3_key = f'{file_info["file_path"]}/{file_info["file_name"]}'
        s3_client = boto3.client(
            's3',
            region_name=S3_CONFIG['region'],
            aws_access_key_id=S3_CONFIG['access_key'],
            aws_secret_access_key=S3_CONFIG['secret_key']
        )
        s3_obj = s3_client.get_object(Bucket=S3_CONFIG['bucket'], Key=s3_key)
        file_data = s3_obj['Body'].read()

        content_type = mimetypes.guess_type(file_name)[0] or 'application/octet-stream'
        response = HttpResponse(file_data, content_type=content_type)
        response['Cache-Control'] = 'private, max-age=3600'
        return response
    except Exception:
        return HttpResponseNotFound('파일을 불러올 수 없습니다.')
