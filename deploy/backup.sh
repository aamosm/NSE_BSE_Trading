#!/bin/sh
# Nightly encrypted off-server backup. Runs as user marketlab from marketlab-backup.timer.
# Contents: the scheduler's consistent SQLite copies (evidence, catalog) made at 23:30, the security master,
# and exchange files received in the last 2 days. Excluded: .env, Kite session, login states (recreate by hand).
# Encrypted with age to BACKUP_RECIPIENT (private key kept OFF the server), uploaded with rclone.
set -eu
: "${BACKUP_REMOTE:?set BACKUP_REMOTE in /etc/marketlab/marketlab.conf}"
: "${BACKUP_RECIPIENT:?set BACKUP_RECIPIENT in /etc/marketlab/marketlab.conf}"
DATA=/var/lib/marketlab
DAY=$(date +%F)
SNAP=$DATA/backups/$DAY
OUT=$DATA/backups/marketlab-$DAY.tar.gz.age
[ -d "$SNAP" ] || { echo "No SQLite snapshot for $DAY (scheduler backup job did not run)" >&2; exit 1; }

LIST=$(mktemp)
trap 'rm -f "$LIST"' EXIT
( cd "$DATA" && echo "backups/$DAY" && { [ -f market/master.sqlite3 ] && echo market/master.sqlite3 || true; } \
  && find market/raw -type f -mtime -2 ) > "$LIST"
tar -C "$DATA" -czf - -T "$LIST" | age -r "$BACKUP_RECIPIENT" -o "$OUT.part"
mv "$OUT.part" "$OUT"
rclone copy --no-traverse "$OUT" "$BACKUP_REMOTE/"
# Keep two weeks locally; the remote keeps everything unless you add a lifecycle rule.
find "$DATA/backups" -maxdepth 1 -mtime +14 \( -name 'marketlab-*.tar.gz.age' -o -type d -name '20*' \) \
  -exec rm -rf {} +
echo "Backup $OUT uploaded to $BACKUP_REMOTE"
