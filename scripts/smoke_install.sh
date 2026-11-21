#!/usr/bin/env bash
# Install a clickops wheel into a fresh virtual environment and run it, the way `pipx install`
# would: `clickops --version` must print the version and `clickops doctor` must run (it reports
# failing checks with fix hints when there are no credentials or config, and exits 1).
#
#   scripts/smoke_install.sh dist/clickops-0.1.0-py3-none-any.whl
set -euo pipefail

WHEEL=${1:?usage: smoke_install.sh <wheel>}
DIR=$(mktemp -d)
trap 'rm -rf "$DIR"' EXIT

# clickops needs Python 3.12 or newer; prefer uv, which can provide it, over the system python3.
if command -v uv > /dev/null; then
  uv venv --quiet --python 3.12 "$DIR/venv"
  uv pip install --quiet --python "$DIR/venv/bin/python" "$WHEEL"
else
  python3 -m venv "$DIR/venv"
  "$DIR/venv/bin/pip" install --quiet "$WHEEL"
fi

"$DIR/venv/bin/clickops" --version

# No credentials and no config here, so doctor must fail with a readable report, not crash.
set +e
OUTPUT=$(cd "$DIR" && AWS_CONFIG_FILE=/dev/null AWS_SHARED_CREDENTIALS_FILE=/dev/null \
  AWS_ACCESS_KEY_ID= AWS_SECRET_ACCESS_KEY= "$DIR/venv/bin/clickops" doctor 2>&1)
CODE=$?
set -e
echo "$OUTPUT"
if [ "$CODE" -ne 1 ]; then
  echo "FAIL: clickops doctor exited with $CODE, expected 1 (checks failed, no crash)" >&2
  exit 1
fi
echo "$OUTPUT" | grep -q "clickops doctor" || { echo "FAIL: no doctor report" >&2; exit 1; }
echo "OK: the wheel installs and clickops runs"
