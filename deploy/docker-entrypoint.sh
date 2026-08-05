#!/bin/sh
set -eu

# A hosted persistent disk can mask the image-time /data directory with a new
# root-owned mount. Correct only the configured database directory, then run
# the application as the unprivileged service account.
DB_PATH="${TIDE_DB_PATH:-/data/tide_mem.sqlite3}"
DB_DIR="$(dirname "$DB_PATH")"

case "$DB_DIR" in
  /*) ;;
  *)
    echo "TIDE_DB_PATH must resolve to an absolute directory" >&2
    exit 64
    ;;
esac

if [ "$DB_DIR" = "/" ]; then
  echo "Refusing to change ownership of the filesystem root" >&2
  exit 64
fi

mkdir -p "$DB_DIR"
chown -R tide:tide "$DB_DIR"

exec gosu tide "$@"
