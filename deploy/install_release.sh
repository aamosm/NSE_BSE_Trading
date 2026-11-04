#!/bin/sh
# Install a pinned, reviewed commit as a new release and switch to it. Run as root:
#   sh install_release.sh <full-commit-sha-or-tag>
# Never deploys a moving branch name automatically; the previous release is kept for rollback.
set -eu

REF=${1:?usage: install_release.sh <commit-or-tag>}
REPO_URL=${REPO_URL:-https://github.com/aamosm/NSE_BSE_Trading.git}
BASE=/opt/marketlab
REPO=$BASE/repo

if [ "$(id -u)" -ne 0 ]; then echo "Run as root" >&2; exit 1; fi
case "$REF" in main|master|HEAD|cash-research-reset) echo "Pin a commit SHA or tag, not a branch" >&2; exit 1;; esac

[ -d "$REPO/.git" ] || git clone --no-checkout "$REPO_URL" "$REPO"
git -C "$REPO" fetch --tags --prune origin
SHA=$(git -C "$REPO" rev-parse --verify "$REF^{commit}")
DEST=$BASE/releases/$SHA

if [ ! -d "$DEST" ]; then
  TMP=$(mktemp -d "$BASE/releases/.new-XXXXXX")
  git -C "$REPO" archive "$SHA" | tar -x -C "$TMP"
  python3 -m venv "$TMP/.venv"
  "$TMP/.venv/bin/pip" install --quiet --disable-pip-version-check -r "$TMP/requirements-dev.lock"
  # Targeted self-check of the boundaries that matter on a server (no network, no account access).
  (cd "$TMP" && PYTHONPATH="$TMP/src" "$TMP/.venv/bin/python" -m pytest -q -p no:cacheprovider \
      tests/test_boundaries.py tests/test_login_flow.py tests/test_webapp.py tests/test_service.py)
  echo "$SHA" > "$TMP/RELEASE"
  chmod -R go-w "$TMP"
  mv "$TMP" "$DEST"
fi

# Atomic switch; remember the previous release for rollback.
if [ -L "$BASE/current" ]; then
  readlink -f "$BASE/current" > "$BASE/previous_release"
fi
ln -sfn "$DEST" "$BASE/current.new"
mv -T "$BASE/current.new" "$BASE/current"

install -m 644 "$DEST/deploy/marketlab-scheduler.service" "$DEST/deploy/marketlab-web.service" \
  "$DEST/deploy/marketlab-backup.service" "$DEST/deploy/marketlab-backup.timer" /etc/systemd/system/
[ -f /etc/marketlab/marketlab.conf ] || install -m 644 "$DEST/deploy/marketlab.conf.example" /etc/marketlab/marketlab.conf
systemctl daemon-reload
systemctl enable marketlab-scheduler marketlab-web marketlab-backup.timer
systemctl restart marketlab-web marketlab-scheduler
systemctl start marketlab-backup.timer

sleep 3
if curl -fsS http://127.0.0.1:8765/health | grep -q '"live_orders": false'; then
  echo "Release $SHA is live."
else
  echo "Health check failed; run deploy/rollback.sh" >&2
  exit 1
fi
