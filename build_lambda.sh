#!/usr/bin/env bash
# =============================================================================
# build_lambda.sh
# Packages pypdf into src/package/ and zips both Lambda functions for Terraform.
#
# Run this script from the terraform/ directory before `terraform apply`.
# Prerequisites: Python 3, pip
#
# Usage:
#   chmod +x build_lambda.sh
#   ./build_lambda.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="${SCRIPT_DIR}/src"
PACKAGE_DIR="${SRC_DIR}/package"

echo "==> Build directory: ${SRC_DIR}"

# ─────────────────────────────────────────────
# Step 1: Install pypdf into src/package/
# ─────────────────────────────────────────────
echo "==> Installing pypdf into ${PACKAGE_DIR}/"
mkdir -p "${PACKAGE_DIR}"
pip install pypdf --target "${PACKAGE_DIR}" --upgrade --quiet
echo "    pypdf installed successfully"

# ─────────────────────────────────────────────
# Step 2: Package claims processor Lambda
# The zip must include:
#   - lambda_function.py  (handler at root)
#   - package/            (vendored pypdf)
# ─────────────────────────────────────────────
echo "==> Packaging claims processor Lambda → src/lambda_function.zip"
cd "${SRC_DIR}"
zip -r lambda_function.zip lambda_function.py package/ --quiet
echo "    lambda_function.zip created ($(du -sh lambda_function.zip | cut -f1))"

# ─────────────────────────────────────────────
# Step 3: Package DLQ processor Lambda
# The zip only needs dlq_processor.py — no third-party dependencies.
# ─────────────────────────────────────────────
echo "==> Packaging DLQ processor Lambda → src/dlq_processor.zip"
zip -r dlq_processor.zip dlq_processor.py --quiet
echo "    dlq_processor.zip created ($(du -sh dlq_processor.zip | cut -f1))"

cd "${SCRIPT_DIR}"

echo ""
echo "==> Build complete. Ready to deploy:"
echo "    terraform init"
echo "    terraform plan"
echo "    terraform apply"
