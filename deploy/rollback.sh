#!/bin/sh
# Switch back to the previous release (or a named installed release) and restart. Run as root:
#   sh rollback.sh            # previous release
#   sh rollback.sh <sha>      # a specific installed release under /opt/marketlab/releases
set -eu
BASE=/opt/marketlab
if [ "$(id -u)" -ne 0 ]; then echo "Run as root" >&2; exit 1; fi
if [ $# -ge 1 ]; then TARGET=$BASE/releases/$1; else TARGET=$(cat "$BASE/previous_release"); fi
[ -d "$TARGET" ] || { echo "Release not installed: $TARGET" >&2; exit 1; }
CURRENT=$(readlink -f "$BASE/current")
ln -sfn "$TARGET" "$BASE/current.new"
mv -T "$BASE/current.new" "$BASE/current"
echo "$CURRENT" > "$BASE/previous_release"
systemctl restart marketlab-web marketlab-scheduler
sleep 3
curl -fsS http://127.0.0.1:8765/health && echo " <- rolled back to $(basename "$TARGET")"
