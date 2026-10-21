#!/bin/sh
# PGT backend shell entry:
#   1) /opt/pgt/whl changed since the last install: install its wheels (pgt + extensions);
#      dependencies missing in this image come from /opt/pgt/whl, else from the pip mirror (PIP_INDEX_URL)
#   2) run the backend: python -m pgt.app --env prod, working dir $PGT_DATA_DIR
# Update: replace the wheels in backend/whl, then restart the container.
set -e
WHL_DIR=/opt/pgt/whl
STAMP=/opt/pgt/installed.sha256
INDEX=${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}

if ! ls "$WHL_DIR"/*.whl >/dev/null 2>&1; then
    echo "[ERROR] no .whl in $WHL_DIR (mount backend/whl there)"
    exit 1
fi
n=$(ls "$WHL_DIR"/pgt-*.whl 2>/dev/null | wc -l)
if [ "$n" -ne 1 ]; then
    echo "[ERROR] $WHL_DIR must hold exactly one pgt-*.whl, found $n"
    exit 1
fi

sum=$(cd "$WHL_DIR" && ls -1 *.whl | sort | xargs sha256sum | sha256sum | cut -d' ' -f1)
if [ "$(cat "$STAMP" 2>/dev/null)" = "$sum" ]; then
    echo "[INFO] wheels unchanged, skip install"
else
    echo "[INFO] installing wheels from $WHL_DIR:"
    ls -1 "$WHL_DIR"/*.whl
    # the wheels in WHL_DIR replace the installed ones (also the same version)
    pip install --no-cache-dir --no-index --find-links "$WHL_DIR" --force-reinstall --no-deps "$WHL_DIR"/*.whl
    # dependencies of pgt that this image does not have yet
    if ! pip install --no-cache-dir --find-links "$WHL_DIR" --index-url "$INDEX" --timeout 15 --retries 1 "$WHL_DIR"/pgt-*.whl; then
        echo "[ERROR] installing the dependencies of pgt failed (no wheel in $WHL_DIR and $INDEX not reachable?)"
        exit 1
    fi
    if ! pip check; then
        echo "[ERROR] a dependency of these wheels is missing; put its wheel into backend/whl or rebuild the image with docker_image_backend_build.bat"
        exit 1
    fi
    echo "$sum" > "$STAMP"
fi

mkdir -p "$PGT_DATA_DIR"
cd "$PGT_DATA_DIR"
echo "[INFO] python -m pgt.app --env prod (PGT_DATA_DIR=$PGT_DATA_DIR, COLLECTOR_EMBEDDED=${COLLECTOR_EMBEDDED:-from .env.prod})"
exec python -m pgt.app --env prod "$@"
