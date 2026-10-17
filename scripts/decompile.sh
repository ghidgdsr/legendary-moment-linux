#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ ! -x tools/jdk/bin/java ] || [ ! -x tools/jadx/bin/jadx ]; then
  echo "tools missing; run scripts/setup.sh first" >&2
  exit 1
fi
if [ ! -f work/apk/classes3.dex ]; then
  echo "APK not extracted; run scripts/setup.sh first" >&2
  exit 1
fi

rm -rf decompiled/app
set +e
JAVA_HOME="$ROOT/tools/jdk" PATH="$ROOT/tools/jdk/bin:$PATH" \
  tools/jadx/bin/jadx -d decompiled/app --no-res work/apk/classes3.dex
rc=$?
set -e
if [ ! -f decompiled/app/sources/xyz/shuncongci/leica/LeicaEngine.java ]; then
  echo "jadx did not produce the app sources (exit $rc)" >&2
  exit "$rc"
fi
if [ "$rc" -ne 0 ]; then
  echo "jadx reported $rc (some auxiliary classes failed); app sources are complete." >&2
fi
echo "Decompiled to decompiled/app"
