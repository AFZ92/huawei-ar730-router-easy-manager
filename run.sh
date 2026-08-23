#!/usr/bin/env bash
# تشغيل AR730 Manager على macOS.
#
# لماذا هذا السكربت موجود:
#   • Python المرفقة مع macOS تستخدم Tk 8.5 المعطوبة الرسم على النسخ
#     الحديثة من النظام — تعطي نافذة سوداء فارغة. فنستخدم Python 3.12
#     من uv وهي تأتي بـ Tk 9.0.
#   • البيئة المعزولة (venv) لا ترث مسارات مكتبة Tcl من المفسّر الأساسي،
#     فنمرّرها صراحةً عبر TCL_LIBRARY و TK_LIBRARY وإلا فشل الإقلاع بـ
#     "Cannot find a usable init.tcl".
#
#   ./run.sh          التشغيل الحقيقي على الراوتر
#   ./run.sh --demo   وضع التجربة — راوتر وهمي، بلا أي اتصال شبكي
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
    echo "البيئة غير مهيّأة. نفّذ:  uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python paramiko" >&2
    exit 1
fi

BASE="$(.venv/bin/python -c 'import sys; print(sys.base_prefix)')"
export TCL_LIBRARY="$BASE/lib/tcl9.0"
export TK_LIBRARY="$BASE/lib/tk9.0"

exec .venv/bin/python ar730_manager.py "$@"
