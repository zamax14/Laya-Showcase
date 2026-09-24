#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export UV_CACHE_DIR="$PWD/.model-cache/uv"
uv venv --python 3.12 .venv-kev
uv pip install --python .venv-kev/bin/python \
  --index https://download.pytorch.org/whl/cu128 \
  --default-index https://pypi.org/simple \
  --index-strategy unsafe-best-match \
  'torch==2.8.0+cu128' \
  'kev[serve] @ git+https://github.com/jaredpalmer/kev.git@7405b72e73e2d24787f3720d162a21c974ff2ad2' \
  'flash-linear-attention==0.5.2'
# Kev-0.8B es un Qwen3.5 híbrido: sin flash-linear-attention sus capas Gated DeltaNet usan la implementación
# de referencia de PyTorch. Medido en una RTX 4050: 275 → 72 ms por ticket. causal-conv1d solo bajaba a 70 ms
# y necesita compilar con nvcc, así que no se instala.
