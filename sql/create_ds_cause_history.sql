-- Preserve the source snapshot when a DS cause is applied. No existing data changes.
CREATE TABLE IF NOT EXISTS ssd_crawl_db.ds_monitoring_cause_history (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    anomaly_id BIGINT NOT NULL,
    application_type VARCHAR(16) NOT NULL,
    cause VARCHAR(255) NOT NULL,
    source_snapshot LONGTEXT NULL,
    applied_at DATETIME NOT NULL,
    applied_by VARCHAR(255) NOT NULL,
    KEY idx_cause_history_anomaly (anomaly_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
