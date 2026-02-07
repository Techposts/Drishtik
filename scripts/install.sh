#!/usr/bin/env bash
# =============================================================================
# Frigate → OpenClaw → AI Security Pipeline — Installer Wrapper
# =============================================================================
# Runs prerequisite checks, then launches the pipeline setup.
#
# Run: bash install.sh
# =============================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PREREQS="$ROOT_DIR/setup-frigate-ai-prereqs.sh"
PIPELINE="$ROOT_DIR/setup-frigate-ai.sh"

if [[ ! -f "$PREREQS" ]]; then
  echo "Missing: $PREREQS"
  exit 1
fi

if [[ ! -f "$PIPELINE" ]]; then
  echo "Missing: $PIPELINE"
  exit 1
fi

echo ""
echo "==> Running prerequisite checks..."
bash "$PREREQS"

echo ""
read -r -p "Proceed to pipeline setup now? [Y/n]: " CONT
CONT="${CONT:-Y}"
if [[ "$CONT" =~ ^[Nn] ]]; then
  echo "Cancelled."
  exit 0
fi

echo ""
echo "==> Running pipeline setup..."
bash "$PIPELINE"
