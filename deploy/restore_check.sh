#!/bin/sh
# Prove a backup can be restored. Run where the age PRIVATE key is (your laptop under WSL/Git Bash, or a
# fresh server), never by leaving the private key on the production server:
#   sh restore_check.sh marketlab-2026-11-05.tar.gz.age ~/marketlab-backup.key [restore_dir]
set -eu
ARCHIVE=${1:?archive}
KEY=${2:?age identity file}
DIR=${3:-$(mktemp -d)}
mkdir -p "$DIR"
age -d -i "$KEY" "$ARCHIVE" | tar -xz -C "$DIR"
STATUS=0
for db in "$DIR"/backups/*/evidence.sqlite3 "$DIR"/backups/*/catalog.sqlite3; do
  [ -f "$db" ] || continue
  RESULT=$(sqlite3 "$db" 'PRAGMA integrity_check;')
  ROWS=$(sqlite3 "$db" 'SELECT count(*) FROM observations;')
  echo "$(basename "$db"): integrity=$RESULT observations=$ROWS"
  [ "$RESULT" = "ok" ] || STATUS=1
done
echo "Restored into $DIR"
exit $STATUS
