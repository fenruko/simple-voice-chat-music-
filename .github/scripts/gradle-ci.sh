#!/usr/bin/env bash
set -u -o pipefail

label="${1:?usage: gradle-ci.sh LABEL TASK...}"
shift
mkdir -p .ci-logs
log_file=".ci-logs/${label}.log"
set +e
gradle "$@" --stacktrace --console=plain 2>&1 | tee "$log_file"
status=${PIPESTATUS[0]}
set -e
if [[ $status -ne 0 ]]; then
  python3 - "$log_file" <<'PY'
from pathlib import Path
import sys
text = Path(sys.argv[1]).read_text(errors="replace")
lines = text.splitlines()
selected = []
for i, line in enumerate(lines):
    marker = any(token in line for token in (
        "FAILURE: Build failed", "* What went wrong:", "* Where:", "* Exception is:",
        "Execution failed for task", "Could not resolve", "Could not find", "No matching variant",
        "Plugin [id", "Caused by:", "error:", "BUILD FAILED", "BUILD SUCCESSFUL",
    ))
    if marker:
        selected.extend(lines[max(0, i - 2):min(len(lines), i + 24)])
if not selected:
    selected = lines[:40] + ["... output excerpt ..."] + lines[-40:]
# Deduplicate overlapping context while retaining order.
excerpt = []
for line in selected:
    if not excerpt or excerpt[-1] != line:
        excerpt.append(line)
message = "\n".join(excerpt)[-12000:]
message = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
print(f"::error title=Gradle failure::{message}")
PY
fi
exit "$status"
