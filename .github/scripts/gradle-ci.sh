#!/usr/bin/env bash
set -u -o pipefail

label="${1:?usage: gradle-ci.sh LABEL TASK...}"
shift
mkdir -p ci-logs
log_file="ci-logs/${label}.log"
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
markers = (
    "FAILURE: Build failed", "* What went wrong:", "* Where:",
    "Execution failed for task", "Could not resolve", "Could not find", "No matching variant",
    "Plugin [id", "error:", "BUILD FAILED",
)
for i, line in enumerate(lines):
    if any(marker in line for marker in markers):
        selected.extend(lines[max(0, i - 1):min(len(lines), i + 6)])
if not selected:
    selected = lines[:25] + ["... output excerpt ..."] + lines[-35:]
excerpt = []
for line in selected:
    if not excerpt or excerpt[-1] != line:
        excerpt.append(line)
message = "\n".join(excerpt)
if len(message) > 12000:
    message = message[:8000] + "\n... diagnostics truncated ...\n" + message[-3500:]
message = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
print(f"::error title=Gradle failure::{message}")
PY
fi
exit "$status"
