# -*- coding: utf-8 -*-
"""يتحقق أن وضع التجربة (--demo) يعمل بلا paramiko وبملفات منفصلة."""
import os, sys, shutil, tempfile

# مخرجات هذه المجموعات عربية، وكونسول ويندوز يفتح بترميز قديم (cp1252)
# لا يسعها فتنفجر print قبل أن يبدأ أي فحص. نفرض UTF-8 في كل بيئة.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:          # بايثون قديم أو مخرَج لا يدعم إعادة الضبط
    pass

WORK = tempfile.mkdtemp(prefix="ar730demo_")
APPDIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
shutil.copy(os.path.join(APPDIR, "ar730_manager.py"), WORK)
sys.argv = [os.path.join(WORK, "ar730_manager.py"), "--demo"]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WORK)

import tkinter                                  # noqa
from tkinter import messagebox                  # noqa
import ar730_manager as M                       # noqa

M.paramiko = None                               # كأن المكتبة غير مثبتة إطلاقاً

ok = []
def check(l, c, d=""):
    ok.append(bool(c))
    print(("  ✓ " if c else "  ✗ ") + l + (("   [" + d + "]") if d else ""))

# نعيد ما يفعله main() في فرع --demo بلا mainloop
M.paramiko = M._DemoParamiko()
M.SETTINGS_FILE = os.path.join(WORK, "demo_settings.json")
M.DB_FILE = os.path.join(WORK, "demo_devices.json")
M.LOG_FILE = os.path.join(WORK, "demo_session.log")

app = M.App()
app.demo_mode = True
check("فتح بلا paramiko مثبتة", True)
check("قاعدة بيانات منفصلة", app.db.path.endswith("demo_devices.json"), app.db.path)

app.v_pass.set("wrong")
app.on_connect()
check("يرفض كلمة السر wrong (لتجربة رسالة الفشل)", len(messagebox.errors()) == 1)
messagebox.reset()

app.v_pass.set("anything")
app.on_connect()
check("يتصل بأي كلمة سر أخرى", app.router.connected)
check("اسم الجهاز الوهمي ظاهر", "DEMO" in app.router.hostname, app.router.hostname)
check("حسابات تجريبية جاهزة", len(app.router_users) >= 4, str(sorted(app.router_users)))
check("المجموعات مع ACL", app.router_groups.get("grp_managers") == "3010",
      str(app.router_groups))
check("متصلون تجريبيون", len(app.tv_on.get_children()) == 3,
      "%d صفوف" % len(app.tv_on.get_children()))
check("جدول الأجهزة فيه الموثوقان",
      len(app.tv_dev.get_children()) == 2, str(app.tv_dev.get_children()))
check("جدول البوابة فيه sara", "sara" in app.tv_por.get_children())
check("لا أخطاء", not messagebox.errors(), str(messagebox.errors()))

# نتأكد أن الراوتر الوهمي يفرض قواعد الجهاز الحقيقي
d = M._DemoParamiko.device
d.view = "aaa"
check("يرفض الترتيب المقلوب",
      "normal service type" in d.run("local-user t password cipher X"))
d.run("local-user t service-type 8021x")
check("يرفض كلمة سر تساوي الاسم",
      "same as a user name" in d.run("local-user t password cipher t"))
check("يرفض irreversible-cipher",
      "irreversible" in d.run("local-user t password irreversible-cipher X"))

app._on_close()
print("\nنجح %d من %d" % (sum(ok), len(ok)))
shutil.rmtree(WORK, ignore_errors=True)
sys.exit(0 if all(ok) else 1)
