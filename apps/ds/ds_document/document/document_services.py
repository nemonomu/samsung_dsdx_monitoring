"""
DS Document Services: 비즈니스 로직, 토큰 생성/검증, S3 연동, DB 처리 체인
"""

import boto3
import mimetypes
from datetime import datetime, timedelta
from django.core.signing import TimestampSigner, SignatureExpired, BadSignature

from config.config import S3_CONFIG
from apps.common.db import ds_connection, DS_SHARE_TOKEN_TABLE
from apps.common.response import log_error
from apps.common.ds.files import ds_upload_file, ds_cleanup_orphan_files
from apps.common.ds.id_generator import generate_ds_id, generate_ds_token_id

from . import document_repositories as repo

# 문서 공유 토큰 서명 설정 (views.py에서 인계됨)
SHARE_SIGNER = TimestampSigner(salt='document-share')
SHARE_MAX_AGE = 86400  # 24시간


# ── 파일 업로드 & 통신 로직 ──────────────────────────────

def upload_file(file, object_document_id, username, upload_type=1):
    """DS 문서 파일 업로드"""
    if not file:
        return {'success': False, 'error': '파일이 없습니다.'}
    if not object_document_id:
        return {'success': False, 'error': 'object_document_id가 필요합니다.'}

    if upload_type not in (1, 2):
        upload_type = 1

    try:
        result = ds_upload_file(file, object_document_id, username, upload_type=upload_type)
        proxy_url = f'/api/ds/documents/file/{result["file_name"]}'
        return {
            'success': True,
            'file_id': result['file_id'],
            'url': proxy_url
        }
    except Exception as e:
        return {'success': False, 'error': log_error(e, 'upload')}


def get_file_proxy_url(file_name):
    """S3 리다이렉트용 Presigned URL 반환"""
    try:
        with ds_connection() as (conn, cursor):
            row = repo.get_document_file_info(cursor, file_name)

        if not row:
            return {'success': False, 'error': '파일을 찾을 수 없습니다.', 'status': 404}

        s3_key = f'{row[1]}/{row[0]}'

        s3_client = boto3.client(
            's3',
            region_name=S3_CONFIG['region'],
            aws_access_key_id=S3_CONFIG['access_key'],
            aws_secret_access_key=S3_CONFIG['secret_key']
        )

        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_CONFIG['bucket'], 'Key': s3_key},
            ExpiresIn=3600
        )

        return {'success': True, 'url': url}
    except Exception as e:
        return {'success': False, 'error': log_error(e)}


def get_file_binary_for_share(token, file_name):
    """토큰이 있는 비로그인 환경에서의 직접 S3 파일 다운로드 서비스 (views.py share_file 분리분)"""
    try:
        SHARE_SIGNER.unsign(token, max_age=SHARE_MAX_AGE)
    except (SignatureExpired, BadSignature):
        return {'success': False, 'error': '유효하지 않은 링크입니다.'}

    try:
        with ds_connection() as (conn, cursor):
            token_row = repo.get_share_token_revoked(cursor, DS_SHARE_TOKEN_TABLE, token)
            if token_row and token_row[0]:
                return {'success': False, 'error': '유효하지 않은 링크입니다.'}

            row = repo.get_document_file_info(cursor, file_name)

        if not row:
            return {'success': False, 'error': '파일을 찾을 수 없습니다.'}

        s3_key = f'{row[1]}/{row[0]}'
        s3_client = boto3.client(
            's3',
            region_name=S3_CONFIG['region'],
            aws_access_key_id=S3_CONFIG['access_key'],
            aws_secret_access_key=S3_CONFIG['secret_key']
        )
        s3_obj = s3_client.get_object(Bucket=S3_CONFIG['bucket'], Key=s3_key)
        file_data = s3_obj['Body'].read()

        content_type = mimetypes.guess_type(file_name)[0] or 'application/octet-stream'
        return {'success': True, 'file_data': file_data, 'content_type': content_type}

    except Exception:
        return {'success': False, 'error': '파일을 불러올 수 없습니다.'}


def delete_file(file_id, username):
    """단일 첨부파일 완전 삭제 및 S3정리"""
    try:
        now = datetime.now()
        with ds_connection() as (conn, cursor):
            row = repo.get_file_info_by_id(cursor, file_id)
            if not row:
                return {'success': False, 'error': '파일을 찾을 수 없습니다.'}

            repo.soft_delete_file(cursor, file_id, username, now)
            conn.commit()

        try:
            s3_key = f'{row[1]}/{row[0]}'
            s3_client = boto3.client(
                's3',
                region_name=S3_CONFIG['region'],
                aws_access_key_id=S3_CONFIG['access_key'],
                aws_secret_access_key=S3_CONFIG['secret_key']
            )
            s3_client.delete_object(Bucket=S3_CONFIG['bucket'], Key=s3_key)
        except Exception:
            pass

        return {'success': True, 'message': '파일이 삭제되었습니다.'}
    except Exception as e:
        return {'success': False, 'error': log_error(e, 'delete')}


def get_document_files(object_document_id):
    """첨부파일 목록 조회"""
    if not object_document_id:
        return {'success': False, 'error': 'object_document_id가 필요합니다.'}

    try:
        with ds_connection() as (conn, cursor):
            files = repo.get_document_files_list(cursor, object_document_id)
        return {'success': True, 'files': files}
    except Exception as e:
        return {'success': False, 'error': log_error(e, 'db')}


# ── VIEW용 화면 생성 데이터 로더 ──────────────────────────────

def get_categories_context():
    """index 뷰 용 카테고리 데이터 확보"""
    try:
        with ds_connection() as (conn, cursor):
            categories = repo.get_document_categories_with_count(cursor)
    except Exception as e:
        categories = []
        log_error(e, 'db')
    return categories


def get_editor_context(document_id, input_selected_category, input_category_type):
    """edit 뷰 용 문서 및 카테고리/템플릿 맥락 정보 확보"""
    selected_category = input_selected_category
    template_content = ''
    selected_category_name = ''
    
    try:
        selected_category_type = int(input_category_type)
    except (ValueError, TypeError):
        selected_category_type = 1

    try:
        with ds_connection() as (conn, cursor):
            categories = repo.get_document_categories(cursor)
            
            if document_id:
                row = repo.get_document_category_info(cursor, document_id)
                if row:
                    selected_category = row[0]
                    selected_category_name = row[1]
                    selected_category_type = row[2] or 1
            elif selected_category:
                for cat in categories:
                    if str(cat['category_id']) == str(selected_category):
                        selected_category_name = cat['category_name']
                        template_content = cat.get('template_content') or ''
                        selected_category_type = cat.get('category_type') or 1
                        break
    except Exception as e:
        categories = []
        log_error(e, 'db')

    return {
        'categories': categories,
        'selected_category': selected_category,
        'selected_category_name': selected_category_name,
        'selected_category_type': selected_category_type,
        'template_content': template_content,
    }

# ── 문서 CRUD ──────────────────────────────────────────────

def get_documents_list(category_id, search_field='', search_text='', date_from=''):
    """문서 목록 조회"""
    if not category_id:
        return {'success': False, 'error': '카테고리 ID가 필요합니다.'}

    try:
        with ds_connection() as (conn, cursor):
            documents = repo.get_documents_list_data(cursor, category_id, search_field, search_text, date_from)
        return {'success': True, 'documents': documents, 'total': len(documents)}
    except Exception as e:
        return {'success': False, 'error': log_error(e, 'db')}


def get_document_detail(document_id):
    """문서 상세 정보"""
    if not document_id:
        return {'success': False, 'error': '문서 ID가 필요합니다.'}

    try:
        with ds_connection() as (conn, cursor):
            document = repo.get_document_detail_info(cursor, document_id)
        if not document:
             return {'success': False, 'error': '문서를 찾을 수 없습니다.'}
        return {'success': True, 'document': document}
    except Exception as e:
        return {'success': False, 'error': log_error(e, 'db')}


def create_document(category_id, title, content, object_document_id, crawl_date, username):
    """문서 생성"""
    if not category_id:
        return {'success': False, 'error': '카테고리를 선택하세요.'}
    if not title:
        return {'success': False, 'error': '제목을 입력하세요.'}

    try:
        now = datetime.now()
        with ds_connection() as (conn, cursor):
            if crawl_date:
                # 마감 여부 체크
                cursor.execute("""
                    SELECT is_closed FROM ssd_crawl_db.ds_monitoring_report_close
                    WHERE crawl_date = %s
                """, (crawl_date,))
                close_row = cursor.fetchone()
                if close_row and close_row[0] == 1:
                    return {'success': False, 'error': '마감된 날짜입니다.'}

                # 기존 문서 존재 여부 확인 → 있으면 업데이트
                existing_doc = repo.get_document_by_crawl_date(cursor, category_id, crawl_date)
                if existing_doc:
                    document_id = existing_doc[0]
                    repo.update_document_record(cursor, document_id, title, content, username, now)

                    category_type = repo.get_category_type(cursor, category_id)
                    if category_type != 2:
                        obj_doc_id = existing_doc[1] if len(existing_doc) > 1 else object_document_id
                        ds_cleanup_orphan_files(cursor, obj_doc_id, content, username)
                    conn.commit()

                    return {
                        'success': True,
                        'document_id': document_id,
                        'message': '검수 보고서가 수정되었습니다.'
                    }

            document_id = generate_ds_id(cursor, 'ssd_crawl_db.ds_monitoring_documents', 'document_id')
            repo.insert_document_record(cursor, document_id, category_id, title, content, object_document_id, crawl_date, username, now)

            category_type = repo.get_category_type(cursor, category_id)
            if category_type != 2:
                ds_cleanup_orphan_files(cursor, object_document_id, content, username)
            conn.commit()

        return {
            'success': True,
            'document_id': document_id,
            'object_document_id': object_document_id,
            'message': '검수 보고서가 저장되었습니다.'
        }
    except Exception as e:
        return {'success': False, 'error': log_error(e, 'save')}


def update_document(document_id, title, content, username):
    """문서 수정"""
    if not title:
        return {'success': False, 'error': '제목을 입력하세요.'}

    try:
        now = datetime.now()
        with ds_connection() as (conn, cursor):
            row = repo.get_document_object_id_and_category_type(cursor, document_id)
            obj_doc_id = row[0] if row else None
            category_type = row[1] if row else 1

            repo.update_document_record(cursor, document_id, title, content, username, now)
            
            if category_type != 2:
                ds_cleanup_orphan_files(cursor, obj_doc_id, content, username)
            conn.commit()

        return {'success': True, 'message': '문서가 수정되었습니다.'}
    except Exception as e:
        return {'success': False, 'error': log_error(e, 'update')}


def delete_document(document_id, username):
    """문서 및 파일 동시 논리삭제 처리"""
    try:
        now = datetime.now()
        with ds_connection() as (conn, cursor):
            obj_doc_id = repo.get_document_object_id(cursor, document_id)
            repo.soft_delete_document(cursor, document_id, username, now)

            files = []
            if obj_doc_id:
                files = repo.get_document_files_for_object(cursor, obj_doc_id)
                repo.soft_delete_document_files(cursor, obj_doc_id, username, now)

            conn.commit()

        if files:
            try:
                s3_client = boto3.client(
                    's3',
                    region_name=S3_CONFIG['region'],
                    aws_access_key_id=S3_CONFIG['access_key'],
                    aws_secret_access_key=S3_CONFIG['secret_key']
                )
                for f in files:
                    s3_key = f'{f[1]}/{f[0]}'
                    s3_client.delete_object(Bucket=S3_CONFIG['bucket'], Key=s3_key)
            except Exception:
                pass

        return {'success': True, 'message': '문서가 삭제되었습니다.'}
    except Exception as e:
        return {'success': False, 'error': log_error(e, 'delete')}


# ── 공유 토큰 관리 ──────────────────────────────────────────────

def get_document_for_share(token):
    """토큰을 사용한 공유 문서 객체 및 상태 검증"""
    try:
        signed_value = SHARE_SIGNER.unsign(token, max_age=SHARE_MAX_AGE)
    except SignatureExpired:
        return {'success': False, 'error': '만료된 링크입니다. 공유 링크는 생성 후 24시간 동안만 유효합니다.', 'error_type': 'expired'}
    except BadSignature:
        return {'success': False, 'error': '유효하지 않은 링크입니다.', 'error_type': 'invalid'}

    # category_id:document_id 분리
    if ':' in signed_value:
        category_id, document_id = signed_value.split(':', 1)
    else:
        document_id = signed_value
        category_id = None

    try:
        with ds_connection() as (conn, cursor):
            token_row = repo.get_share_token_revoked(cursor, DS_SHARE_TOKEN_TABLE, token)
            if token_row and token_row[0]:
                return {'success': False, 'error': '공유가 취소된 링크입니다.', 'error_type': 'revoked'}

            row = repo.get_shared_document_detail(cursor, document_id)
            if not row:
                return {'success': False, 'error': '문서를 찾을 수 없습니다.', 'error_type': 'not_found'}

            columns = ['document_id', 'title', 'content', 'category_name', 'created_at']
            document = dict(zip(columns, row))

            if document.get('content'):
                document['content'] = document['content'].replace(
                    '/api/ds/documents/file/',
                    f'/ds-share/file/{token}/'
                )
            
        return {'success': True, 'document': document}
    except Exception as e:
        log_error(e, 'db')
        return {'success': False, 'error': '문서를 불러오는 중 오류가 발생했습니다.', 'error_type': 'error'}


def create_share_token(document_id, category_id, memo, username, existing=None):
    """토큰 발급"""
    if not document_id:
        return {'success': False, 'error': '문서 ID가 필요합니다.'}
    if not category_id:
        return {'success': False, 'error': '카테고리 ID가 필요합니다.'}
    if not memo:
        return {'success': False, 'error': '공유 대상 메모를 입력하세요.'}

    try:
        sign_value = f'{category_id}:{document_id}'
        token = SHARE_SIGNER.sign(sign_value)

        now = datetime.now()
        expires_at = now + timedelta(seconds=SHARE_MAX_AGE)
        
        with ds_connection(existing=existing) as (conn, cursor):
            token_id = generate_ds_token_id(cursor)
            repo.insert_share_token(cursor, DS_SHARE_TOKEN_TABLE, token_id, document_id, category_id, token, memo, username, now, expires_at)
            if existing is None:
                conn.commit()

        return {'success': True, 'token': token}
    except Exception as e:
        return {'success': False, 'error': log_error(e, 'save')}


def get_share_list(document_id):
    """이력 조회"""
    if not document_id:
        return {'success': False, 'error': '문서 ID가 필요합니다.'}

    try:
        with ds_connection() as (conn, cursor):
            rows = repo.get_share_links_history(cursor, DS_SHARE_TOKEN_TABLE, document_id)
        return {'success': True, 'shares': rows, 'total': len(rows)}
    except Exception as e:
        return {'success': False, 'error': log_error(e, 'db')}


def revoke_share_token(token_id, username):
    """공유 차단"""
    if not token_id:
        return {'success': False, 'error': '토큰 ID가 필요합니다.'}

    try:
        now = datetime.now()
        with ds_connection() as (conn, cursor):
            updated = repo.revoke_share_token_record(cursor, DS_SHARE_TOKEN_TABLE, token_id, username, now)
            conn.commit()

        if updated == 0:
            return {'success': False, 'error': '이미 차단되었거나 존재하지 않는 토큰입니다.'}

        return {'success': True, 'message': '공유 링크가 차단되었습니다.'}
    except Exception as e:
        return {'success': False, 'error': log_error(e, 'update')}
