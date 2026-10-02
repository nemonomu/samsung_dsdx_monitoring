"""
DS Layer 4 Report Services: 보고서 관리 비즈니스 로직
"""
import paramiko
from datetime import datetime, timedelta, date
from apps.common.response import log_error
from config.config import FILE_SERVER_CONFIG
from . import report_repositories

def get_file_info_for_date(target_date):
    """특정 날짜의 리테일러별 파일 정보 조회 (SFTP)
    Returns: (file_info dict, duplicate_retailers list)
    """
    date_folder = target_date.strftime('%Y%m%d')
    file_info = {}
    file_count = {}

    try:
        transport = paramiko.Transport((FILE_SERVER_CONFIG['host'], FILE_SERVER_CONFIG['port']))
        transport.connect(username=FILE_SERVER_CONFIG['username'], password=FILE_SERVER_CONFIG['password'])
        sftp = paramiko.SFTPClient.from_transport(transport)
        base_path = FILE_SERVER_CONFIG['upload_path']

        targets = report_repositories.get_monitoring_targets()
        retailer_map = {}
        for t in targets:
            country = t[4].lower() if t[4] else ''
            mall = t[5].lower().replace(' ', '_').replace('-', '') if t[5] else ''
            key = f"{country}_{mall}"
            retailer_map[key] = t[1]

        try:
            country_dirs = sftp.listdir(base_path)
        except Exception:
            country_dirs = []

        for country_code in country_dirs:
            country_path = f"{base_path}/{country_code}"
            try:
                stat = sftp.stat(country_path)
                if not (stat.st_mode & 0o40000): continue
            except Exception:
                continue

            date_path = f"{country_path}/{date_folder}"
            try:
                sftp.stat(date_path)
            except FileNotFoundError:
                continue

            try:
                files = sftp.listdir_attr(date_path)
                zip_files = [f for f in files if f.filename.endswith('.zip') and not (f.st_mode & 0o40000)]

                for f in zip_files:
                    filename = f.filename
                    parts = filename.replace('.zip', '').split('_')
                    if len(parts) >= 4:
                        file_country = parts[2]
                        file_retailer = '_'.join(parts[3:])
                        retailer_key = f"{file_country}_{file_retailer}"
                        retailer_name = retailer_map.get(retailer_key, file_retailer)
                    else:
                        retailer_name = country_code.upper()

                    file_count[retailer_name] = file_count.get(retailer_name, 0) + 1
                    file_info[retailer_name] = {
                        'file_name': filename,
                        'file_size': f.st_size
                    }
            except Exception:
                continue

        sftp.close()
        transport.close()
    except Exception as e:
        log_error(e)

    duplicate_retailers = [r for r, cnt in file_count.items() if cnt > 1]
    return file_info, duplicate_retailers

def is_report_closed(target_date, existing=None):
    """보고서 마감 여부 외부 도메인 노출용"""
    return report_repositories.is_report_closed(target_date, existing)

def save_file_info(crawl_date, user_id):
    """파일서버에서 파일 정보 조회 후 리테일러별 정보 DB 업데이트"""
    try:
        if not crawl_date:
            return {'success': False, 'error': 'crawl_date가 필요합니다.'}

        target_date = datetime.strptime(crawl_date, '%Y-%m-%d').date()
        file_info_cache, duplicate_retailers = get_file_info_for_date(target_date)
        targets = report_repositories.get_monitoring_targets()

        return report_repositories.execute_save_file_info(crawl_date, user_id, file_info_cache, targets, duplicate_retailers)
    except Exception as e:
        log_error(e)
        return {'success': False, 'error': str(e)}

def close_report(crawl_date, user_id, content=None):
    """보고서 마감 진행"""
    try:
        if not crawl_date:
            return {'success': False, 'error': 'crawl_date가 필요합니다.'}
        datetime.strptime(crawl_date, '%Y-%m-%d')
        if not isinstance(content, str) or not content.strip():
            return {'success': False, 'error': '마감할 보고서 내용이 필요합니다. 보고서 출력을 다시 열어주세요.'}
        return report_repositories.execute_close_report(crawl_date, user_id, content)
    except Exception as e:
        log_error(e)
        return {'success': False, 'error': str(e)}

def cancel_close_report(crawl_date, user_id, memo):
    """보고서 마감 취소"""
    try:
        if not crawl_date:
            return {'success': False, 'error': 'crawl_date가 필요합니다.'}
        return report_repositories.execute_cancel_close_report(crawl_date, user_id, memo)
    except Exception as e:
        log_error(e)
        return {'success': False, 'error': str(e)}

def update_report(body):
    """이상치 데이터 메모/원인 일괄/단건 수정"""
    try:
        user_id = body.get('user_id', 'system')
        return report_repositories.update_anomaly_report(body, user_id)
    except Exception as e:
        log_error(e)
        return {'success': False, 'error': str(e)}

def update_daily_memo(body):
    """일별 리테일러 보고서 메모 수정"""
    try:
        user_id = body.get('user_id', 'system')
        return report_repositories.update_daily_memo_db(body, user_id)
    except Exception as e:
        log_error(e)
        return {'success': False, 'error': str(e)}

def get_report_list(target_date, retailer_filter, view_mode):
    """저장된 이상치 목록 조회 (복합 뷰 반환)"""
    if not target_date:
        target_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    if not view_mode:
        view_mode = 'status'

    try:
        return report_repositories.get_report_list_db(target_date, retailer_filter, view_mode)
    except Exception as e:
        log_error(e)
        return {'success': False, 'error': str(e)}

def get_file_size_history(end_date, days):
    """최근 N일간 리테일러별 파일 용량 모델링 가공 조회"""
    if days is None: days = 7
    try:
        days = max(1, min(int(days), 90))
    except (ValueError, TypeError):
        days = 7

    if not end_date:
        end_date = date.today() - timedelta(days=1)
    
    start_date = end_date - timedelta(days=days - 1)

    try:
        dates = []
        current = start_date
        while current <= end_date:
            dates.append(current.strftime('%Y-%m-%d'))
            current += timedelta(days=1)

        rows = report_repositories.get_file_size_history_db(start_date, end_date)

        retailer_data = {}
        retailer_order = []
        for retailer, crawl_date, file_size in rows:
            if retailer not in retailer_data:
                retailer_data[retailer] = {}
                retailer_order.append(retailer)
            date_key = crawl_date if isinstance(crawl_date, str) else crawl_date.strftime('%Y-%m-%d')
            retailer_data[retailer][date_key] = file_size or 0

        retailers = []
        for retailer in retailer_order:
            sizes = [retailer_data[retailer].get(d, 0) for d in dates]
            valid_sizes = [s for s in sizes if s > 0]
            avg = round(sum(valid_sizes) / len(valid_sizes)) if valid_sizes else 0
            retailers.append({'retailer': retailer, 'sizes': sizes, 'avg': avg})

        return {'dates': dates, 'retailers': retailers}
    except Exception as e:
        log_error(e)
        return {'error': str(e)}
