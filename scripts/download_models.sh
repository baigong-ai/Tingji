#!/usr/bin/env bash
# Pre-download FunASR models from modelscope.cn via git clone.
#
# Why git clone instead of Python's modelscope SDK?
# On macOS, the uv-managed python binary is adhoc-signed, which triggers
# system network restrictions for some users. `git` is Apple-signed and
# uses the system network path, so it works reliably.
#
# After this script finishes, app/asr.py will detect the local directories
# and skip the SDK download path entirely.
set -euo pipefail

cd "$(dirname "$0")/.."

MODELS_DIR="${1:-./models}"
mkdir -p "$MODELS_DIR"

# Ensure git-lfs is initialized (model files are LFS-tracked).
git lfs install >/dev/null 2>&1 || true

clone_one() {
  local url="$1"
  local dest="$2"

  if [ -d "$MODELS_DIR/$dest" ] && \
     find "$MODELS_DIR/$dest" \( -name "*.pt" -o -name "*.bin" -o -name "*.onnx" \) -print -quit 2>/dev/null | grep -q .; then
    echo "[skip] $dest (already downloaded)"
    return 0
  fi

  echo "[download] $dest"
  echo "  from: $url"
  rm -rf "$MODELS_DIR/$dest"
  git clone --depth 1 "$url" "$MODELS_DIR/$dest"
  echo "[ok] $dest ($(du -sh "$MODELS_DIR/$dest" | cut -f1))"
  echo
}

# 1. ASR (paraformer-zh)
clone_one \
  "https://www.modelscope.cn/iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch.git" \
  "paraformer-zh"

# 2. VAD (fsmn-vad)
clone_one \
  "https://www.modelscope.cn/iic/speech_fsmn_vad_zh-cn-16k-common-pytorch.git" \
  "fsmn-vad"

# 3. Punctuation (ct-punc)
clone_one \
  "https://www.modelscope.cn/iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch.git" \
  "ct-punc"

# 4. Speaker embedding (cam++)
clone_one \
  "https://www.modelscope.cn/iic/speech_campplus_sv_zh-cn_16k-common.git" \
  "campp"

echo
echo "All models downloaded to $(cd "$MODELS_DIR" && pwd)"
echo "Total size: $(du -sh "$MODELS_DIR" | cut -f1)"
