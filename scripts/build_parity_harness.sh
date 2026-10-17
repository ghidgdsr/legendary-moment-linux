#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

JAVA="$ROOT/tools/jdk/bin/javac"
STDLIB="$ROOT/tools/kotlin-stdlib.jar"
CLASSES="$ROOT/tests/jvm/harness-classes"

if [ ! -d tests/jvm/harness-src ]; then
  echo "JVM parity sources are not included in this repository."
  echo "They are decompiled from the APK locally; tests/test_jvm_parity.py will skip."
  exit 0
fi

if [ ! -x "$JAVA" ]; then
  echo "portable JDK missing; run scripts/setup.sh first" >&2
  exit 1
fi

if [ ! -f "$STDLIB" ]; then
  echo "== Downloading kotlin-stdlib 2.0.21 =="
  curl -L --fail --retry 2 -o "$STDLIB" \
    'https://repo1.maven.org/maven2/org/jetbrains/kotlin/kotlin-stdlib/2.0.21/kotlin-stdlib-2.0.21.jar'
fi

mkdir -p "$CLASSES"
"$JAVA" -cp "$STDLIB" -d "$CLASSES" $(find tests/jvm/harness-src -name '*.java')
"$JAVA" -cp "$CLASSES:$STDLIB" -d "$CLASSES" tests/jvm/Parity.java
echo "JVM parity harness built in $CLASSES"
