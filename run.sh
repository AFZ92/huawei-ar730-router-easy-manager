#!/usr/bin/env bash
# تشغيل AR730 Manager على macOS بواجهة Qt الرسمية.
#
#   ./run.sh          التشغيل الحقيقي على الراوتر
#   ./run.sh --demo   وضع التجربة — راوتر وهمي، بلا أي اتصال شبكي
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
    echo "البيئة غير مهيّأة. نفّذ:  uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python paramiko" >&2
    exit 1
fi

exec .venv/bin/python ar730_qt.py "$@"
