#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/package_source.py "${1:-../ChatBridge-2.50.0-source.zip}"
