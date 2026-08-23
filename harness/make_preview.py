# -*- coding: utf-8 -*-
"""
يولّد معاينة HTML لشكل الواجهة — العناوين والأعمدة والصفوف كلها مقروءة
من البرنامج نفسه في وضع التجربة، لا مكتوبة يدوياً، كي تطابق ما سيظهر فعلاً.
"""
import os, sys, shutil, tempfile, html

# مخرجات هذه المجموعات عربية، وكونسول ويندوز يفتح بترميز قديم (cp1252)
# لا يسعها فتنفجر print قبل أن يبدأ أي فحص. نفرض UTF-8 في كل بيئة.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:          # بايثون قديم أو مخرَج لا يدعم إعادة الضبط
    pass

WORK = tempfile.mkdtemp(prefix="ar730prev_")
APPDIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
shutil.copy(os.path.join(APPDIR, "ar730_manager.py"), WORK)
sys.argv = [os.path.join(WORK, "ar730_manager.py"), "--demo"]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WORK)

import tkinter                       # noqa
import ar730_manager as M            # noqa

M.paramiko = M._DemoParamiko()
M.SETTINGS_FILE = os.path.join(WORK, "s.json")
M.DB_FILE = os.path.join(WORK, "d.json")
M.LOG_FILE = os.path.join(WORK, "l.log")

app = M.App()
app.v_pass.set("demo")
app.on_connect()
# اسم وصفي واحد كي تظهر فائدة قاعدة البيانات المحلية
app.db.upsert_device("00005e005302", "موبايل المدير", "grp_managers", "مدير")
app.db.upsert_device("00005e005303", "AP673 - الطابق الأول", "grp_infra", "نقطة وصول")
app.db.upsert_portal("sara", "محاسبة — الطابق الأول", "grp_staff", "دوام جزئي")
# جهاز ملغى كي تظهر طريقة عرض الملغيين (رمادي ومشطوب)
app.db.upsert_device("0011224488aa", "لابتوب موظف سابق", "grp_staff", "")
app.db.revoke_device("0011224488aa", "انتهى عقده")
app._refresh_device_table(); app._refresh_portal_table()
app.on_refresh_online()          # كي تظهر الأسماء الوصفية في جدول المتصلين

T = app.T
TABS = [t for _, t in app.nb.tabs_]


def table(tv, buttons):
    cols = list(tv["columns"])
    th = "".join("<th>%s</th>" % html.escape(tv.heading(c)["text"]) for c in cols)
    rows = ""
    for iid in tv.get_children():
        vals = tv.item(iid, "values")
        tags = tv.item(iid, "tags")
        cls = " class='%s'" % tags[0] if tags else ""
        rows += "<tr%s>%s</tr>" % (
            cls, "".join("<td>%s</td>" % html.escape(str(v)) for v in vals))
    btns = "".join("<button class='%s'>%s</button>" %
                   ("danger" if d else "", html.escape(b)) for b, d in buttons)
    return ("<div class='bar'>%s</div><table><thead><tr>%s</tr></thead>"
            "<tbody>%s</tbody></table>") % (btns, th, rows)


dev = table(app.tv_dev, [(T["add_device"], 0), (T["change_group"], 0),
                         (T["revoke_device"], 1), (T["export"], 0), (T["refresh"], 0)])
por = table(app.tv_por, [(T["add_user"], 0), (T["reset_pw"], 0), (T["change_group"], 0),
                         (T["del_user"], 1), (T["export"], 0), (T["refresh"], 0)])
onl = table(app.tv_on, [(T.get("trust_device", "وثّق هذا الجهاز"), 0),
                        (T.get("cut_user", "افصل"), 1), (T["refresh"], 0)])
grp = table(app.tv_grp, [(T["refresh"], 0)])
log = html.escape(app.txt_log.buffer[-2600:])

PANELS = {0: dev, 1: por, 2: onl, 3: grp}

tabhtml = ""
panelhtml = ""
for i, name in enumerate(TABS):
    tabhtml += "<button class='tab%s' data-i='%d'>%s</button>" % (
        " on" if i == 0 else "", i, html.escape(name.strip()))
    if i in PANELS:
        body = PANELS[i]
    elif i == 4:
        body = """<div class='form'>
        <label>%s</label><input value="10.0.1.1">
        <label>%s</label><input value="admin">
        <label>كلمة سر حسابات الماك المشتركة</label><input value="CHANGE-ME-SHARED-MAC-PASSWORD">
        <label>المجموعة الافتراضية للأجهزة</label><input value="grp_staff">
        <label>لغة الواجهة</label><input value="عربي / English">
        <div class='bar'><button>حفظ الإعدادات</button></div></div>""" % (
            html.escape(T["host"]), html.escape(T["user"]))
    else:
        body = "<pre class='log'>%s</pre>" % log
    panelhtml += "<div class='panel%s' data-i='%d'>%s</div>" % (
        " on" if i == 0 else "", i, body)

doc = """<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8">
<title>معاينة واجهة AR730 Access Manager</title>
<style>
:root{--bg:#eceff1;--card:#fff;--ink:#16232b;--mut:#6b7c86;--line:#d3dbe0;--accent:#1f6f8b}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:14px/1.6 "Segoe UI",system-ui,"Noto Naskh Arabic",sans-serif;padding:24px}
.note{max-width:1100px;margin:0 auto 16px;background:#fff6e5;border:1px solid #e8cf9a;
 border-right:4px solid #c98a12;border-radius:8px;padding:12px 16px;font-size:13px}
.win{max-width:1100px;margin:0 auto;background:var(--card);border:1px solid var(--line);
 border-radius:10px;overflow:hidden;box-shadow:0 8px 30px rgba(20,40,55,.13)}
.titlebar{background:#243b47;color:#eaf2f5;padding:9px 14px;font-size:13px;
 display:flex;justify-content:space-between;align-items:center}
.dots{display:flex;gap:6px}.dots i{width:11px;height:11px;border-radius:50%;background:#5d7784;display:block}
.top{display:flex;gap:10px;align-items:center;padding:12px 14px;border-bottom:1px solid var(--line);
 flex-wrap:wrap;background:#f6f8f9}
.top label{color:var(--mut);font-size:13px}
.top input{border:1px solid var(--line);border-radius:5px;padding:5px 9px;font:inherit;font-size:13px}
.state{margin-inline-start:auto;color:#16704a;font-weight:600;font-size:13px}
.tabs{display:flex;gap:2px;padding:10px 12px 0;background:#f6f8f9;border-bottom:1px solid var(--line);
 flex-wrap:wrap}
.tab{border:1px solid var(--line);border-bottom:none;background:#e6ebee;color:#4a5c66;
 padding:8px 16px;border-radius:8px 8px 0 0;cursor:pointer;font:inherit;font-size:13px}
.tab.on{background:#fff;color:var(--ink);font-weight:600;position:relative;top:1px}
.panel{display:none;padding:14px}.panel.on{display:block}
.bar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
button{font:inherit;font-size:13px;padding:6px 14px;border:1px solid var(--line);
 background:#f2f5f6;border-radius:6px;cursor:pointer}
button.danger{color:#a3301c;border-color:#e3bdb5;background:#fdf3f1}
table{width:100%;border-collapse:collapse;font-size:13px}
th{background:#eef2f4;text-align:right;padding:9px 10px;border-bottom:2px solid var(--line);font-weight:600}
td{padding:9px 10px;border-bottom:1px solid #eef1f3}
tr.revoked td{color:#8a8a8a;text-decoration:line-through}
tr.orphan td{color:#8a5600}
tr.missing td{color:#a3301c}
.log{background:#0f1a20;color:#dae8ec;padding:14px;border-radius:8px;overflow:auto;
 max-height:420px;font:12px/1.55 "Cascadia Mono",Consolas,monospace;direction:ltr;text-align:left}
.form{display:grid;grid-template-columns:220px 1fr;gap:10px 14px;max-width:640px;align-items:center}
.form label{color:var(--mut)}
.form input{border:1px solid var(--line);border-radius:5px;padding:6px 10px;font:inherit;font-size:13px}
.form .bar{grid-column:1/-1;margin-top:8px}
.status{border-top:1px solid var(--line);background:#f6f8f9;padding:8px 14px;
 color:var(--mut);font-size:12.5px}
</style>
<div class="note"><b>هذه معاينة لشكل الواجهة، وليست لقطة شاشة.</b>
البيانات والعناوين والأعمدة مقروءة من البرنامج نفسه في وضع التجربة، فهي تطابق ما ستراه.
الأزرار هنا لا تعمل عدا التنقل بين التبويبات.</div>
<div class="win">
 <div class="titlebar"><span>__TITLE__</span><span class="dots"><i></i><i></i><i></i></span></div>
 <div class="top">
   <label>__HOST__</label><input value="10.0.1.1" size="10">
   <label>__USER__</label><input value="admin" size="8">
   <label>__PASS__</label><input type="password" value="demodemo" size="10">
   <button>__CONN__</button>
   <span class="state">● __ON__ &nbsp;AR730</span>
 </div>
 <div class="tabs">__TABS__</div>
 __PANELS__
 <div class="status">__STATUS__</div>
</div>
<script>
document.querySelectorAll('.tab').forEach(function(b){
  b.onclick=function(){
    document.querySelectorAll('.tab').forEach(function(x){x.classList.remove('on')});
    document.querySelectorAll('.panel').forEach(function(x){x.classList.remove('on')});
    b.classList.add('on');
    var p=document.querySelector(".panel[data-i='"+b.dataset.i+"']");
    if(p)p.classList.add('on');
  };
});
</script></html>"""

doc = (doc.replace("__TITLE__", html.escape("%s  v%s" % (T["title"], M.APP_VERSION)))
          .replace("__HOST__", html.escape(T["host"]))
          .replace("__USER__", html.escape(T["user"]))
          .replace("__PASS__", html.escape(T["password"]))
          .replace("__CONN__", html.escape(T["disconnect"]))
          .replace("__ON__", html.escape(T["status_on"]))
          .replace("__TABS__", tabhtml)
          .replace("__PANELS__", panelhtml)
          .replace("__STATUS__", html.escape(T["ok_added"])))

docs = os.path.join(APPDIR, "docs")
if not os.path.isdir(docs):
    os.makedirs(docs)
out = os.path.join(docs, "interface-preview.html")
open(out, "w", encoding="utf-8").write(doc)
print("wrote", out, len(doc), "bytes")
shutil.rmtree(WORK, ignore_errors=True)
