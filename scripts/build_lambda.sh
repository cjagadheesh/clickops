#!/usr/bin/env bash
# Build dist/clickops-detector.zip for the arm64 Python 3.12 Lambda.
# Reproducible: an unchanged source tree and lock file give an identical zip (same sha256).
#
#   scripts/build_lambda.sh
set -euo pipefail

cd "$(dirname "$0")/.."
OUT=dist/clickops-detector.zip
BUILD=build/lambda
REQS=build/lambda-requirements.txt

# The Lambda runtime already provides boto3; the CLI-only libraries are not needed there.
SKIP=(boto3 botocore s3transfer jmespath python-dateutil six urllib3
      typer rich click shellingham markdown-it-py mdurl pygments annotated-doc colorama)
SKIP_ARGS=()
for pkg in "${SKIP[@]}"; do SKIP_ARGS+=(--no-emit-package "$pkg"); done

rm -rf "$BUILD"
mkdir -p "$BUILD" dist
uv export --frozen --no-dev --no-hashes --no-emit-project "${SKIP_ARGS[@]}" \
  | grep -v '^ *#' > "$REQS"

uv pip install --quiet --target "$BUILD" --no-deps --only-binary :all: \
  --python-version 3.12 --python-platform aarch64-manylinux2014 -r "$REQS"
cp -R clickops "$BUILD/clickops"

python3 - "$BUILD" "$OUT" <<'PY'
import os
import sys
import zipfile

root, out = sys.argv[1], sys.argv[2]
files = []
for base, dirs, names in os.walk(root):
    dirs[:] = sorted(d for d in dirs if d != "__pycache__")
    files += [os.path.join(base, n) for n in sorted(names) if not n.endswith(".pyc")]

with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    for path in sorted(files):
        info = zipfile.ZipInfo(os.path.relpath(path, root), date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        with open(path, "rb") as fh:
            zf.writestr(info, fh.read())
PY

sha256sum "$OUT"
