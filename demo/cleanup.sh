#!/usr/bin/env bash
# Deletes the demo bucket named in CLICKOPS_DEMO_BUCKET and the generated imports/ folder.
set -euo pipefail
: "${CLICKOPS_DEMO_BUCKET:?CLICKOPS_DEMO_BUCKET is not set}"
case "$CLICKOPS_DEMO_BUCKET" in clickops-demo-*) ;; *) echo "refusing: not a demo bucket" >&2; exit 1 ;; esac
aws s3api delete-bucket --bucket "$CLICKOPS_DEMO_BUCKET" --region ap-south-1
rm -rf imports
