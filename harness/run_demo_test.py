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
shutil.copytree(os.path.join(APPDIR, "data"), os.path.join(WORK, "data"))
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

check("الجهاز المحظور تجريبياً ظاهر",
      "blocked" in app.tv_dev.item("00005e005303", "tags"))

# تغيير كلمة السر وتعميمها يعمل على الراوتر الوهمي ويفكّ الحظر
_Real = M.FieldDialog
class _Filled(_Real):
    def __init__(self, parent, title, fields):
        self.fields = fields
        _Real.__init__(self, parent, title, fields)
    def wait_window(self, w=None):
        self._vars["pw"].set("Train-Pass-9"); self._vars["pw2"].set("Train-Pass-9")
        self._ok()
M.FieldDialog = _Filled
app.on_rotate_mac_password()
M.FieldDialog = _Real
dv = M._DemoParamiko.device
check("تغيير كلمة السر بلا أخطاء", not messagebox.errors(), str(messagebox.errors()))
check("الملف التجريبي تغيّر", dv.profiles["m_wl"] == "Train-Pass-9")
check("فُكّ الحظر التجريبي", dv.users["00005e005303"].get("state") == "A")

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

# تبويب الخطوط: WAN1 محجوب وWAN3 مخنوق عمداً في وضع التجربة
messagebox.reset()
lines = app.on_check_lines()
verdicts = {l["gw"]: l["verdict"] for l in (lines or [])}
check("فحص الخطوط التجريبية", verdicts.get("192.168.1.1") == "blocked"
      and verdicts.get("192.168.4.1") == "ok", str(verdicts))
check("الخط المخنوق يظهر في وضع التجربة", verdicts.get("192.168.3.1") == "throttled",
      str(verdicts))
check("فحص الخطوط بلا أخطاء", not messagebox.errors(), str(messagebox.errors()))

# أجهزة الإدارة على الراوتر الوهمي: الجهاز الموثوق المتصل يصبح جهاز إدارة
messagebox.reset()
class _Mgmt(_Real):
    def __init__(self, parent, title, fields):
        self.fields = fields
        _Real.__init__(self, parent, title, fields)
    def wait_window(self, w=None):
        for k, v in {"mac": "0000-5e00-5302", "name": "Demo", "net": "Vlanif20", "ip": "",
                     "acl": "2999"}.items():
            self._vars[k].set(v)
        self._ok()
M.FieldDialog = _Mgmt
app.on_add_mgmt()
M.FieldDialog = _Real
dm = M._DemoParamiko.device.mgmt
check("جهاز إدارة تجريبي بلا أخطاء", not messagebox.errors(), str(messagebox.errors()))
check("قاعدة ACL تجريبية", 100 in dm.acls["2999"]["rules"], str(dm.acls["2999"]["rules"]))
check("الجدول يعرضه جاهزاً", app.tv_mgmt.get_children() and
      app.tv_mgmt.item(app.tv_mgmt.get_children()[0], "tags") == ("ok",))

# المتّصلون حسب الشبكة على الراوتر الوهمي
messagebox.reset()
app.on_refresh_vlans()
check("قائمة الشبكات في وضع التجربة", len(app.cb_vlan["values"]) == 7,
      str(list(app.cb_vlan["values"])))
app.v_vlan.set([i for i in app.cb_vlan["values"] if i.startswith("VLAN 20")][0])
app.on_pick_vlan()
kinds = [app.tv_vlan.item(i, "values")[5] for i in app.tv_vlan.get_children()]
check("جهاز بلا عنوان يظهر في الجدول", app.T["vlan_kind_none"] in kinds, str(kinds))
check("قراءة الشبكات بلا أخطاء", not messagebox.errors(), str(messagebox.errors()))

# عقد هذا الجهاز أُطلق في اختبار جهاز الإدارة أعلاه، فنعيده كي يعود له
# عقدان: واحد في شبكته وآخر في شبكة الإدارة
dm.leases["20"]["10.0.20.166"] = "0000-5e00-5302"
app.on_pick_vlan()
app.on_scan_overlap()
check("فحص التداخل يكشف جهاز الشبكتين في وضع التجربة",
      "00005e005302" in app.overlap["dups"], str(list(app.overlap["dups"])))
check("وخانة «شبكات أخرى» تمتلئ",
      "VLAN 1" in app.tv_vlan.item("00005e005302", "values")[8],
      str(app.tv_vlan.item("00005e005302", "values")))
check("فحص التداخل بلا أخطاء", not messagebox.errors(), str(messagebox.errors()))

app._on_close()
print("\nنجح %d من %d" % (sum(ok), len(ok)))
shutil.rmtree(WORK, ignore_errors=True)
sys.exit(0 if all(ok) else 1)
