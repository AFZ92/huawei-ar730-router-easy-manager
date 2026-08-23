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
    def __init__(self, parent, title, fields):
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
check("ستة تبويبات", len(app.nb.tabs_) == 6, "عدد التبويبات: %d" % len(app.nb.tabs_))
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

head("٤ — إضافة جهاز موثوق (الكمبيوتر 0000-5e00-5301)")
SCRIPT.append({"mac": "00:00:5E:00:53:01", "name": "كمبيوتر الاستقبال",
               "group": "grp_managers", "note": "مكتب الإدارة"})
app.on_add_device()
u = DEV.users.get("00005e005301")
check("الحساب أُنشئ على الراوتر", u is not None)
check("النوع 8021x", u and "8021x" in u["types"], str(u and u["types"]))
check("المجموعة grp_managers", u and u["group"] == "grp_managers")
check("كلمة السر ضُبطت", u and u["pw"])
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


lbl_port = [w for w in _all(app)
            if isinstance(w, tkinter.ttk.Label) and "22" in str(w.cget("text") or "")]
check("التسمية تشرح أن الفراغ يعني 22", len(lbl_port) == 1,
      str([w.cget("text") for w in lbl_port]))

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
check("ستة تبويبات بالإنجليزية أيضاً", len(app2.nb.tabs_) == 6)
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
