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
lines = text.splitlines()[-100:]
message = "\n".join(lines)[-12000:]
message = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
print(f"::error title=Gradle failure::{message}")
PY
fi
exit "$status"
