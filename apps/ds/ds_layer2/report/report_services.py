"""
DS Layer 2 Report Services: 리테일러 마감 비즈니스 로직
"""
from datetime import datetime, timedelta
from apps.common.db import ds_connection
from apps.common.response import log_error
from apps.ds.ds_layer2.stats.stats_repositories import (
    fetch_batches_for_date, fetch_expected_count,
    fetch_quality_counts, fetch_quality_counts_by_time_range
)
from . import report_repositories
from .anomaly_causes import carry_forward_causes
from apps.ds.ds_layer4.report.report_services import get_file_info_for_date

def get_retailer_stats(cursor, retailer, target_date, include_file_info=False):
    target_row = report_repositories.fetch_target_info(cursor, retailer)
    if not target_row: return None
    retailer_id, table_name, country, mall_name = target_row

    batches_by_retailer = fetch_batches_for_date(target_date)
    retailer_batches = batches_by_retailer.get(retailer, [])
    batch_count = len(retailer_batches)
    rerun_count = max(0, batch_count - 1)

    total_quality = fetch_quality_counts(cursor, table_name, target_date)
    if batch_count >= 2:
        final_quality = fetch_quality_counts_by_time_range(cursor, table_name, target_date, retailer_batches[-1]['start_time'], None)
        final_batch_count, quality = final_quality.get('total', 0), final_quality
    else:
        final_batch_count, quality = total_quality.get('total', 0), total_quality

    expected_count = fetch_expected_count(cursor, country, mall_name)
    completion_rate = round((final_batch_count / expected_count * 100), 2) if expected_count > 0 else 0

    null_union = quality.get('null_union', 0)
    imageurl_invalid = quality.get('imageurl_invalid', 0)
    price_zero = quality.get('price_zero', 0)
    partial_null = quality.get('partial_null', 0)
    anomaly_total = null_union + imageurl_invalid + price_zero + partial_null

    file_name, file_size = '', 0
    if include_file_info:
        retailer_file = get_file_info_for_date(target_date).get(retailer, {})
        file_name, file_size = retailer_file.get('file_name', ''), retailer_file.get('file_size', 0)

    return {
        'retailer_id': retailer_id, 'expected_count': expected_count, 'total_count': total_quality.get('total', 0),
        'final_batch_count': final_batch_count, 'completion_rate': completion_rate, 'rerun_count': rerun_count,
        'anomaly_total': anomaly_total, 'anomaly_title_null': null_union, 'anomaly_image_null': quality.get('imageurl_null', 0),
        'anomaly_partial_null': partial_null, 'anomaly_price_zero': price_zero, 'file_name': file_name, 'file_size': file_size
    }

def save_retailer(crawl_date, retailer, anomalies, memo, user_id):
    try:
        if not crawl_date or not retailer: return {'success': False, 'error': '필수 파라미터 누락'}
        with ds_connection() as (conn, cursor):
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            target_date = datetime.strptime(crawl_date, '%Y-%m-%d').date()
            stats = get_retailer_stats(cursor, retailer, target_date, include_file_info=False)
            if not stats: return {'success': False, 'error': f'{retailer} 타겟을 찾을 수 없습니다.'}

            if anomalies:
                previous_anomalies = report_repositories.fetch_previous_anomalies_with_causes(
                    cursor,
                    target_date - timedelta(days=1),
                    stats['retailer_id'],
                )
                anomalies = carry_forward_causes(anomalies, previous_anomalies)

            report_daily_id, anomaly_ids = report_repositories.db_save_retailer_transaction(crawl_date, stats['retailer_id'], stats, anomalies, memo, user_id, now, cursor, conn)
            return {'success': True, 'message': f'{retailer} 저장 완료', 'report_daily_id': report_daily_id, 'anomaly_count': len(anomaly_ids), 'anomaly_ids': anomaly_ids}
    except Exception as e:
        log_error(e)
        return {'success': False, 'error': str(e)}

def delete_retailer(crawl_date, retailer, user_id):
    try:
        if not crawl_date or not retailer: return {'success': False, 'error': '필수 파라미터 누락'}
        with ds_connection() as (conn, cursor):
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            target_row = report_repositories.fetch_target_info(cursor, retailer)
            if not target_row: return {'success': False, 'error': f'{retailer} 타겟을 찾을 수 없습니다.'}
            daily_d, anomaly_d = report_repositories.db_delete_retailer_transaction(crawl_date, target_row[0], user_id, now, cursor, conn)
            return {'success': True, 'message': f'{retailer} 삭제 완료', 'daily_deleted': daily_d, 'anomaly_deleted': anomaly_d}
    except Exception as e:
        log_error(e)
        return {'success': False, 'error': str(e)}

def get_retailer_save_status(target_date):
    if not target_date: target_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    saved_retailers = report_repositories.fetch_retailer_save_status(target_date)
    return {'success': True, 'date': target_date, 'saved_retailers': saved_retailers if saved_retailers is not None else {}}
