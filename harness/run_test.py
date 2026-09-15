# -*- coding: utf-8 -*-
"""
تشغيل التطبيق كاملاً بلا شاشة أمام راوتر AR730 وهمي.

يضغط الأزرار بالترتيب الذي سيضغطه الموظف، ويتحقق بعد كل خطوة من ثلاثة
مواضع: إعداد الراوتر، جدول الواجهة، وقاعدة البيانات المحلية.
"""
import os, sys, shutil, tempfile

# مخرجات هذه المجموعات عربية، وكونسول ويندوز يفتح بترميز قديم (cp1252)
# لا يسعها فتنفجر print قبل أن يبدأ أي فحص. نفرض UTF-8 في كل بيئة.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:          # بايثون قديم أو مخرَج لا يدعم إعادة الضبط
    pass

WORK = tempfile.mkdtemp(prefix="ar730test_")
APPDIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
shutil.copy(os.path.join(APPDIR, "ar730_manager.py"), WORK)
sys.argv = [os.path.join(WORK, "ar730_manager.py")]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # tkinter+paramiko الوهميان
sys.path.insert(0, WORK)

import tkinter                      # noqa: E402
from tkinter import messagebox, simpledialog   # noqa: E402
import paramiko                     # noqa: E402
import ar730_manager as M           # noqa: E402

DEV = paramiko.FakeAR730()
paramiko.SSHClient.device = DEV

FAILS = []
STEPS = []


def check(label, cond, detail=""):
    STEPS.append((label, bool(cond), detail))
    if not cond:
        FAILS.append(label + (" — " + detail if detail else ""))
    print(("  ✓ " if cond else "  ✗ ") + label + (("   [" + detail + "]") if detail else ""))


def head(t):
    print("\n" + "=" * 68 + "\n" + t + "\n" + "=" * 68)


# ---- حوار الحقول: نملأه سلفاً بدل أن ينتظر المستخدم -------------------------
SCRIPT = []          # قائمة dict أو None (إلغاء)


_RealDialog = M.FieldDialog


class ScriptedDialog(_RealDialog):
    last_fields = []
    last_title = ""

    def __init__(self, parent, title, fields):
        ScriptedDialog.last_fields = fields
        ScriptedDialog.last_title = title
        self.scripted = SCRIPT.pop(0) if SCRIPT else None
        _RealDialog.__init__(self, parent, title, fields)

    def wait_window(self, w=None):
        # النافذة الحقيقية تتوقف هنا حتى يضغط المستخدم؛ نحن نضغط بدلاً عنه
        if self.scripted is None:
            self._cancel()
            return
        for k, v in self.scripted.items():
            if k in self._vars:
                self._vars[k].set(v)
        self._ok()


M.FieldDialog = ScriptedDialog

head("١ — فتح البرنامج")
app = M.App()
check("النافذة بُنيت بلا استثناء", True)
check("ثمانية تبويبات", len(app.nb.tabs_) == 8, "عدد التبويبات: %d" % len(app.nb.tabs_))
check("عناوين أعمدة الأجهزة", len(app.tv_dev.headings) == 6)
check("لا رسائل خطأ عند الإقلاع", not messagebox.errors(), str(messagebox.errors()))

head("٢ — اتصال بكلمة سر خاطئة")
app.v_host.set("10.0.1.1"); app.v_user.set("admin"); app.v_pass.set("wrong")
app.on_connect()
check("رفض الاتصال وأظهر رسالة", len(messagebox.errors()) == 1)
check("بقي غير متصل", not app.router.connected)
messagebox.reset()

head("٣ — اتصال صحيح")
app.v_pass.set("correct-password")
app.on_connect()
check("اتصل", app.router.connected)
check("قرأ اسم الجهاز", app.router.hostname == "AR730", app.router.hostname)
check("أطفأ الترقيم أولاً", any(c == "screen-length 0 temporary" for _, c in DEV.history))
check("مسح كلمة السر من الحقل", app.v_pass.get() == "")
check("قرأ حسابات الراوتر", "00005e005302" in app.router_users)
check("قرأ المجموعات مع ACL", app.router_groups.get("grp_staff") == "3020",
      str(app.router_groups))
check("جدول المتصلين امتلأ", len(app.tv_on.get_children()) == 2)
check("لا أخطاء", not messagebox.errors(), str(messagebox.errors()))

head("٣أ — منع الإضافة بكلمة سر الماك الافتراضية")
check("الإعداد الافتراضي هو القيمة المؤقتة",
      app.v_macpw.get() == M.MAC_PW_PLACEHOLDER, app.v_macpw.get())
before_hist = len(DEV.history)
SCRIPT.append({"mac": "aa:bb:cc:dd:ee:10", "name": "x", "group": "grp_staff", "note": ""})
app.on_add_device()
check("رفض الإضافة برسالة", len(messagebox.errors()) == 1, str(messagebox.errors()))
check("الرسالة توجّه إلى الإعدادات",
      messagebox.errors() and "mac-access-profile" in messagebox.errors()[0][2])
check("لم يُرسَل أي أمر إلى الراوتر", len(DEV.history) == before_hist)
check("لم يُنشأ الحساب", "aabbccddee10" not in DEV.users)
messagebox.reset()
app.v_macpw.set("Old-Shared-1")

head("٤ — إضافة جهاز موثوق (الكمبيوتر 0000-5e00-5301)")
SCRIPT.append({"mac": "00:00:5E:00:53:01", "name": "كمبيوتر الاستقبال",
               "group": "grp_managers", "note": "مكتب الإدارة"})
app.on_add_device()
u = DEV.users.get("00005e005301")
check("الحساب أُنشئ على الراوتر", u is not None)
check("النوع 8021x", u and "8021x" in u["types"], str(u and u["types"]))
check("المجموعة grp_managers", u and u["group"] == "grp_managers")
check("كلمة السر ضُبطت", u and u["pw"])
check("بكلمة السر المشتركة من الإعدادات", u and u.get("pwval") == "Old-Shared-1",
      str(u and u.get("pwval")))
check("كلمة السر مخفية في سجل الأوامر",
      "Old-Shared-1" not in app.txt_log.buffer and "password cipher ******" in app.txt_log.buffer)
order = [c for _, c in DEV.history if c.startswith("local-user 00005e005301")]
check("الترتيب: نوع ← سر ← مجموعة",
      "service-type" in order[0] and "password" in order[1] and "user-group" in order[2],
      " | ".join(x.split()[2] for x in order[:3]))
check("حُفظ الإعداد", DEV.saved)
check("ظهر في جدول الواجهة", "00005e005301" in app.tv_dev.get_children())
row = app.tv_dev.item("00005e005301", "values")
check("الاسم الوصفي في الجدول", "كمبيوتر الاستقبال" in row, str(row))
check("قاعدة البيانات سجّلته نشطاً", app.db.device("00005e005301")["state"] == "active")
check("لا أخطاء", not messagebox.errors(), str(messagebox.errors()))

head("٤أ — إضافة عدة أجهزة متتالية في نفس الجلسة")
# سطر [V300R024C00SPC100] في أول الإعداد كان يُحسب موجّهاً فتنقطع القراءة،
# ويفشل التحقق من الجهاز الثاني فما بعده رغم أنه أُنشئ على الراوتر
for i, mac in enumerate(("00:00:5e:00:53:64", "00:00:5e:00:53:66", "00:00:5e:00:53:60")):
    SCRIPT.append({"mac": mac, "name": "جهاز %d" % i, "group": "grp_staff", "note": ""})
    app.on_add_device()
    m12 = M.normalize_mac(mac)
    check("الجهاز %d أُنشئ وتحقق منه" % (i + 1),
          m12 in DEV.users and not messagebox.errors(), str(messagebox.errors())[:120])
    check("الجهاز %d ظاهر في الجدول ومسجّل محلياً" % (i + 1),
          m12 in app.tv_dev.get_children() and app.db.device(m12) is not None)
check("القناة لم تختل: الموجّه يطابق اسم الجهاز فقط",
      not app.router._s._prompt_re.search("\r\n[V300R024C00SPC100]"))
for mac in ("00005e005364", "00005e005366", "00005e005360"):
    messagebox.answers.append(True)
    simpledialog.replies.append("تنظيف")
    app.tv_dev.selection_set(mac)
    app.on_revoke_device()
    app.db.data["devices"].pop(mac, None)
app._refresh_device_table()
messagebox.reset()

head("٥ — رفض ماك غير صالح ورفض المكرر")
SCRIPT.append({"mac": "12:34:56", "name": "x", "group": "grp_staff", "note": ""})
app.on_add_device()
check("رفض ماك ناقص", len(messagebox.errors()) == 1)
SCRIPT.append({"mac": "0000-5e00-5301", "name": "y", "group": "grp_staff", "note": ""})
app.on_add_device()
check("رفض جهازاً مسجلاً مسبقاً", len(messagebox.errors()) == 2)
messagebox.reset()

head("٦ — تحذير عند ترك المجموعة فارغة")
SCRIPT.append({"mac": "aa:bb:cc:dd:ee:01", "name": "بلا مجموعة", "group": "", "note": ""})
app.on_add_device()
check("حذّر ولم يُنشئ الحساب",
      "aabbccddee01" not in DEV.users and
      any(c[0] == "warning" for c in messagebox.calls))
messagebox.reset()

head("٧ — نقل الجهاز إلى مجموعة الموظفين")
before_cuts = len(DEV.cut_log)
app.tv_dev.selection_set("00005e005301")
SCRIPT.append({"group": "grp_staff"})
app.on_change_device_group()
check("المجموعة تغيّرت على الراوتر", DEV.users["00005e005301"]["group"] == "grp_staff")
check("فُصلت الجلسة كي تسري الصلاحية",
      any("mac-address 0000-5e00-5301" in c for c in DEV.cut_log[before_cuts:]),
      str(DEV.cut_log[before_cuts:]))
check("أمر cut نُفّذ داخل عرض aaa",
      any(v == "aaa" and c.startswith("cut access-user") for v, c in DEV.history))
check("لا أخطاء", not messagebox.errors(), str(messagebox.errors()))

head("٨ — إلغاء الجهاز")
messagebox.answers.append(True)          # نعم، احذف
simpledialog.replies.append("انتهى عقده")
app.tv_dev.selection_set("00005e005301")
app.on_revoke_device()
check("حُذف من الراوتر فعلاً", "00005e005301" not in DEV.users)
d = app.db.device("00005e005301")
check("بقي في قاعدة البيانات", d is not None)
check("حالته ملغى", d and d["state"] == "revoked")
check("السبب محفوظ", d and d["revoke_reason"] == "انتهى عقده")
check("ما زال ظاهراً في الجدول", "00005e005301" in app.tv_dev.get_children())
check("معلَّم بوسم revoked",
      "revoked" in app.tv_dev.item("00005e005301", "tags"),
      str(app.tv_dev.item("00005e005301", "tags")))
check("لا أخطاء", not messagebox.errors(), str(messagebox.errors()))

head("٩ — حساب بوابة")
SCRIPT.append({"user": "ahmad", "pw": "Str0ng-Pass-1", "name": "موظف المبيعات",
               "group": "grp_staff", "note": "قسم المبيعات"})
app.on_add_portal()
pu = DEV.users.get("ahmad")
check("أُنشئ على الراوتر", pu is not None)
check("النوع web", pu and "web" in pu["types"], str(pu and pu["types"]))
check("المجموعة grp_staff", pu and pu["group"] == "grp_staff")
check("ظهر في جدول البوابة", "ahmad" in app.tv_por.get_children())

SCRIPT.append({"pw": "short"})
app.tv_por.selection_set("ahmad")
app.on_reset_portal_pw()
check("رفض كلمة سر قصيرة", len(messagebox.errors()) == 1)
messagebox.reset()

SCRIPT.append({"pw": "An0ther-Long-Pass"})
app.tv_por.selection_set("ahmad")
app.on_reset_portal_pw()
check("قبل كلمة سر قوية", not messagebox.errors(), str(messagebox.errors()))

SCRIPT.append({"group": "grp_managers"})
app.tv_por.selection_set("ahmad")
app.on_change_portal_group()
check("غيّر مجموعة حساب البوابة", DEV.users["ahmad"]["group"] == "grp_managers")

messagebox.answers.append(True)
simpledialog.replies.append("انتقل لفرع آخر")
app.tv_por.selection_set("ahmad")
app.on_del_portal()
check("حُذف من الراوتر", "ahmad" not in DEV.users)
check("بقي ملغى في قاعدة البيانات", app.db.portal("ahmad")["state"] == "revoked")
check("لا أخطاء", not messagebox.errors(), str(messagebox.errors()))

head("١٠ — جدول المتصلين: توثيق وفصل")
# الجهاز اختفى من الجدول لأن الإلغاء فصله فعلاً — نحاكي إعادة اتصاله
DEV.online.append({"id": "1041", "user": "00005e005301", "ip": "10.0.21.207",
                   "mac": "0000-5e00-5301", "status": "Pre-authen"})
app.on_refresh_online()
rows = app.tv_on.get_children()
check("قرأ المتصلين", len(rows) >= 1, "عدد الصفوف: %d" % len(rows))
target = [r for r in rows if "1041" in str(app.tv_on.item(r, "values"))]
if target:
    app.tv_on.selection_set(target[0])
    SCRIPT.append({"mac": "0000-5e00-5301", "name": "كمبيوتر الاستقبال",
                   "group": "grp_managers", "note": "أُعيد"})
    app.on_trust_online()
    check("زر (وثّق هذا الجهاز) عبّأ الماك تلقائياً", "00005e005301" in DEV.users)
else:
    check("وجد صف الجهاز غير المصادَق", False, "لم يُعثر على 1041")

app.on_refresh_online()
rows = app.tv_on.get_children()
if rows:
    app.tv_on.selection_set(rows[0])
    n_before = len(DEV.online)
    app.on_cut_user()
    check("فصل مستخدماً متصلاً", len(DEV.online) == n_before - 1,
          "%d ← %d" % (n_before, len(DEV.online)))
check("لا أخطاء", not messagebox.errors(), str(messagebox.errors()))

head("١٠ز — إضافة جهاز من جدول المتصلين")
messagebox.reset()
DEV.online.append({"id": "1077", "user": "guest.portal", "ip": "10.0.21.50",
                   "mac": "0000-5e00-5362", "status": "Success"})
app.on_refresh_online()

def _online_row(uid):
    for r in app.tv_on.get_children():
        if str(app.tv_on.item(r, "values")[0]) == uid:
            return r
    return None

r = _online_row("1077")
check("الصف ظاهر في المتصلين", r is not None)

# بلا تحديد: رسالة لا نافذة
app.tv_on.selection_set()
app.on_trust_online()
check("بلا تحديد يطلب اختيار صف", any(c[0] == "info" for c in messagebox.calls))
messagebox.reset()

# الاسم إلزامي في هذا المسار
app.tv_on.selection_set(r)
SCRIPT.append({"name": "", "group": "grp_staff", "note": ""})
app.on_trust_online()
check("رفض الإضافة بلا اسم", "00005e005362" not in DEV.users
      and any(c[2] == app.T["err_need_name"] for c in messagebox.calls))
fields = {f["key"]: f for f in ScriptedDialog.last_fields}
check("النافذة بعنوان المتصلين", ScriptedDialog.last_title == app.T["add_online_title"])
check("الماك للقراءة فقط ومعبّأ", fields["mac"].get("kind") == "readonly"
      and fields["mac"]["default"] == "00:00:5E:00:53:62", str(fields.get("mac")))
check("الـIP والحساب للقراءة فقط", fields["ip"]["default"] == "10.0.21.50"
      and fields["account"]["default"] == "guest.portal"
      and fields["ip"]["kind"] == fields["account"]["kind"] == "readonly")
check("المجموعة قائمة منسدلة", fields["group"]["kind"] == "combo"
      and "grp_staff" in fields["group"]["values"])
messagebox.reset()

# إضافة صحيحة مع قبول فصل الجلسة
r = _online_row("1077")
app.tv_on.selection_set(r)
SCRIPT.append({"mac": "00:00:00:00:00:00", "name": "تاب المبيعات",
               "group": "grp_staff", "note": "من المتصلين"})
messagebox.answers.append(True)
app.on_trust_online()
u = DEV.users.get("00005e005362")
check("أُنشئ بالماك من الصف لا من الحقل", u is not None and "000000000000" not in DEV.users)
check("بالمجموعة المختارة", u and u["group"] == "grp_staff")
check("سُجّل محلياً بالاسم", (app.db.device("00005e005362") or {}).get("name") == "تاب المبيعات")
check("ظهر في الأجهزة الموثوقة", "00005e005362" in app.tv_dev.get_children())
ask = [c for c in messagebox.calls if c[0] == "askyesno"]
check("عرض فصل الجلسة ذاكراً الحساب", ask and "guest.portal" in ask[0][2])
check("فُصلت الجلسة برقمها", any("user-id 1077" in c for c in DEV.cut_log))
check("الجدول تحدّث بعد الفصل", _online_row("1077") is None)
check("لا أخطاء", not messagebox.errors(), str(messagebox.errors()))
messagebox.reset()

# جهاز موثوق مسبقاً: معلومة لا نافذة ولا خطأ
DEV.online.append({"id": "1078", "user": "00005e005362", "ip": "10.0.21.50",
                   "mac": "0000-5e00-5362", "status": "Success"})
app.on_refresh_online()
app.tv_on.selection_set(_online_row("1078"))
ScriptedDialog.last_title = ""
app.on_trust_online()
info = [c for c in messagebox.calls if c[0] == "info"]
check("الموثوق مسبقاً يعطي معلومة باسمه ومجموعته",
      info and "تاب المبيعات" in info[0][2] and "grp_staff" in info[0][2], str(info)[:100])
check("لم تُفتح نافذة إضافة", ScriptedDialog.last_title == "")
check("ولا خطأ", not messagebox.errors())
row_desc = app.tv_on.item(_online_row("1078"), "values")[5]
check("عمود الاسم في المتصلين يعرض الاسم", row_desc == "تاب المبيعات", row_desc)
messagebox.reset()

# رفض فصل الجلسة يُبقيها
DEV.online.append({"id": "1079", "user": "visitor", "ip": "10.0.21.60",
                   "mac": "aabb-ccdd-ee31", "status": "Pre-authen"})
app.on_refresh_online()
app.tv_on.selection_set(_online_row("1079"))
SCRIPT.append({"name": "طابعة", "group": "grp_infra", "note": ""})
messagebox.answers.append(False)
cuts = len(DEV.cut_log)
app.on_trust_online()
check("أُضيف الجهاز", "aabbccddee31" in DEV.users)
check("لم تُفصل الجلسة عند الرفض", len(DEV.cut_log) == cuts and _online_row("1079"))

# النقر المزدوج والقائمة تفتحان نفس المسار
check("النقر المزدوج مربوط", "<Double-1>" in app.tv_on.bindings)
del tkinter.MENUS[:]
y = app.tv_on.get_children().index(_online_row("1079")) * 20 + 5
app.tv_on.event_generate("<Button-3>", x=5, y=y, x_root=0, y_root=0)
labels = [l for l, _ in tkinter.MENUS[-1].entries] if tkinter.MENUS else []
check("القائمة تبدأ ببند الإضافة", labels and labels[0] == app.T["add_online"], str(labels))
del tkinter.MENUS[:]
app.tv_dev.event_generate("<Button-3>", x=5, y=5, x_root=0, y_root=0)
labels = [l for l, _ in tkinter.MENUS[-1].entries] if tkinter.MENUS else []
check("جدول الأجهزة بلا بند الإضافة", app.T["add_online"] not in labels)

for m in ("aabbccddee31", "00005e005362"):
    messagebox.answers.append(True); simpledialog.replies.append("تنظيف")
    app.tv_dev.selection_set(m); app.on_revoke_device()
    app.db.data["devices"].pop(m, None)
DEV.online = [o for o in DEV.online if o["id"] not in ("1078", "1079")]
app.on_refresh_all()
messagebox.reset()

head("١٠أ — كشف الحسابات المحظورة")
DEV.users["00005e005301"]["state"] = "B"
app.on_refresh_all()
check("قرأ حالات الحسابات", app.router_states.get("00005e005301") == "B",
      str(app.router_states))
check("الاسم المقصوص لا يكسر التحليل", "accampus@domain_..." in app.router_states)
row = app.tv_dev.item("00005e005301", "values")
check("الجدول يعرض الحظر", app.T["state_blocked"] in row, str(row))
check("السطر معلَّم بوسم blocked",
      "blocked" in app.tv_dev.item("00005e005301", "tags"))
check("شريط الحالة ينبّه", "1" in app.lbl_status.cget("text"), app.lbl_status.cget("text"))

head("١٠ب — تغيير كلمة السر: رفض المدخلات الخاطئة قبل الراوتر")
for bad, key in (({"profile": "m_wl", "pw": "Abcdef-12", "pw2": "Abcdef-13"}, "err_pw_mismatch"),
                 ({"profile": "m_wl", "pw": "short1", "pw2": "short1"}, "err_pw_weak"),
                 ({"profile": "m_wl", "pw": "abcdefghij", "pw2": "abcdefghij"}, "err_pw_weak"),
                 ({"profile": "m_wl", "pw": "Has Space-1", "pw2": "Has Space-1"}, "err_pw_chars"),
                 ({"profile": "m_wl", "pw": "aa:bb:cc:dd:ee:ff", "pw2": "aa:bb:cc:dd:ee:ff"}, "err_pw_is_mac"),
                 ({"profile": "m_wl", "pw": M.MAC_PW_PLACEHOLDER, "pw2": M.MAC_PW_PLACEHOLDER}, "err_placeholder_pw")):
    messagebox.reset()
    SCRIPT.append(bad)
    app.on_rotate_mac_password()
    errs = messagebox.errors()
    check("رفض: %s" % key, len(errs) == 1 and errs[0][2] == app.T[key],
          str(errs[:1])[:80])
check("الملف لم يتغيّر", DEV.profiles["m_wl"] == "Old-Shared-1")
check("لم يُسأل تأكيد", not any(c[0] == "askyesno" for c in messagebox.calls))
messagebox.reset()

head("١٠ج — تغيير كلمة السر: إلغاء التأكيد لا يلمس الراوتر")
SCRIPT.append({"profile": "m_wl", "pw": "Test*Shared9", "pw2": "Test*Shared9"})
messagebox.answers.append(False)
app.on_rotate_mac_password()
check("الملف لم يتغيّر", DEV.profiles["m_wl"] == "Old-Shared-1")
check("لم تُرسل أوامر mac-authen", not any(c.startswith("mac-authen") for _, c in DEV.history))
messagebox.reset()

head("١٠د — تغيير كلمة السر: الراوتر يرفض كلمة سر الملف")
DEV.reject_profile_pw = True
SCRIPT.append({"profile": "m_wl", "pw": "Test*Shared9", "pw2": "Test*Shared9"})
app.on_rotate_mac_password()
check("أظهر خطأ", len(messagebox.errors()) == 1, str(messagebox.errors()))
check("لم يُمسّ أي حساب",
      all(u.get("pwval") != "Test*Shared9" for u in DEV.users.values()))
check("الإعدادات لم تتغيّر", app.settings["mac_shared_password"] != "Test*Shared9")
check("عاد إلى وضع المستخدم", DEV.view == "user", DEV.view)
DEV.reject_profile_pw = False
messagebox.reset()

head("١٠هـ — تغيير كلمة السر وتعميمها")
DEV.users["aabbccddee20"] = {"types": {"8021x"}, "group": "grp_staff", "pw": True,
                             "pwval": "Old-Shared-1", "state": "A"}
saves = DEV.save_count
SCRIPT.append({"profile": "m_wl", "pw": "Test*Shared9", "pw2": "Test*Shared9"})
app.on_rotate_mac_password()
check("لا أخطاء", not messagebox.errors(), str(messagebox.errors()))
confirm = [c for c in messagebox.calls if c[0] == "askyesno"]
check("سأل تأكيداً يذكر الملف والعدد",
      confirm and "m_wl" in confirm[0][2] and "3" in confirm[0][2],
      confirm and confirm[0][2].replace("\n", " ")[:90])
check("الملف تغيّر", DEV.profiles["m_wl"] == "Test*Shared9")
check("الملف الفارغ لم يُمسّ", DEV.profiles["mac_access_profile"] is None)
macs = [n for n, u in DEV.users.items() if "8021x" in u["types"]]
check("كل حسابات الماك تحمل الجديدة",
      all(DEV.users[m]["pwval"] == "Test*Shared9" for m in macs), str(macs))
check("حساب البوابة لم يُمسّ", DEV.users.get("sara", {}).get("pwval") != "Test*Shared9")
check("المحظور فُكّ حظره", DEV.users["00005e005301"]["state"] == "A")
check("صيغة الملف محفوظة",
      any(c == "mac-authen username macaddress format without-hyphen password cipher Test*Shared9"
          for _, c in DEV.history))
order = [c for _, c in DEV.history if c.startswith("mac-authen") or
         (c.startswith("local-user") and "Test*Shared9" in c)]
check("الملف قبل الحسابات", order and order[0].startswith("mac-authen"))
check("حُفظ الإعداد على الراوتر", DEV.save_count > saves)
check("الإعدادات المحلية تحمل الجديدة", app.settings["mac_shared_password"] == "Test*Shared9"
      and app.v_macpw.get() == "Test*Shared9")
check("عاد إلى وضع المستخدم", DEV.view == "user", DEV.view)
check("الجدول لم يعد يعرض الحظر",
      "blocked" not in app.tv_dev.item("00005e005301", "tags"))
check("كلمة السر الجديدة لا تظهر في السجل", "Test*Shared9" not in app.txt_log.buffer)
check("سُجّلت العملية محلياً",
      any(h.get("action") == "rotate_mac_password" for h in app.db.data["history"]))
messagebox.reset()

head("١٠و — تغيير كلمة السر: حساب يرفض التحديث")
DEV.reject_pw_for = {"aabbccddee20"}
SCRIPT.append({"profile": "m_wl", "pw": "Next-Pass-77", "pw2": "Next-Pass-77"})
app.on_rotate_mac_password()
errs = messagebox.errors()
check("أظهر الحساب الفاشل بالاسم", len(errs) == 1 and "AA:BB:CC:DD:EE:20" in errs[0][2],
      str(errs)[:100])
check("بقية الحسابات تحدّثت", DEV.users["00005e005302"]["pwval"] == "Next-Pass-77")
check("الإعدادات تتبع الملف رغم الفشل الجزئي",
      app.settings["mac_shared_password"] == "Next-Pass-77")
DEV.reject_pw_for = set()
del DEV.users["aabbccddee20"]
app.on_refresh_all()
messagebox.reset()

head("١١ — مجموعات الصلاحيات والسجل والتصدير")
check("جدول المجموعات فيه الثلاث", len(app.tv_grp.get_children()) == 3)
check("سجل الأوامر يمتلئ", len(app.txt_log.buffer) > 500,
      "%d حرفاً" % len(app.txt_log.buffer))
check("السجل يحوي أوامر فعلية", "local-user" in app.txt_log.buffer)
app.on_export("devices")
import tkinter.filedialog as fd
check("صدّر ملف CSV", os.path.exists(fd.path))
if os.path.exists(fd.path):
    data = open(fd.path, encoding="utf-8-sig").read()
    check("الملف يحوي صف الجهاز", "00:00:5E:00:53:01" in data,
          "%d سطراً" % len(data.strip().splitlines()))
    print("\n--- محتوى ملف التصدير ---")
    for ln in data.strip().splitlines():
        print("   " + ln)

head("١٢أ — تعديل الاسم والملاحظة")
mac = "00005e005301"
before_hist = len(DEV.history)
app.tv_dev.selection_set(mac)
SCRIPT.append({"name": "كمبيوتر الاستقبال — الطابق الثاني", "note": "نُقل من مكتب الإدارة"})
app.on_edit_device_meta()
d = app.db.device(mac)
check("الاسم تغيّر في قاعدة البيانات", d["name"] == "كمبيوتر الاستقبال — الطابق الثاني", d["name"])
check("الملاحظة تغيّرت", d["note"] == "نُقل من مكتب الإدارة", d["note"])
check("المجموعة لم تُمسّ", d["group"] == "grp_managers", d["group"])
check("الحالة بقيت نشطة", d["state"] == "active", d["state"])
check("لم يُرسَل أي أمر إلى الراوتر", len(DEV.history) == before_hist,
      "أوامر زائدة: %d" % (len(DEV.history) - before_hist))
row = app.tv_dev.item(mac, "values")
check("الجدول يعرض الاسم الجديد", "كمبيوتر الاستقبال — الطابق الثاني" in row, str(row))
check("الجدول يعرض الملاحظة الجديدة", "نُقل من مكتب الإدارة" in row, str(row))
check("بقي السطر محدَّداً بعد التحديث", app.tv_dev.selection() == (mac,),
      str(app.tv_dev.selection()))
check("لا أخطاء", not messagebox.errors(), str(messagebox.errors()))

head("١٢ب — إلغاء نافذة التعديل لا يغيّر شيئاً")
app.tv_dev.selection_set(mac)
SCRIPT.append(None)          # المستخدم ضغط إلغاء
app.on_edit_device_meta()
check("الاسم كما هو", app.db.device(mac)["name"] == "كمبيوتر الاستقبال — الطابق الثاني")
check("الملاحظة كما هي", app.db.device(mac)["note"] == "نُقل من مكتب الإدارة")

head("١٢ج — التعديل يعمل على جهاز ملغى")
messagebox.answers.append(True)
simpledialog.replies.append("انتهى عقد الموظف")
app.tv_dev.selection_set(mac)
app.on_revoke_device()
check("حُذف من الراوتر", mac not in DEV.users)
app.tv_dev.selection_set(mac)
SCRIPT.append({"name": "كمبيوتر الاستقبال (مؤرشف)", "note": "الجهاز في المخزن"})
app.on_edit_device_meta()
d = app.db.device(mac)
check("الاسم تغيّر رغم الإلغاء", d["name"] == "كمبيوتر الاستقبال (مؤرشف)", d["name"])
check("بقي ملغى — التعديل لا يعيد التفعيل", d["state"] == "revoked", d["state"])
check("سبب الإلغاء محفوظ", d["revoke_reason"] == "انتهى عقد الموظف", d.get("revoke_reason", ""))
row = app.tv_dev.item(mac, "values")
check("العمود يجمع سبب الإلغاء والملاحظة",
      "انتهى عقد الموظف" in str(row) and "الجهاز في المخزن" in str(row), str(row))

head("١٢د — التعديل بلا تحديد سطر")
app.tv_dev.selection_set()
messagebox.reset()
app.on_edit_device_meta()
check("طلب اختيار سطر ولم ينهَر", True)

head("١٢هـ — تعديل حساب بوابة")
messagebox.reset()
SCRIPT.append({"user": "sara", "pw": "Str0ng-Pass-2", "name": "استقبال",
               "group": "grp_staff", "note": ""})
app.on_add_portal()
check("حساب بوابة جاهز للتعديل", "sara" in app.tv_por.get_children())
app.tv_por.selection_set("sara")
before_hist = len(DEV.history)
SCRIPT.append({"name": "استقبال — الطابق الأرضي", "note": "دوام جزئي"})
app.on_edit_portal_meta()
pr = app.db.portal("sara")
check("اسم حساب البوابة تغيّر", pr["name"] == "استقبال — الطابق الأرضي", pr["name"])
check("ملاحظة حساب البوابة تغيّرت", pr["note"] == "دوام جزئي", pr["note"])
check("المجموعة لم تُمسّ", DEV.users["sara"]["group"] == "grp_staff",
      DEV.users["sara"]["group"])
check("لم يُرسَل أي أمر إلى الراوتر", len(DEV.history) == before_hist)
check("لا أخطاء", not messagebox.errors(), str(messagebox.errors()))

head("١٢و — التوقيع ونافذة حول البرنامج")
check("التوقيع ظاهر في الشريط السفلي",
      "AFZ Systems" in app.lbl_brand.cget("text"), app.lbl_brand.cget("text"))
app._brand_hover(True)
check("المرور يكشف أنه قابل للنقر",
      app.T["about_hint"] in app.lbl_brand.cget("text"))
app._brand_hover(False)
check("النص يعود بعد المرور",
      app.lbl_brand.cget("text") == "Powered by AFZ Systems", app.lbl_brand.cget("text"))

for lang in ("ar", "en"):
    body = M.ABOUT[lang]
    check("نص حول البرنامج [%s] فيه البريد" % lang, M.VENDOR_EMAIL in body)
    check("نص حول البرنامج [%s] فيه اسم الجهة" % lang, M.VENDOR in body)
    check("نص حول البرنامج [%s] فيه تعليمات كافية" % lang, len(body) > 2000,
          "%d حرفاً" % len(body))
    hint = "شبكات الإدارة" if lang == "ar" else "management networks"
    check("نص حول البرنامج [%s] يذكر شبكة الإدارة" % lang, hint in body, hint)

app.on_about()
check("النافذة فُتحت بلا استثناء", True)
check("لا أخطاء", not messagebox.errors(), str(messagebox.errors()))

head("١٢ل — منفذ الاتصال")
check("خانة المنفذ فارغة افتراضياً", app.v_port.get() == "", repr(app.v_port.get()))
def _all(w, out=None):
    out = [] if out is None else out
    for ch in getattr(w, "children", []):
        out.append(ch)
        _all(ch, out)
    return out


# نطابق نص التلميح بعينه لا مجرد وجود "22": المسارات المؤقتة تحمل
# أرقاماً عشوائية وقد تحوي "22" فيصير الفحص متذبذباً
lbl_port = [w for w in _all(app)
            if isinstance(w, tkinter.ttk.Label)
            and str(w.cget("text") or "") == app.T["port_hint"]]
check("التسمية تشرح أن الفراغ يعني 22", len(lbl_port) == 1,
      str([w.cget("text") for w in lbl_port]))
check("التلميح يذكر المنفذ الافتراضي", "22" in app.T["port_hint"],
      app.T["port_hint"])

# منفذ غير رقمي يُرفض قبل أن يصل إلى الراوتر
messagebox.reset()
app.router.close()
app.v_port.set("abc")
app.v_pass.set("correct-password")
app.on_connect()
check("رفض منفذاً غير رقمي", len(messagebox.errors()) == 1, str(messagebox.errors()))
check("لم يتصل", not app.router.connected)
messagebox.reset()

app.v_port.set("70000")
app.v_pass.set("correct-password")
app.on_connect()
check("رفض منفذاً خارج المدى", len(messagebox.errors()) == 1)
check("لم يتصل", not app.router.connected)
messagebox.reset()

# الفراغ يعني 22
app.v_port.set("")
app.v_pass.set("correct-password")
app.on_connect()
check("الفراغ اتصل عبر 22", app.router.connected)
check("22 حُفظ في الإعدادات", app.settings["port"] == 22, str(app.settings["port"]))
check("الخانة بقيت فارغة", app.v_port.get() == "", repr(app.v_port.get()))
check("لا أخطاء", not messagebox.errors(), str(messagebox.errors()))

# منفذ مخصّص يُستعمل ويُحفظ
app.router.close()
app.v_port.set("2222")
app.v_pass.set("correct-password")
app.on_connect()
check("اتصل بمنفذ مخصّص", app.router.connected)
check("المنفذ المخصّص حُفظ", app.settings["port"] == 2222, str(app.settings["port"]))
app.router.close()
app.v_port.set("")
app.v_pass.set("correct-password")
app.on_connect()
check("عاد للاتصال الطبيعي", app.router.connected)
messagebox.reset()

head("١٢س — النافذة تفتح بعرض يسع شريط الاتصال")


def _win_w(a):
    return int(a.geometry().split("x")[0])


check("النافذة ضبطت مقاسها عند البناء", app.geometry() != "", app.geometry())

# شريط عريض: النافذة تفتح بما يسعه في سطر واحد
app._top_w1, app._top_w2 = 1400, 900
app._fit_window()
check("العرض يسع شريطاً عريضاً", _win_w(app) >= 1440,
      "%d px لشريط 1400" % _win_w(app))
check("الحد الأدنى هو مقاس السطرين لا السطر الواحد",
      940 <= app.minsize()[0] < 1440, str(app.minsize()))

# شريط ضيّق: نبقى عند العرض المفضّل ولا نتقلّص معه
app._top_w1, app._top_w2 = 500, 400
app._fit_window()
check("الشريط الضيّق لا يصغّر النافذة", _win_w(app) == 1120,
      "%d px" % _win_w(app))

# شريط أوسع من الشاشة: نقصّ عند حدود الشاشة لا نتجاوزها
tkinter.SCREEN[0] = 1280
app._top_w1, app._top_w2 = 3000, 2500
app._fit_window()
check("لا يتجاوز عرض الشاشة", _win_w(app) <= 1280 - 60,
      "%d px على شاشة 1280" % _win_w(app))
check("الحد الأدنى لا يتجاوز الشاشة أيضاً", app.minsize()[0] <= 1280 - 40,
      str(app.minsize()))
tkinter.SCREEN[0] = 1920

# النافذة تُفتح في وسط الشاشة لا خارجها
app._top_w1, app._top_w2 = 900, 700
app._fit_window()
parts = app.geometry().replace("x", "+").split("+")
check("الموضع ضمن الشاشة", int(parts[2]) >= 0 and int(parts[3]) >= 0,
      app.geometry())
check("لا أخطاء", not messagebox.errors(), str(messagebox.errors()))

head("١٢ع — شريط الاتصال ينكسر سطرين عند الضيق")


def _rows_used():
    return sorted(set(w.grid_kw["row"] for w, _, _ in app._top_cells
                      if w.grid_kw))


app._top_w1, app._top_w2 = 1300, 950
app._layout_top(1)
check("سطر واحد افتراضاً", _rows_used() == [0], str(_rows_used()))
check("كل الحقول مرصوفة",
      all(w.grid_kw for w, _, _ in app._top_cells), "11 حقلاً")


class _Ev(object):
    pass


ev = _Ev(); ev.widget = app; ev.width = 1400
app._on_window_resize(ev)
check("نافذة واسعة تبقى بسطر واحد", app._top_rows == 1, str(app._top_rows))

ev.width = 1100
app._on_window_resize(ev)
check("نافذة ضيّقة تنكسر سطرين", app._top_rows == 2, str(app._top_rows))
check("الحقول موزّعة على سطرين", _rows_used() == [0, 1], str(_rows_used()))
check("لا حقل ضاع عند الانكسار",
      all(w.grid_kw for w, _, _ in app._top_cells))
check("عنوان الراوتر في السطر الأول",
      app._top_cells[0][0].grid_kw["row"] == 0)
check("حالة الاتصال في السطر الثاني",
      app.lbl_state.grid_kw["row"] == 1)

ev.width = 1400
app._on_window_resize(ev)
check("العودة للاتساع تعيد السطر الواحد", app._top_rows == 1)

# حدث من ويدجت أخرى يجب أن يُتجاهل وإلا تذبذب التخطيط
ev2 = _Ev(); ev2.widget = app.lbl_state; ev2.width = 200
app._on_window_resize(ev2)
check("حدث من ويدجت أخرى لا يغيّر التخطيط", app._top_rows == 1)

head("١٢ف — نص الاتصال لا يوسّع الشريط")
check("زر الاتصال بعرض محجوز",
      app.btn_conn.cget("width") >= len(app.T["disconnect"]),
      str(app.btn_conn.cget("width")))
check("تسمية الحالة بعرض محجوز",
      app.lbl_state.cget("width") == app._state_chars,
      str(app.lbl_state.cget("width")))

app._set_state("● " + app.T["status_off"], "Off.TLabel")
short = app.lbl_state.cget("text")
app._set_state("● " + app.T["status_on"] + "  AR730", "Ok.TLabel")
long_ = app.lbl_state.cget("text")
check("النص يتغيّر فعلاً", short != long_, "%s ← %s" % (short, long_))
check("العرض المحجوز لم يتغيّر",
      app.lbl_state.cget("width") == app._state_chars)

app._set_state("● " + app.T["status_on"] + "  AR730-VERY-LONG-HOSTNAME-XYZ", "Ok.TLabel")
check("الاسم الطويل يُختصر لا يوسّع",
      len(app.lbl_state.cget("text")) <= app._state_chars,
      "%d حرفاً من %d" % (len(app.lbl_state.cget("text")), app._state_chars))
check("الاختصار يظهر بعلامة",
      app.lbl_state.cget("text").endswith("…"), app.lbl_state.cget("text"))
check("لا أخطاء", not messagebox.errors(), str(messagebox.errors()))

head("١٢م — الشريط السفلي يحجز مكانه")
nb_seq = app.nb.pack_seq
brand_seq = app.lbl_brand.master.pack_seq
check("دفتر التبويبات مرصوف", nb_seq is not None)
check("صف التوقيع مرصوف", brand_seq is not None)
check("الشريط السفلي رُصف قبل دفتر التبويبات الممتد",
      brand_seq < nb_seq, "التوقيع %s / التبويبات %s" % (brand_seq, nb_seq))
check("دفتر التبويبات هو الممتد", app.nb.pack_kw.get("expand") is True,
      str(app.nb.pack_kw))
check("التوقيع ظاهر بلا توسيع يدوي",
      "AFZ Systems" in app.lbl_brand.cget("text"))

head("١٢ن — أزرار نافذة حول البرنامج")


dlg = M.AboutDialog(app, app.T, M.ABOUT["ar"], lambda: None,
                    rtl=app.rtl, fonts=app.font_base)
kids = _all(dlg)
labels = [str(w.cget("text")) for w in kids if w.cget("text") is not None]
check("زر الإغلاق موجود", app.T["about_close"] in labels, str(labels[:8]))
check("زر نسخ البريد موجود", app.T["copy_email"] in labels, str(labels[:8]))

btn_frames = [w for w in kids
              if w.pack_kw and w.pack_kw.get("side") == "bottom"]
check("صف الأزرار محجوز في الأسفل", len(btn_frames) == 1, str(len(btn_frames)))

body = [w for w in kids if isinstance(w, tkinter.Text)]
check("صندوق النص موجود", len(body) == 1)
box = body[0].master
check("صندوق النص ممتد", box.pack_kw.get("expand") is True, str(box.pack_kw))
check("الأزرار رُصفت قبل صندوق النص الممتد",
      btn_frames[0].pack_seq < box.pack_seq,
      "أزرار %s / نص %s" % (btn_frames[0].pack_seq, box.pack_seq))
check("البريد داخل النافذة", M.VENDOR_EMAIL in labels)
dlg.destroy()
check("لا أخطاء", not messagebox.errors(), str(messagebox.errors()))

head("١٢ط — البحث في جدول الأجهزة")
# نهيّئ الجدول: جهاز موثوق باسم، وآخر بلا سجل محلي
app.v_find_dev.set("")
app._refresh_device_table()
all_rows = len(app.tv_dev.get_children())
check("الجدول كامل قبل البحث", all_rows >= 2, "%d صف" % all_rows)
check("العدّاد فارغ بلا بحث", app.lbl_count_dev.cget("text") == "",
      str(app.lbl_count_dev.cget("text")))

app.v_find_dev.set("الاستقبال")
check("البحث بالاسم يصفّي", len(app.tv_dev.get_children()) == 1,
      "%d صف" % len(app.tv_dev.get_children()))
check("العدّاد يظهر النسبة", "1" in app.lbl_count_dev.cget("text"),
      app.lbl_count_dev.cget("text"))

app.v_find_dev.set("00005e005301")
check("البحث بالماك بلا فواصل يطابق",
      "00005e005301" in app.tv_dev.get_children(),
      str(app.tv_dev.get_children()))

app.v_find_dev.set("00:00:5E:00:53:01")
check("البحث بالماك بالفواصل يطابق أيضاً",
      "00005e005301" in app.tv_dev.get_children())

app.v_find_dev.set("00:00:5E:00:53:02")
check("البحث يطابق جهازاً آخر", "00005e005302" in app.tv_dev.get_children())
check("ولا يطابق الأول", "00005e005301" not in app.tv_dev.get_children())

app.v_find_dev.set("ملغى")
revoked_hits = app.tv_dev.get_children()
check("البحث بالحالة يعمل", len(revoked_hits) >= 1, "%d صف" % len(revoked_hits))

app.v_find_dev.set("zzz-لا-يوجد")
check("بحث بلا نتيجة يفرّغ الجدول", len(app.tv_dev.get_children()) == 0)

app.v_find_dev.set("")
check("مسح البحث يعيد كل الصفوف",
      len(app.tv_dev.get_children()) == all_rows,
      "%d من %d" % (len(app.tv_dev.get_children()), all_rows))
check("العدّاد يفرغ بعد المسح", app.lbl_count_dev.cget("text") == "")
check("لا أخطاء", not messagebox.errors(), str(messagebox.errors()))

head("١٢ي — البحث في المستخدمين والمتصلين")
app.v_find_por.set("")
app._refresh_portal_table()
por_all = len(app.tv_por.get_children())
app.v_find_por.set("استقبال")
check("البحث في حسابات البوابة بالاسم",
      len(app.tv_por.get_children()) == 1, "%d صف" % len(app.tv_por.get_children()))
app.v_find_por.set("sara")
check("البحث باسم المستخدم", "sara" in app.tv_por.get_children())
app.v_find_por.set("")
check("مسح بحث البوابة", len(app.tv_por.get_children()) == por_all)

# صفوف ثابتة كي لا يعتمد الفحص على ما فعلته الفحوص السابقة بالمتصلين
app.online_rows = [
    {"id": "1", "user": "00005e005301", "ip": "10.0.20.31",
     "mac": "0000-5e00-5301", "status": "Success"},
    {"id": "2", "user": "sara", "ip": "10.0.20.44",
     "mac": "3e4b-1122-3344", "status": "Pre-authen"},
]
app.v_find_on.set("")
app._refresh_online_table()
on_all = len(app.tv_on.get_children())
check("جدول المتصلين فيه صفوف", on_all == 2, "%d صف" % on_all)

before_cmds = len(DEV.history)
app.v_find_on.set("10.0.20.44")
check("البحث في المتصلين بالـIP",
      len(app.tv_on.get_children()) == 1, "%d صف" % len(app.tv_on.get_children()))
app.v_find_on.set("Pre-authen")
check("البحث في المتصلين بالحالة",
      len(app.tv_on.get_children()) == 1, "%d صف" % len(app.tv_on.get_children()))
app.v_find_on.set("00005e005301")
check("البحث في المتصلين بالماك بلا فواصل",
      len(app.tv_on.get_children()) == 1, "%d صف" % len(app.tv_on.get_children()))
check("البحث لا يستعلم الراوتر من جديد", len(DEV.history) == before_cmds,
      "أوامر زائدة: %d" % (len(DEV.history) - before_cmds))
app.v_find_on.set("zzz-لا-يوجد")
check("بحث المتصلين بلا نتيجة", len(app.tv_on.get_children()) == 0)
app.v_find_on.set("")
check("مسح بحث المتصلين", len(app.tv_on.get_children()) == on_all)
check("لا أخطاء", not messagebox.errors(), str(messagebox.errors()))

head("١٢ك — التفاف النصوص التوضيحية مع حجم النافذة")
import tkinter as _tkmod
probe = _tkmod.Label(app)
app._wrap(probe, probe, margin=56, minimum=220)
check("عرض ابتدائي مضبوط قبل أي تغيير حجم",
      probe.cget("wraplength") == 660, str(probe.cget("wraplength")))
probe.event_generate("<Configure>", width=900)
check("التوسيع يزيد عرض الالتفاف",
      probe.cget("wraplength") == 844, str(probe.cget("wraplength")))
probe.event_generate("<Configure>", width=400)
check("التصغير ينقص عرض الالتفاف",
      probe.cget("wraplength") == 344, str(probe.cget("wraplength")))
probe.event_generate("<Configure>", width=100)
check("لا ينزل تحت الحد الأدنى",
      probe.cget("wraplength") == 220, str(probe.cget("wraplength")))
check("رُقيب تغيير الحجم مسجَّل فعلاً",
      len(probe.bindings.get("<Configure>", [])) == 1)

head("١٢ص — النسخ من الجداول بلا تعديل")
app.v_find_dev.set("")
app._refresh_device_table()
row_id = "00005e005302"
row_y = app.tv_dev.get_children().index(row_id) * 20 + 5
vals = [str(v) for v in app.tv_dev.item(row_id, "values")]

check("قائمة الزر الأيمن مربوطة", "<Button-3>" in app.tv_dev.bindings)
check("اختصار النسخ مربوط", "<Control-c>" in app.tv_dev.bindings)
check("الجدول لا يملك أي أداة تحرير", not any(
    isinstance(w, (tkinter.Entry, tkinter.ttk.Entry)) for w in _all(app.tv_dev.master)))

# في العربية العمود الظاهر الأخير (أقصى اليمين) هو الماك
del tkinter.MENUS[:]
x_mac = (len(app.tv_dev.cget("displaycolumns")) - 1) * 100 + 5
app.tv_dev.event_generate("<Button-3>", x=x_mac, y=row_y, x_root=0, y_root=0)
check("فُتحت قائمة", len(tkinter.MENUS) == 1)
labels = [l for l, _ in tkinter.MENUS[-1].entries] if tkinter.MENUS else []
check("الزر الأيمن حدّد الصف", app.tv_dev.selection() == (row_id,))
check("بند نسخ الخلية يعرض الماك رغم عكس الأعمدة",
      any("00:00:5E:00:53:02" in l for l in labels), str(labels))
check("بندا صيغتي الراوتر", any("00005e005302" in l for l in labels)
      and any("0000-5e00-5302" in l for l in labels), str(labels))

def _press(label_part):
    for l, cmd in tkinter.MENUS[-1].entries:
        if label_part in l:
            cmd(); return True
    return False

_press("00005e005302")
check("نسخ الماك بلا فواصل", tkinter.CLIPBOARD[0] == "00005e005302", tkinter.CLIPBOARD[0])
_press("0000-5e00-5302")
check("نسخ الماك بالشرطات", tkinter.CLIPBOARD[0] == "0000-5e00-5302", tkinter.CLIPBOARD[0])
_press(app.T["copy_row"])
check("نسخ الصف كاملاً", tkinter.CLIPBOARD[0] == "\t".join(vals), repr(tkinter.CLIPBOARD[0]))
check("شريط الحالة يؤكد النسخ", "00:00:5E:00:53:02" in app.lbl_status.cget("text"))

# عمود المجموعة: بند واحد للخلية بلا بنود الماك
del tkinter.MENUS[:]
disp = tuple(app.tv_dev.cget("displaycolumns"))
app.tv_dev.event_generate("<Button-3>", x=disp.index("group") * 100 + 5, y=row_y,
                          x_root=0, y_root=0)
labels = [l for l, _ in tkinter.MENUS[-1].entries]
check("خلية المجموعة", any("grp_managers" in l for l in labels) and len(labels) == 2,
      str(labels))
_press("grp_managers")
check("نسخ قيمة المجموعة", tkinter.CLIPBOARD[0] == "grp_managers")

del tkinter.MENUS[:]
app.tv_dev.event_generate("<Button-3>", x=5, y=5000, x_root=0, y_root=0)
check("النقر خارج الصفوف لا يفتح قائمة", not tkinter.MENUS)

tkinter.CLIPBOARD[0] = ""
app.tv_dev.selection_set(row_id)
r = app.tv_dev.event_generate("<Control-c>")
check("Ctrl+C ينسخ الصف المحدد", tkinter.CLIPBOARD[0] == "\t".join(vals),
      repr(tkinter.CLIPBOARD[0]))
check("Ctrl+C لا يمرّ لغيره", r == "break")

before_vals = list(app.tv_dev.item(row_id, "values"))
check("النسخ لم يغيّر الصف", before_vals == [v for v in app.tv_dev.item(row_id, "values")])

check("جدول المتصلين يدعم النسخ أيضاً", "<Button-3>" in app.tv_on.bindings)
check("جدول البوابة يدعم النسخ", "<Button-3>" in app.tv_por.bindings)
check("جدول المجموعات يدعم النسخ", "<Button-3>" in app.tv_grp.bindings)

# سجل الأوامر: تحديد ونسخ نعم، كتابة ولصق لا
log = app.txt_log
check("السجل يمنع الكتابة",
      log.event_generate("<Key>", keysym="a", state=0) == "break")
check("السجل يسمح بـ Ctrl+C",
      log.event_generate("<Key>", keysym="c", state=0x0004) is None)
check("السجل يسمح بالتنقل بالأسهم",
      log.event_generate("<Key>", keysym="Down", state=0) is None)
check("السجل يمنع اللصق", log.event_generate("<<Paste>>") == "break")
check("السجل يمنع القص", log.event_generate("<<Cut>>") == "break")
check("لا أخطاء", not messagebox.errors(), str(messagebox.errors()))

head("١٣ — تحليل مخرجات الخطوط الحقيقية")
REAL_ROUTES = """ip route-static 0.0.0.0 0.0.0.0 GigabitEthernet0/0/8 dhcp
ip route-static 0.0.0.0 0.0.0.0 192.168.4.1 track nqa admin wan4
ip route-static 0.0.0.0 0.0.0.0 192.168.1.1 track nqa admin wan1
ip route-static 0.0.0.0 0.0.0.0 192.168.2.1 track nqa admin wan2
ip route-static 1.1.1.1 255.255.255.255 192.168.2.1
ip route-static 8.8.4.4 255.255.255.255 192.168.4.1
ip route-static 8.8.8.8 255.255.255.255 192.168.1.1
ip route-static vpn-instance OPENSSHLINKVPORT 0.0.0.0 0.0.0.0 192.168.4.1 public"""
REAL_NQA = """[V300R024C00SPC100]
#
nqa test-instance admin wan1
 test-type icmp
 destination-address ipv4 1.1.1.1
 frequency 10
 start now
nqa test-instance admin wan2
 test-type icmp
 destination-address ipv4 1.0.0.1
 start now
nqa test-instance admin wan4
 test-type tcp
 destination-address ipv4 8.8.4.4
 destination-port 443
 start now
#
return"""
REAL_BRIEF = """Interface                         IP Address/Mask      Physical   Protocol  
GigabitEthernet0/0/8              192.168.2.250/24     down       down      
GigabitEthernet0/0/9              192.168.1.250/24     up         up        
LoopBack1                         10.0.255.1/32        up         up(s)     
Vlanif103                         192.168.4.250/24     up         up        """
routes = M.parse_static_routes(REAL_ROUTES)
check("مسارات dhcp و vpn-instance مستبعدة", len(routes) == 6, str(len(routes)))
check("track مقروء", routes[0]["track"] == ("admin", "wan4"), str(routes[0]))
check("قناع /32 مقروء", routes[3]["len"] == 32)
nqa = M.parse_nqa_config(REAL_NQA)
check("ثلاثة فحوص", len(nqa) == 3, str(sorted(nqa)))
check("منفذ TCP مقروء", nqa[("admin", "wan4")]["port"] == "443")
lines = M.build_wan_lines(routes, nqa, M.parse_ip_brief(REAL_BRIEF))
byg = {l["gw"]: l for l in lines}
check("ثلاثة خطوط", sorted(byg) == ["192.168.1.1", "192.168.2.1", "192.168.4.1"], str(sorted(byg)))
check("كشف الفحص الذي يخرج من خط آخر (wan1 → 1.1.1.1 عبر wan2)",
      "note_probe_elsewhere" in byg["192.168.1.1"]["notes"], str(byg["192.168.1.1"]["notes"]))
check("كشف مسار مربوط بفحص TCP لا يُسحب",
      "note_track_not_icmp" in byg["192.168.4.1"]["notes"], str(byg["192.168.4.1"]["notes"]))
check("كشف غياب فحص HTTPS", "note_no_https" in byg["192.168.1.1"]["notes"])
check("المنفذ من الشبكة", byg["192.168.4.1"]["iface"] == "Vlanif103")
check("المنفذ المفصول", byg["192.168.2.1"]["iface_up"] is False)

REAL_RT = """Destination: 0.0.0.0/0
     Protocol: Static           Process ID: 0
      NextHop: 192.168.1.1       Neighbour: 0.0.0.0
        State: Invalid Adv Relied      Age: 00h01m49s
 RelayNextHop: 0.0.0.0           Interface: GigabitEthernet0/0/9
     TunnelID: 0x0                   Flags: R

Destination: 0.0.0.0/0
      NextHop: 192.168.4.1       Neighbour: 0.0.0.0
        State: Active Adv Relied       Age: 00h25m27s
 RelayNextHop: 0.0.0.0           Interface: Vlanif103

Destination: 0.0.0.0/0
      NextHop: 0.0.0.0           Neighbour: 0.0.0.0
        State: Invalid Adv             Age: 00h45m49s"""
rt = M.parse_default_route_states(REAL_RT)
check("حالة المسار المسحوب", rt["192.168.1.1"]["state"] == "Invalid", str(rt))
check("حالة المسار الفعّال وعمره", rt["192.168.4.1"] == {"state": "Active", "iface": "Vlanif103",
                                                         "age": "00h25m27s"}, str(rt))
check("مسار 0.0.0.0 مستبعد", "0.0.0.0" not in rt)

REAL_RES = """ NQA entry(admin, t1icmp) :testflag is active ,testtype is icmp 
  1 . Test 3 result   The test is finished
   Send operation times: 3              Receive response times: 3          
   Completion:success                   RTD OverThresholds number: 0       
   Min/Max/Average Completion Time: 50/220/110                           
   Lost packet ratio: 0 %                                                
  2 . Test 4 result   The test is finished
   Send operation times: 3              Receive response times: 0          
   Completion:failed                    RTD OverThresholds number: 0       
   Min/Max/Average Completion Time: 0/0/0                                
   Lost packet ratio: 100 %                                              """
res = M.parse_nqa_result(REAL_RES)
check("آخر نتيجة هي الأحدث (Test 4)", res["test"] == 4 and not res["ok"] and res["loss"] == 100,
      str(res))
check("لا نتائج = None", M.parse_nqa_result("Error: no result") is None)

REAL_IF = """GigabitEthernet0/0/9 current state : UP
Line protocol current state : UP
Description:WAN1
Last physical up time   : 2026-09-14 16:13:08 UTC+02:00
Last physical down time : 2026-09-14 16:12:39 UTC+02:00
Current system time: 2026-09-14 16:21:39+02:00
Speed :  100,  Loopback: NONE
Duplex: FULL,  Negotiation: ENABLE
Last 300 seconds input rate 5256 bits/sec, 3 packets/sec
Last 300 seconds output rate 29936 bits/sec, 7 packets/sec

Input:  2065856 packets, 262452113 bytes
  Discard:                  0,  Total Error:               230

  CRC:                    115,  Giants:                      0

Output:  4755263 packets, 2067708560 bytes
  Discard:                  0,  Total Error:                 0"""
inf = M.parse_interface(REAL_IF)
check("وصف وسرعة وCRC المنفذ", (inf["desc"], inf["speed"], inf["duplex"], inf["crc"]) ==
      ("WAN1", 100, "FULL", 115), str(inf))
check("أخطاء الاستقبال لا الإرسال", inf["in_errors"] == 230, str(inf["in_errors"]))
check("معدل المرور", inf["in_bps"] == 5256 and inf["out_bps"] == 29936)
check("وقت الانقطاع", M._vrp_time(inf["last_down"]) == M.datetime.datetime(2026, 9, 14, 16, 12, 39))
check("منافذ VLAN", M.parse_vlan_ports(
    "Untagged      Port: GigabitEthernet0/0/3        \nActive Untag  Port: GigabitEthernet0/0/3")
      == ["GigabitEthernet0/0/3"])
REAL_PING = """  --- 8.8.8.8 ping statistics ---
    5 packet(s) transmitted
    5 packet(s) received
    0.00% packet loss
    round-trip min/avg/max = 40/44/46 ms"""
check("ملخص ping", M.parse_ping(REAL_PING) == {"sent": 5, "recv": 5, "loss": 0.0, "min": 40,
                                               "avg": 44, "max": 46}, str(M.parse_ping(REAL_PING)))
check("ping بلا ردود", M.parse_ping("    3 packet(s) transmitted\n    0 packet(s) received\n"
                                     "    100.00% packet loss")["recv"] == 0)

head("١٣أ — فحص الخطوط من التبويب")
messagebox.reset()
wan = DEV.wan
wan.commands[:] = []
lines = app.on_check_lines()
check("فُحصت ثلاثة خطوط", lines is not None and len(lines) == 3, str(lines and len(lines)))
byg = {l["gw"]: l for l in app.wan_lines}
check("WAN1 سليم", byg["192.168.1.1"]["verdict"] == "ok", byg["192.168.1.1"]["verdict"])
check("WAN2 منفذه مفصول", byg["192.168.2.1"]["verdict"] == "port_down",
      byg["192.168.2.1"]["verdict"])
check("WAN4 عبر Vlanif103 → GigabitEthernet0/0/3",
      byg["192.168.4.1"]["phys"] == "GigabitEthernet0/0/3" and
      byg["192.168.4.1"]["port"]["speed"] == 1000, str(byg["192.168.4.1"]["port"]))
check("فحص ICMP وHTTPS مرتبطان بكل خط",
      byg["192.168.1.1"]["icmp"]["name"] == "w1icmp" and byg["192.168.1.1"]["tcp"]["name"] == "w1tcp")
check("لا ملاحظات إعداد على الإعداد الصحيح", byg["192.168.4.1"]["notes"] == [],
      str(byg["192.168.4.1"]["notes"]))
check("قياس مباشر عبر -nexthop",
      any(c == "ping -c 10 -t 1000 -nexthop 192.168.1.1 149.112.112.112" for _, c in wan.commands))
check("لا ping لمنفذ مفصول", not any("-nexthop 192.168.2.1" in c for _, c in wan.commands))
check("كل أوامر الفحص من وضع المستخدم (قراءة فقط)",
      all(v == "user" for v, _ in wan.commands), str(set(v for v, _ in wan.commands)))
check("الجدول فيه ثلاثة صفوف", len(app.tv_wan.get_children()) == 3)
vals = app.tv_wan.item("192.168.1.1", "values")
check("اسم الخط من وصف المنفذ", vals[0] == "WAN1", str(vals))
check("زمن الاستجابة من ping المباشر", "52 ms" in vals[6], str(vals))
check("ملاحظة السرعة 100 على WAN1",
      any("100" in n for n in app._wan_notes(byg["192.168.1.1"])))
report = app._wan_report_text()
check("التقرير يذكر كل خط", all(n in report for n in ("WAN1", "WAN2", "WAN4")))
check("التقرير يذكر CRC", "CRC 115" in report)
check("التقرير معروض", "WAN4" in app.txt_wan.get("1.0", "end"))
check("لا أخطاء", not messagebox.errors(), str(messagebox.errors()))

head("١٣ب — انتهاء الحصة: ping يعمل وHTTPS لا")
wan.lines["192.168.1.1"]["tcp_ok"] = False
app.on_check_lines()
byg = {l["gw"]: l for l in app.wan_lines}
check("WAN1 محجوب", byg["192.168.1.1"]["verdict"] == "blocked", byg["192.168.1.1"]["verdict"])
check("الراوتر لم يسحبه (ping ينجح)", byg["192.168.1.1"]["route_state"] == "Active")
check("تنبيه في شريط الحالة", "WAN1" in app.lbl_status.cget("text"), app.lbl_status.cget("text"))
check("وسم الخطر في الجدول", "bad" in app.tv_wan.item("192.168.1.1", "tags"))

head("١٣ج — إخراج الخط يدوياً ثم إعادته")
messagebox.reset()
# الخط الأخير العامل: نُسقط WAN4 مؤقتاً فلا يبقى غير WAN1 المحجوب
wan.lines["192.168.4.1"]["icmp_ok"] = False
app.on_check_lines(live=False)
app.tv_wan.selection_set("192.168.1.1")
app.on_withdraw_line()
check("رفض إخراج الخط حين لا يبقى غيره", len(messagebox.errors()) == 1, str(messagebox.errors()))
check("لم يُحذف المسار", any("0.0.0.0 0.0.0.0 192.168.1.1" in r for r in wan.routes))
wan.lines["192.168.4.1"]["icmp_ok"] = True
app.on_check_lines(live=False)
messagebox.reset()

messagebox.answers[:] = [False]
app.tv_wan.selection_set("192.168.1.1")
app.on_withdraw_line()
check("الإلغاء لا يغيّر شيئاً", any("0.0.0.0 0.0.0.0 192.168.1.1" in r for r in wan.routes))

saves = DEV.save_count
app.tv_wan.selection_set("192.168.1.1")
app.on_withdraw_line()
check("لا أخطاء", not messagebox.errors(), str(messagebox.errors()))
check("المسار حُذف من الراوتر", not any("0.0.0.0 0.0.0.0 192.168.1.1" in r for r in wan.routes),
      str(wan.routes))
check("الحذف من system-view",
      ("system", "undo ip route-static 0.0.0.0 0.0.0.0 192.168.1.1") in wan.commands)
rec = app.settings["withdrawn_lines"].get("192.168.1.1")
check("المسار محفوظ محلياً مع فحصه", rec and rec["track"] == ["admin", "w1icmp"]
      and rec["reason"] == "manual", str(rec))
check("محفوظ في ملف الإعدادات أيضاً",
      "192.168.1.1" in M.load_settings().get("withdrawn_lines", {}))
check("الإعداد حُفظ على الراوتر", DEV.save_count == saves + 1)
byg = {l["gw"]: l for l in app.wan_lines}
check("الخط ما زال ظاهراً كخارج التوزيع",
      byg["192.168.1.1"]["verdict"] == "withdrawn", byg["192.168.1.1"]["verdict"])
check("وما زالت صحته تُفحص (محجوب)", byg["192.168.1.1"]["health"] == "blocked")
check("سُجّل في التاريخ", app.db.data["history"][-1]["action"] == "wan_withdraw")

messagebox.reset()
app.tv_wan.selection_set("192.168.1.1")
app.on_withdraw_line()
check("لا يُخرج مرتين", any(c[0] == "info" for c in messagebox.calls))

messagebox.reset()
app.tv_wan.selection_set("192.168.4.1")
app.on_restore_line()
check("لا يعيد خطاً لم يُخرجه البرنامج", any(c[0] == "info" for c in messagebox.calls))

messagebox.reset()
wan.lines["192.168.1.1"]["tcp_ok"] = True
app.tv_wan.selection_set("192.168.1.1")
app.on_restore_line()
ask = [c for c in messagebox.calls if c[0] == "askyesno"]
check("التأكيد يعرض الأمر الذي سيُنفَّذ",
      ask and "track nqa admin w1icmp" in ask[-1][2], str(ask))
check("المسار عاد مربوطاً بفحص ICMP",
      "ip route-static 0.0.0.0 0.0.0.0 192.168.1.1 track nqa admin w1icmp" in wan.routes,
      str(wan.routes))
check("أُزيل من القائمة المحلية", "192.168.1.1" not in app.settings["withdrawn_lines"])
byg = {l["gw"]: l for l in app.wan_lines}
check("عاد سليماً في التوزيع", byg["192.168.1.1"]["verdict"] == "ok", byg["192.168.1.1"]["verdict"])
check("لا أخطاء", not messagebox.errors(), str(messagebox.errors()))

head("١٣د — مسار أُعيد يدوياً على الراوتر")
app.settings["withdrawn_lines"]["192.168.4.1"] = {"track": ["admin", "w4icmp"], "reason": "manual"}
app.on_check_lines(live=False)
check("السجل المحلي القديم يُنظَّف تلقائياً", "192.168.4.1" not in app.settings["withdrawn_lines"])

head("١٣هـ — المراقبة التلقائية")
messagebox.reset()
app.v_wan_auto.set(True)
app.v_wan_auto_withdraw.set(True)
wan.lines["192.168.1.1"]["tcp_ok"] = False
wan.commands[:] = []
app._wan_monitor_once()
check("دورة واحدة لا تكفي للإخراج", any("0.0.0.0 0.0.0.0 192.168.1.1" in r for r in wan.routes))
check("المراقبة بلا ping مباشر", not any(c.startswith("ping") for _, c in wan.commands))
check("المراقبة بلا نوافذ", not messagebox.calls, str(messagebox.calls))
app._wan_monitor_once()
check("الدورة الثانية تُخرج الخط المحجوب",
      not any("0.0.0.0 0.0.0.0 192.168.1.1" in r for r in wan.routes), str(wan.routes))
check("سبب الإخراج تلقائي", app.settings["withdrawn_lines"]["192.168.1.1"]["reason"] == "auto")
check("المراقبة لا تحفظ الإعداد على الراوتر",
      not any(c == "save" for _, c in wan.commands))
app._wan_monitor_once()
check("لا يعيده ما دام محجوباً",
      not any("0.0.0.0 0.0.0.0 192.168.1.1" in r for r in wan.routes))
wan.lines["192.168.1.1"]["tcp_ok"] = True
app._wan_monitor_once()
check("دورة سليمة واحدة لا تكفي للإعادة",
      not any("0.0.0.0 0.0.0.0 192.168.1.1" in r for r in wan.routes))
app._wan_monitor_once()
check("يعيده بعد دورتين سليمتين",
      "ip route-static 0.0.0.0 0.0.0.0 192.168.1.1 track nqa admin w1icmp" in wan.routes)

# لا يُخرج آخر خط يعمل حتى لو كان محجوباً
wan.lines["192.168.1.1"]["tcp_ok"] = False
wan.lines["192.168.4.1"]["icmp_ok"] = False
app._wan_monitor_once(); app._wan_monitor_once(); app._wan_monitor_once()
check("لا يُخرج آخر خط يعمل", any("0.0.0.0 0.0.0.0 192.168.1.1" in r for r in wan.routes))

# الإخراج اليدوي لا تعيده المراقبة
wan.lines["192.168.4.1"]["icmp_ok"] = True
wan.lines["192.168.1.1"]["tcp_ok"] = True
app.v_wan_auto_withdraw.set(False)
app.on_check_lines(live=False)
app.tv_wan.selection_set("192.168.1.1")
app.on_withdraw_line()
app.v_wan_auto_withdraw.set(True)
app._wan_monitor_once(); app._wan_monitor_once()
check("الإخراج اليدوي تحترمه المراقبة",
      not any("0.0.0.0 0.0.0.0 192.168.1.1" in r for r in wan.routes))
app.tv_wan.selection_set("192.168.1.1")
app.on_restore_line()
app.v_wan_auto.set(False)
app.v_wan_auto_withdraw.set(False)
check("لا أخطاء", not messagebox.errors(), str(messagebox.errors()))

tkinter.CLIPBOARD[0] = ""
app.on_copy_wan_report()
check("نسخ التقرير", "WAN1" in tkinter.CLIPBOARD[0] and "192.168.4.1" in tkinter.CLIPBOARD[0])
check("جدول الخطوط يدعم النسخ", "<Button-3>" in app.tv_wan.bindings)

head("١٢و — أجهزة الإدارة: تحليل مخرجات الجهاز الحقيقي")
REAL_ACL = """Basic ACL 2999, 3 rules
MGMT-ACCESS
Acl's step is 5
 rule 5 permit source 10.0.1.0 0.0.0.255 (38 matches)
 rule 10 permit source 10.0.10.0 0.0.0.255 
 rule 3000 deny (180 matches)

Advanced ACL 3010, 2 rules
MANAGERS
Acl's step is 5
 rule 3 permit ip destination 10.0.255.1 0 
 rule 3000 permit ip 
"""
acls = M.parse_basic_acls(REAL_ACL)
check("القوائم الأساسية وحدها", list(acls) == ["2999"], str(list(acls)))
check("الوصف مقروء", acls["2999"]["desc"] == "MGMT-ACCESS", acls["2999"]["desc"])
check("القواعد الثلاث بأرقامها", [r["id"] for r in acls["2999"]["rules"]] == [5, 10, 3000])
check("قاعدة الشبكة بمصدرها وقناعها",
      acls["2999"]["rules"][0]["src"] == "10.0.1.0" and acls["2999"]["rules"][0]["wild"] == "0.0.0.255")
check("قاعدة المنع العامة بلا مصدر", acls["2999"]["rules"][2] == {"id": 3000, "action": "deny", "src": "", "wild": ""})
check("رقم القاعدة الجديدة 100 قبل المنع", M.acl_free_rule_id(acls["2999"]) == 100)
check("قاعدة شبكة ليست قاعدة مضيف", M.acl_host_rule(acls["2999"], "10.0.10.0") is None)
host = M.parse_basic_acls("Basic ACL 2999, 1 rule\n rule 7 permit source 10.0.20.250 0 (3 matches)")
check("قاعدة المضيف بقناع 0 مقروءة", M.acl_host_rule(host["2999"], "10.0.20.250") == 7, str(host))
tight = {"rules": [{"id": 5, "action": "permit", "src": "10.0.1.0", "wild": "0.0.0.255"},
                   {"id": 50, "action": "deny", "src": "", "wild": ""}]}
check("قائمة منعها مبكر: رقم قبل المنع", M.acl_free_rule_id(tight) == 1)

REAL_ARP = """IP ADDRESS      MAC ADDRESS     EXPIRE(M) TYPE        INTERFACE   VPN-INSTANCE 
                                    VLAN/CEVLAN(SIP/DIP)      PVC
------------------------------------------------------------------------------
10.0.20.1       0000-5e00-5365            I -         Vlanif20       
10.0.20.53      0000-5e00-5362  17        D-0         GE0/0/2        
                                            20/-      
10.0.21.217     0000-5e00-5363  18        D-0         GE0/0/2        
                                            20/-      
------------------------------------------------------------------------------
Total:26        Dynamic:25      Static:0     Interface:1    
"""
arp = M.parse_arp_table(REAL_ARP)
check("جدول ARP: الماك إلى العنوان", arp["00005e005362"]["ip"] == "10.0.20.53", str(arp.get("00005e005362")))
check("اسم المنفذ المختصر يُوسَّع", arp["00005e005362"]["iface"] == "GigabitEthernet0/0/2")
check("المدخل الثاني مقروء", arp["00005e005363"]["ip"] == "10.0.21.217")

REAL_POOL = """  Pool-name        : Vlanif20
  Network          : 10.0.20.0
  Mask             : 255.255.254.0
 -------------------------------------------------------------------------------------
  Network section 
         Start           End       Total    Used Idle(Expired) Conflict Disabled
 -------------------------------------------------------------------------------------
       10.0.20.1     10.0.21.254     510      64        446(0)       0     0
 -------------------------------------------------------------------------------------
  Index              IP             Client-ID    Type       Left   Status           
 -------------------------------------------------------------------------------------
      6       10.0.20.7        0000-5e00-5367    DHCP     527035   Used             
    249     10.0.20.250        aabb-ccdd-eeff    DHCP          -   Static-bind      
    499     10.0.21.244        0000-5e00-5361    DHCP     589711   Used             
 -------------------------------------------------------------------------------------
"""
pool = M.parse_pool_used(REAL_POOL)
check("مدى المجمع", (pool["start"], pool["end"]) == ("10.0.20.1", "10.0.21.254"), str(pool))
check("العناوين المؤجّرة والمربوطة", pool["used"] == {"10.0.20.7": "00005e005367", "10.0.20.250": "aabbccddeeff",
                                         "10.0.21.244": "00005e005361"},
      str(pool["used"]))

REAL_HTTP = """portal local-server http port 8080
authentication https-redirect enable
 local-user admin service-type terminal ssh http
 http secure-server ssl-policy default_policy
 http server enable
 http secure-server enable
 http server permit interface Vlanif1
"""
check("منافذ الويب المسموحة", M.parse_http_permit(REAL_HTTP) == ["Vlanif1"])
check("لا قيد منافذ = None", M.parse_http_permit("http server enable") is None)
b = M.parse_acl_bindings("acl number 2999\n acl-id 3010\n acl 2999 inbound\n acl 2999 inbound\n http acl 2999")
check("ربط vty والويب", b == {"vty": {"2999"}, "http": "2999"}, str(b))
check("acl-id و acl number ليستا ربطاً", M.parse_acl_bindings("acl number 2001\n acl-id 3020")["vty"] == set())
sb = M.parse_static_binds(" dhcp server static-bind ip-address 10.0.20.250 mac-address aabb-ccdd-eeff description Boss-PC")
check("ربط DHCP بوصفه", sb == [{"ip": "10.0.20.250", "mac": "aabbccddeeff", "desc": "Boss-PC"}], str(sb))
ast_ = M.parse_arp_static("arp static 10.0.20.250 aabb-ccdd-eeff\narp static 10.0.20.251 aabb-ccdd-eef0 vid 20 interface GigabitEthernet0/0/2")
check("ARP ثابت بلا vid وبه", ast_["10.0.20.250"]["vid"] == "" and
      ast_["10.0.20.251"]["iface"] == "GigabitEthernet0/0/2", str(ast_))
check("وصف الربط لاتيني فقط", M.mgmt_description("لابتوب المدير") == ""
      and M.mgmt_description("Boss PC #1") == "Boss-PC-1")

head("١٢و٢ — أجهزة الإدارة: التحقق من الاختيارات")
mg = DEV.mgmt
st = app.router.read_mgmt_state("Vlanif20", "00005e005302")
check("الشبكات من الراوتر", [n["iface"] for n in st["networks"]] == ["Vlanif103", "Vlanif1", "Vlanif10", "Vlanif20"],
      str([n["iface"] for n in st["networks"]]))
check("المصادقة على Vlanif20 مقروءة", st["nac"] == {"Vlanif20": True})
check("منفذ الجهاز من ARP فلا حاجة لقراءة VLAN", st["vlan_ports"] == [])

def plan_errs(**kw):
    a = dict(mac12="00005e005302", iface="Vlanif20", ip="", acl_no="2999", trusted=True)
    a.update(kw)
    p_, e_, w_ = M.plan_mgmt_device(st, a["mac12"], a["iface"], a["ip"], a["acl_no"], a["trusted"])
    return p_, [k for k, _ in e_], [k for k, _ in w_]

p_, e_, w_ = plan_errs()
check("خطة سليمة بلا أخطاء", p_ is not None and not e_, str(e_))
check("العنوان التلقائي يتخطى المؤجَّر (.254)", p_ and p_["ip"] == "10.0.21.253", str(p_ and p_["ip"]))
check("vid والمنفذ من الشبكة وARP", p_ and (p_["vid"], p_["port"]) == ("20", "GigabitEthernet0/0/2"))
check("الخطة لا تمس الويب (http acl يعطّل البوابة)",
      p_ and not any(c.startswith(("http", "undo http")) for s in M.mgmt_steps(p_) for c in s["do"] + s["undo"]),
      str(p_ and M.mgmt_steps(p_)))
check("تنبيه إعادة التوصيل (متصل بعنوان آخر)", "mgmt_warn_reconnect" in w_, str(w_))
check("عقد الماك القديم يُحرَّر قبل الربط", p_ and p_["release"] == "10.0.20.166", str(p_ and p_["release"]))
check("خطوة التحرير أولاً وفي وضع المستخدم",
      p_ and M.mgmt_steps(p_)[0] == {"key": "release", "view": "user", "undo": [],
                                     "do": ["reset ip pool interface Vlanif20 10.0.20.166"]})
check("لا تحرير إن اختير عنوان عقده نفسه", plan_errs(ip="10.0.20.166")[0]["release"] == "")
check("عنوان مؤجّر لجهاز آخر", "mgmt_err_ip_leased" in plan_errs(ip="10.0.21.254")[1])
check("عنوان مؤجّر للجهاز نفسه مقبول", not plan_errs(ip="10.0.20.166")[1], str(plan_errs(ip="10.0.20.166")[1]))
check("عنوان خارج الشبكة", "mgmt_err_ip_subnet" in plan_errs(ip="10.0.30.5")[1])
check("عنوان البث مرفوض", "mgmt_err_ip_subnet" in plan_errs(ip="10.0.21.255")[1])
check("عنوان الراوتر", "mgmt_err_ip_router" in plan_errs(ip="10.0.20.1")[1])
check("عنوان بصيغة خاطئة", "mgmt_err_ip_format" in plan_errs(ip="10.0.20.300")[1])
check("جهاز غير موثوق على شبكة بمصادقة", "mgmt_err_untrusted" in plan_errs(trusted=False)[1])
check("قائمة غير موجودة", "mgmt_err_acl" in plan_errs(acl_no="2500")[1])
check("قائمة غير مربوطة بـ SSH = خطأ", "mgmt_warn_not_vty" in plan_errs(acl_no="2001")[1])
check("شبكة غير موجودة", plan_errs(iface="Vlanif99")[1] == ["mgmt_err_net"])
mg.nets["20"] = ("10.0.20.1", 23, True, ["GigabitEthernet0/0/2", "GigabitEthernet0/0/4"])
st_off = app.router.read_mgmt_state("Vlanif20", "aabbccddee99")
check("جهاز غير متصل ومنفذان: لا يُخمَّن المنفذ",
      [k for k, _ in M.plan_mgmt_device(st_off, "aabbccddee99", "Vlanif20", "", "2999", True)[1]]
      == ["mgmt_err_port"])
mg.nets["20"] = ("10.0.20.1", 23, True, ["GigabitEthernet0/0/2"])
st_off = app.router.read_mgmt_state("Vlanif20", "aabbccddee99")
check("منفذ واحد في VLAN يكفي", M.plan_mgmt_device(st_off, "aabbccddee99", "Vlanif20", "", "2999", True)[0]
      ["port"] == "GigabitEthernet0/0/2")

head("١٢و٣ — أجهزة الإدارة: الإضافة من الواجهة")
messagebox.reset()
app._load_mgmt()
check("الجدول فارغ في البداية", not app.tv_mgmt.get_children())
check("سطر صلاحيات الإدارة", "2999" in app.lbl_mgmt_access.cget("text"), app.lbl_mgmt_access.cget("text"))
check("بلا http acl لا تنبيه عن البوابة", "undo http acl" not in app.lbl_mgmt_access.cget("text"))
check("البوابة المدمجة مقروءة من الإعداد", app.mgmt_state.get("portal") is True)
mg.http_acl = "2999"
app.on_refresh_mgmt()
check("http acl مع البوابة: تنبيه في السطر", "undo http acl" in app.lbl_mgmt_access.cget("text"),
      app.lbl_mgmt_access.cget("text"))
check("http acl مع البوابة: تنبيه في شريط الحالة", "undo http acl" in app.lbl_status.cget("text"),
      app.lbl_status.cget("text"))
mg.http_acl = None
app._load_mgmt()
check("زال التنبيه بعد إزالة http acl", "undo http acl" not in app.lbl_mgmt_access.cget("text"))
saves = DEV.save_count
mg.commands[:] = []
SCRIPT.append({"mac": "00:00:5E:00:53:02", "name": "لابتوب المدير", "net": "Vlanif20", "ip": "",
               "acl": "2999"})
app.on_add_mgmt()
labels = {f["key"]: f for f in ScriptedDialog.last_fields}
check("لا خيار للويب في النافذة", "web" not in labels, str(list(labels)))
check("النافذة تعرض الشبكات للاختيار", any("Vlanif20" in v for v in labels["net"]["values"]),
      str(labels["net"]["values"]))
check("النافذة تعرض القوائم مع ربطها", any(v.startswith("2999") and "SSH" in v for v in labels["acl"]["values"])
      and any(v.startswith("2001") for v in labels["acl"]["values"]), str(labels["acl"]["values"]))
check("بلا أخطاء", not messagebox.errors(), str(messagebox.errors()))
check("ربط DHCP على Vlanif20", mg.binds.get("20", {}).get("10.0.21.253") == ("0000-5e00-5302", ""),
      str(mg.binds))
check("العقد القديم حُرِّر في وضع المستخدم قبل الربط",
      mg.commands[0] == ("user", "reset ip pool interface Vlanif20 10.0.20.166")
      and "10.0.20.166" not in mg.leases["20"], str(mg.commands[:2]))
check("ARP ثابت بـ vid والمنفذ", mg.arp.get("10.0.21.253") == ("0000-5e00-5302", "20", "GigabitEthernet0/0/2"),
      str(mg.arp))
check("قاعدة 100 للعنوان وحده", mg.acls["2999"]["rules"].get(100) == "permit source 10.0.21.253 0",
      str(mg.acls["2999"]["rules"]))
check("لم يُضبط http acl", mg.http_acl is None, str(mg.http_acl))
check("منافذ الويب لم تتغير", mg.http_permit == ["Vlanif1"], str(mg.http_permit))
check("لم يُرسل أي أمر http", not any(c.startswith(("http", "undo http")) for _, c in mg.commands), str(mg.commands))
order = [c for _, c in mg.commands]
idx = lambda pre: next(i for i, c in enumerate(order) if c.startswith(pre))
check("الترتيب: تحرير ← ربط ← ARP ← قاعدة (الباب يُفتح أخيراً)",
      idx("reset ip pool") < idx("dhcp server") < idx("arp static") < idx("rule "), str(order))
check("الربط نُفّذ داخل الواجهة وARP في system-view",
      dict((c.split()[0], v) for v, c in mg.commands).get("dhcp") == "sub" and
      dict((c.split()[0], v) for v, c in mg.commands).get("arp") == "system", str(mg.commands))
info = [c for c in messagebox.calls if c[0] == "info"]
check("رسالة نجاح بالعنوان وأمر الدخول", info and "10.0.21.253" in info[-1][2] and "10.0.20.1" in info[-1][2],
      str(info[-1:]))
check("النجاح يذكر إعادة التوصيل", info and "10.0.20.166" in info[-1][2])
check("حُفظ الإعداد", DEV.save_count == saves + 1)
check("الصف في الجدول جاهز", app.tv_mgmt.item("10.0.21.253", "tags") == ("ok",)
      and app.T["mgmt_ready"] in app.tv_mgmt.item("10.0.21.253", "values"),
      str(app.tv_mgmt.item("10.0.21.253", "values")))
check("الاسم من السجل المحلي", "لابتوب المدير" in app.tv_mgmt.item("10.0.21.253", "values"))
check("السجل المحلي", app.db.data["mgmt"].get("10.0.21.253", {}).get("mac") == "00005e005302")
check("الاختيار محفوظ للمرة القادمة", app.settings["mgmt_iface"] == "Vlanif20" and app.settings["mgmt_acl"] == "2999")

messagebox.reset()
mg.commands[:] = []
SCRIPT.append({"mac": "00:00:5E:00:53:02", "name": "مكرر", "net": "Vlanif20", "ip": "10.0.21.200",
               "acl": "2999"})
app.on_add_mgmt()
check("ماك مربوط مسبقاً: رسالة خطأ واضحة", len(messagebox.errors()) == 1
      and "10.0.21.253" in messagebox.errors()[0][2], str(messagebox.errors()))
check("لم يُرسل أي أمر تغيير", not mg.commands, str(mg.commands))

head("١٢و٤ — أجهزة الإدارة: رفض الراوتر والتراجع")
mg.leases["20"]["10.0.20.180"] = "0000-5e00-5302"
check("الراوتر الوهمي يرفض ربط ماك له عقد آخر كالجهاز الحقيقي",
      "uses another IP" in mg._config("dhcp server static-bind ip-address 10.0.21.50 mac-address 0000-5e00-5302",
                                      "sub", "Vlanif20"))
del mg.leases["20"]["10.0.20.180"]
DEV.users["00005e0053aa"] = {"types": {"8021x"}, "group": "grp_managers", "pw": True, "state": "A"}
app.router_users = M.parse_local_users(app.router.read_aaa())
mg.dyn_arp["20"]["0000-5e00-53aa"] = ("10.0.20.170", "GE0/0/2")
mg.fail_on["arp static"] = "Error: Wrong parameter found at '^' position."
messagebox.reset()
saves = DEV.save_count
SCRIPT.append({"mac": "0000-5e00-53aa", "name": "Boss PC", "net": "Vlanif20", "ip": "10.0.21.100",
               "acl": "2999"})
app.on_add_mgmt()
err = messagebox.errors()
check("رسالة فشل تذكر الخطوة ورد الراوتر", len(err) == 1 and app.T["mgmt_step_arp"] in err[0][2]
      and "Wrong parameter" in err[0][2], str(err))
check("الرسالة تذكر التراجع عن الربط", err and app.T["mgmt_step_bind"] in err[0][2].split("\n")[-1], str(err))
check("الربط أُزيل بالتراجع", "10.0.21.100" not in mg.binds.get("20", {}), str(mg.binds))
check("لم تُضف قاعدة", all("10.0.21.100" not in r for r in mg.acls["2999"]["rules"].values()))
check("لم يُحفظ شيء", DEV.save_count == saves)
check("لا سجل محلي", "10.0.21.100" not in app.db.data["mgmt"])
del mg.fail_on["arp static"]

mg.fail_on["dhcp server static-bind ip-address 10.0.21.101 mac-address 0000-5e00-53aa description"] = \
    "Error: Wrong parameter found at '^' position."
messagebox.reset()
SCRIPT.append({"mac": "0000-5e00-53aa", "name": "Boss PC", "net": "Vlanif20", "ip": "10.0.21.101",
               "acl": "2999"})
app.on_add_mgmt()
mg.fail_on.clear()
check("رفض الوصف لا يُفشل العملية", not messagebox.errors(), str(messagebox.errors()))
check("رُبط بلا وصف", mg.binds["20"].get("10.0.21.101") == ("0000-5e00-53aa", ""))
check("القاعدة التالية 101", mg.acls["2999"]["rules"].get(101) == "permit source 10.0.21.101 0",
      str(mg.acls["2999"]["rules"]))
check("رسالة النجاح تذكر رفض الوصف",
      app.T["mgmt_desc_dropped"] in [c for c in messagebox.calls if c[0] == "info"][-1][2])

head("١٢و٥ — أجهزة الإدارة: السحب")
messagebox.reset()
app.tv_mgmt.selection_set("10.0.21.101")
app.router._s.local_address = lambda: "10.0.21.101"
app.on_remove_mgmt()
check("يرفض حذف عنوان جهازك أنت", len(messagebox.errors()) == 1 and 101 in mg.acls["2999"]["rules"])
del app.router._s.local_address
messagebox.reset()
mg.commands[:] = []
app.tv_mgmt.selection_set("10.0.21.101")
app.on_remove_mgmt()
check("سحب بلا أخطاء", not messagebox.errors(), str(messagebox.errors()))
check("القاعدة حُذفت", 101 not in mg.acls["2999"]["rules"])
check("ARP حُذف", "10.0.21.101" not in mg.arp)
check("الربط حُذف", "10.0.21.101" not in mg.binds["20"])
check("القاعدة تُحذف أولاً", [c for _, c in mg.commands][0] == "undo rule 101", str(mg.commands))
check("حذف الربط بالعنوان وحده (صيغة الجهاز)",
      ("sub", "undo dhcp server static-bind ip-address 10.0.21.101") in mg.commands, str(mg.commands))
check("الراوتر الوهمي يرفض الماك في حذف الربط كالجهاز",
      "Too many parameters" in mg._config("undo dhcp server static-bind ip-address 1.2.3.4 mac-address aabb-ccdd-eeff",
                                          "sub", "Vlanif20"))
check("اختفى من الجدول", "10.0.21.101" not in app.tv_mgmt.get_children())
check("الجهاز الآخر باقٍ", 100 in mg.acls["2999"]["rules"] and "10.0.21.253" in app.tv_mgmt.get_children())

# جزء حُذف يدوياً على الراوتر: الصف يظهر ناقصاً ويُسحب ما تبقّى منه
del mg.arp["10.0.21.253"]
app._load_mgmt()
check("الجهاز الناقص معلَّم", app.tv_mgmt.item("10.0.21.253", "tags") == ("orphan",)
      and app.T["mgmt_incomplete"] in app.tv_mgmt.item("10.0.21.253", "values"))
messagebox.reset()
app.tv_mgmt.selection_set("10.0.21.253")
app.on_remove_mgmt()
check("سحب الناقص بلا أخطاء", not messagebox.errors(), str(messagebox.errors()))
check("لم يبقَ منه شيء", 100 not in mg.acls["2999"]["rules"] and "10.0.21.253" not in mg.binds["20"])
check("قواعد الشبكات لم تُمس", set(mg.acls["2999"]["rules"]) == {5, 10, 3000}, str(mg.acls["2999"]["rules"]))
check("بلا تحديد يطلب اختيار صف", (app.on_remove_mgmt(), messagebox.calls[-1][0])[1] == "info")
check("النصوص متطابقة في اللغتين", set(M.TXT["ar"]) == set(M.TXT["en"]),
      str(set(M.TXT["ar"]) ^ set(M.TXT["en"])))
messagebox.reset()

head("١٢ز — اتجاه الواجهة العربية (RTL)")
check("الواجهة في وضع RTL", app.rtl is True)
check("الرصف يبدأ من اليمين", app._side() == "right")
check("الرصف المقابل يسار", app._side(False) == "left")
check("المرساة شرق", app._anchor() == "e")
check("المحاذاة يمين", app._justify() == "right")
check("الحشو ينقلب", app._pad(0, 12) == (12, 0))

disp = app.tv_dev.cget("displaycolumns")
check("أعمدة الجدول معكوسة العرض",
      tuple(disp) == ("note", "added", "state", "group", "name", "mac"), str(disp))
check("قيم الصفوف بقيت على ترتيبها المنطقي",
      app.tv_dev.item("00005e005301", "values")[0].startswith("00:00:5E"),
      str(app.tv_dev.item("00005e005301", "values")[0]))
check("محاذاة رؤوس الأعمدة يمين",
      app.tv_dev.headings["mac"].get("anchor") == "e",
      str(app.tv_dev.headings["mac"]))
check("سجل الأوامر بقي يساراً بخط ثابت العرض",
      app.txt_log.cget("wrap") == "none", str(app.txt_log.cget("wrap")))

head("١٢ح — نفس البرنامج بالإنجليزية (LTR)")
import json as _json
_cfg = os.path.join(WORK, "ar730_settings.json")
with open(_cfg, "w", encoding="utf-8") as _f:
    _json.dump({"ui_lang": "en"}, _f)
app2 = M.App()
check("بُني بالإنجليزية بلا استثناء", True)
check("الواجهة ليست RTL", app2.rtl is False)
check("الرصف يبدأ من اليسار", app2._side() == "left")
check("المرساة غرب", app2._anchor() == "w")
check("أعمدة الجدول بترتيبها الطبيعي",
      not app2.tv_dev.cget("displaycolumns"), str(app2.tv_dev.cget("displaycolumns")))
check("ثمانية تبويبات بالإنجليزية أيضاً", len(app2.nb.tabs_) == 8)
check("واجهة الأزرار إنجليزية", app2.T["dlg_ok"] == "OK", app2.T["dlg_ok"])
check("نص حول البرنامج إنجليزي",
      "What this program is" in M.ABOUT["en"] and "ما هذا البرنامج" not in M.ABOUT["en"])
check("لا أخطاء", not messagebox.errors(), str(messagebox.errors()))
app2._on_close()
os.remove(_cfg)

head("١٢ — الحفظ والإغلاق")
check("save نُفّذ أكثر من مرة", DEV.save_count >= 5, "عدد مرات الحفظ: %d" % DEV.save_count)
check("سجل التاريخ في قاعدة البيانات", len(app.db.data["history"]) >= 5,
      "%d عملية" % len(app.db.data["history"]))
app._on_close()
check("أُغلق نظيفاً", True)

head("النتيجة")
ok = sum(1 for _, c, _ in STEPS if c)
print("نجح %d من %d فحصاً" % (ok, len(STEPS)))
if FAILS:
    print("\nإخفاقات:")
    for f in FAILS:
        print("  - " + f)
shutil.rmtree(WORK, ignore_errors=True)
sys.exit(1 if FAILS else 0)
