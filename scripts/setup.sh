#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

APK="传奇一瞬.apk"
JDK_DIR="$ROOT/tools/jdk"
JADX_DIR="$ROOT/tools/jadx"
JDK_URL="https://api.adoptium.net/v3/binary/latest/21/ga/linux/x64/jdk/hotspot/normal/eclipse"
JADX_VERSION="1.5.6"
JADX_URL="https://github.com/skylot/jadx/releases/download/v${JADX_VERSION}/jadx-${JADX_VERSION}.zip"

mkdir -p work/apk vendor/models tools decompiled data/jobs

echo "== Python venv =="
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip wheel
.venv/bin/pip install -r backend/requirements.txt

if [ ! -x "$JDK_DIR/bin/java" ]; then
  echo "== Downloading portable JDK 21 =="
  mkdir -p "$JDK_DIR"
  curl -L --fail --retry 2 -o tools/jdk.tar.gz "$JDK_URL"
  tar -xzf tools/jdk.tar.gz -C "$JDK_DIR" --strip-components=1
  rm -f tools/jdk.tar.gz
fi

if [ ! -x "$JADX_DIR/bin/jadx" ]; then
  echo "== Downloading jadx $JADX_VERSION =="
  mkdir -p "$JADX_DIR"
  curl -L --fail --retry 2 -o tools/jadx.zip "$JADX_URL"
  unzip -q -o tools/jadx.zip -d "$JADX_DIR"
  rm -f tools/jadx.zip
fi

MODELS=(
  legendary-1.0-depth.fp16.onnx
  legendary-1.0-arnet.fp16.onnx
  legendary-1.0-gan.fp16.onnx
)
have_models=true
for m in "${MODELS[@]}"; do
  [ -f "vendor/models/$m" ] || have_models=false
done

if [ -f "$APK" ]; then
  echo "== Unpacking APK =="
  unzip -o -q "$APK" -d work/apk
  cp work/apk/assets/leica/legendary-1.0-depth.fp16.onnx \
     work/apk/assets/leica/legendary-1.0-arnet.fp16.onnx \
     work/apk/assets/leica/legendary-1.0-gan.fp16.onnx \
     vendor/models/
elif [ "$have_models" = true ]; then
  echo "== APK not found; using models already in vendor/models =="
else
  echo "找不到 $APK，且 vendor/models 不完整。" >&2
  echo "请把 APK 放到项目根目录，或恢复 vendor/models 下的三个模型。" >&2
  exit 1
fi

echo "== Verifying models =="
cd vendor/models
sha256sum -c <<'EOF'
70a6f853e9cb51d729055e48050b98c31d1bf29e5160d1b774253ce413d18a6d  legendary-1.0-depth.fp16.onnx
a3aa5fa6a0818f36dbfa4be4dd5471d874cea5981357b7aeb28919954e70d05c  legendary-1.0-arnet.fp16.onnx
0cd65fb1215c04261735e6b2fa81c86646208bbf5d9a3339a56df6ee348ebd20  legendary-1.0-gan.fp16.onnx
EOF

echo "== JVM parity harness =="
bash "$ROOT/scripts/build_parity_harness.sh"

echo "== Done =="
"$JDK_DIR/bin/java" -version
JAVA_HOME="$JDK_DIR" PATH="$JDK_DIR/bin:$PATH" "$JADX_DIR/bin/jadx" --version
