#!/bin/bash
# Daily backup — add to crontab: 0 3 * * * /opt/agent-api/scripts/backup.sh

BACKUP_DIR="/opt/agent-api/backups"
DATA_DIR="/opt/agent-api/data"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

if [ -d "$DATA_DIR" ]; then
    tar czf "$BACKUP_DIR/backup-$DATE.tar.gz" -C /opt/agent-api data/ 2>/dev/null
    echo "[$(date)] Backup created: backup-$DATE.tar.gz"
else
    echo "[$(date)] No data directory at $DATA_DIR — skipping backup"
fi

# Rotation: keep last 7 days
find "$BACKUP_DIR" -name "backup-*.tar.gz" -mtime +7 -delete 2>/dev/null
