#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AR730 Access Manager
====================
أداة إدارة التحكم بالوصول على Huawei NetEngine AR730.

تدير:
  - القائمة البيضاء لعناوين الماك (دخول صامت بلا صفحة تسجيل دخول)
  - حسابات بوابة الدخول (Portal)
  - مجموعات الصلاحيات (user-group -> ACL)
  - عرض المتصلين حالياً وفصلهم

تتصل بالراوتر عبر SSH وتنفذ الأوامر نيابة عن المستخدم، وتتحقق من كل
تغيير بإعادة قراءته من الجهاز قبل أن تعلن نجاحه، ثم تحفظ الإعداد.

التشغيل:
    pip install paramiko
    python ar730_manager.py

بناء ملف exe لويندوز:
    pip install pyinstaller
    pyinstaller --onefile --windowed --name AR730Manager ar730_manager.py
"""

import json
import os
import re
import sys
import threading
import queue
import time
import datetime
import csv

try:
    import tkinter as tk
    from tkinter import ttk, messagebox, simpledialog, filedialog
except ImportError:
    sys.stderr.write("tkinter غير مثبت. على لينكس: sudo apt install python3-tk\n")
    raise

try:
    import paramiko
except ImportError:
    paramiko = None


# ----------------------------------------------------------------------------
# الإعدادات الافتراضية — تُحفظ في ar730_settings.json بجانب البرنامج
# ----------------------------------------------------------------------------

APP_NAME = "AR730 Access Manager"
APP_VERSION = "1.0"
VENDOR = "AFZ Systems"
DEFAULT_SSH_PORT = 22
# مساحة اسم الراوتر داخل تسمية الحالة؛ ما زاد عنها يُختصر بدل أن يوسّع الشريط
HOSTNAME_ROOM = 12
DEMO_STATE_TEXT = "● وضع التجربة / DEMO"

# لوحة واحدة يشتق منها كل لون في الواجهة، بدل ألوان متناثرة في الشيفرة
C = {
    "bg":        "#f2f4f7",   # خلفية النافذة
    "surface":   "#ffffff",   # البطاقات والجداول
    "border":    "#dfe3e8",
    "text":      "#17212b",
    "muted":     "#6a7a87",
    "accent":    "#1f6feb",
    "accent_hi": "#1a5cc8",
    "accent_bg": "#e8f0fe",
    "danger":    "#c2352b",
    "danger_hi": "#a52a21",
    "ok":        "#107a52",
    "warn":      "#9a6100",
    "sel":       "#dbe9fd",
    "head_bg":   "#f7f9fb",
    "console":   "#111a21",
    "console_fg": "#cfe0e8",
}

# مرشّحات الخطوط بالترتيب — يُختار أول متوفر على الجهاز
FONTS_AR = ("SF Arabic", "Geeza Pro", "Dubai", "Noto Naskh Arabic",
            "Segoe UI", "Tahoma", "Helvetica Neue")
FONTS_EN = ("SF Pro Text", "Helvetica Neue", "Segoe UI Variable Text",
            "Segoe UI", "Inter", "Helvetica")
FONTS_MONO = ("SF Mono", "Menlo", "Consolas", "DejaVu Sans Mono",
              "Courier New", "Courier")


def pick_font(root, candidates, fallback="Helvetica"):
    """أول عائلة خط متوفرة فعلاً على الجهاز، وإلا الاحتياطي."""
    try:
        from tkinter import font as tkfont
        available = set(tkfont.families(root))
    except Exception:
        return fallback
    for name in candidates:
        if name in available:
            return name
    return fallback
VENDOR_EMAIL = "amjadzarour@gmail.com"

DEFAULT_SETTINGS = {
    "host": "10.0.1.1",
    "port": 22,
    "username": "admin",
    # كلمة المرور المشتركة لحسابات الماك.
    # يجب أن تطابق حرفياً القيمة المضبوطة في:
    #   mac-access-profile name m_wl
    #    mac-authen username macaddress format without-hyphen password cipher <هنا>
    "mac_shared_password": "CHANGE-ME-SHARED-MAC-PASSWORD",
    "default_mac_group": "grp_staff",
    "default_portal_group": "grp_staff",
    "known_groups": ["grp_managers", "grp_staff", "grp_infra"],
    # نطاق حسابات البوابة — يُستخدم فقط عند فشل فصل الجلسة بالاسم المجرد
    "portal_domain": "portalusers",
    "ui_lang": "ar",
    "auto_save_config": True,
}

BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
SETTINGS_FILE = os.path.join(BASE_DIR, "ar730_settings.json")
DB_FILE = os.path.join(BASE_DIR, "ar730_devices.json")
LOG_FILE = os.path.join(BASE_DIR, "ar730_session.log")


# ----------------------------------------------------------------------------
# النصوص — عربي / إنجليزي
# ----------------------------------------------------------------------------

TXT = {
    "ar": {
        "title": "أداة إدارة الوصول — AR730",
        "connect": "اتصال",
        "disconnect": "قطع الاتصال",
        "host": "عنوان الراوتر",
        "port": "المنفذ",
        "user": "اسم المستخدم",
        "password": "كلمة المرور",
        "status_off": "غير متصل",
        "status_on": "متصل",
        "tab_devices": "الأجهزة الموثوقة",
        "tab_portal": "حسابات البوابة",
        "tab_online": "المتصلون الآن",
        "tab_groups": "مجموعات الصلاحيات",
        "tab_log": "سجل الأوامر",
        "tab_settings": "الإعدادات",
        "col_mac": "عنوان الماك",
        "col_name": "الاسم الوصفي",
        "col_group": "المجموعة",
        "col_state": "الحالة",
        "col_added": "أُضيف",
        "col_note": "ملاحظة",
        "col_members": "الأعضاء",
        "lang_label": "اللغة",
        "port_hint": "فارغ = 22",
        "err_bad_port": "المنفذ يجب أن يكون رقماً بين 1 و 65535، أو اتركه فارغاً لاستخدام 22.",
        "search": "بحث:",
        "search_hint": "ابحث في الماك أو الاسم أو الحالة",
        "search_clear": "مسح",
        "shown_of": "%(shown)d من %(total)d",
        "no_match": "لا نتيجة تطابق البحث.",
        "dlg_ok": "موافق",
        "dlg_cancel": "إلغاء",
        "data_file": "ملف البيانات:",
        "col_user": "اسم الحساب",
        "col_ip": "عنوان IP",
        "col_status": "الحالة",
        "col_acl": "القائمة",
        "col_id": "الرقم",
        "add_device": "إضافة جهاز",
        "revoke_device": "سحب الثقة",
        "change_group": "تغيير المجموعة",
        "edit_meta": "تعديل الاسم والملاحظة",
        "about_title": "حول البرنامج",
        "about_close": "إغلاق",
        "copy_email": "نسخ البريد",
        "email_copied": "نُسخ البريد إلى الحافظة.",
        "about_hint": "اضغط للتفاصيل وتعليمات الاستخدام",
        "add_user": "إضافة حساب",
        "reset_pw": "تغيير كلمة المرور",
        "del_user": "حذف الحساب",
        "refresh": "تحديث",
        "cut_user": "فصل المتصل",
        "export": "تصدير CSV",
        "state_active": "فعّال",
        "state_revoked": "ملغى",
        "state_orphan": "غير مسجّل محلياً",
        "state_missing": "مفقود من الراوتر",
        "ask_mac": "عنوان الماك (أي صيغة):",
        "ask_name": "الاسم الوصفي (صاحب الجهاز أو موقعه):",
        "ask_note": "ملاحظة (اختياري):",
        "ask_reason": "سبب السحب:",
        "ask_user": "اسم الحساب (حروف وأرقام بلا مسافات):",
        "ask_pw": "كلمة المرور (٨ محارف فأكثر):",
        "ask_group": "المجموعة:",
        "err_no_conn": "غير متصل بالراوتر. اضغط «اتصال» أولاً.",
        "err_bad_mac": "عنوان ماك غير صالح. المتوقع ١٢ رقماً ست عشرياً.",
        "err_dup": "هذا العنوان مسجّل مسبقاً على الراوتر.",
        "err_bad_user": "اسم حساب غير صالح.",
        "err_short_pw": "كلمة المرور قصيرة — ٨ محارف على الأقل.",
        "err_pw_eq_user": "كلمة المرور لا يجوز أن تساوي اسم الحساب.",
        "ok_added": "تمت الإضافة والتحقق منها على الراوتر.",
        "ok_revoked": "سُحبت الثقة وفُصل الجهاز.",
        "ok_group": "تم تغيير المجموعة وإعادة المصادقة.",
        "ok_edit": "حُفظ الاسم والملاحظة محلياً (لا يمسّ الراوتر).",
        "ok_saved": "حُفظ الإعداد على الراوتر.",
        "confirm_revoke": "سحب الثقة عن هذا الجهاز وفصله فوراً؟",
        "confirm_del": "حذف هذا الحساب نهائياً من الراوتر؟",
        "warn_no_group": "تحذير: حساب بلا مجموعة يحصل على وصول كامل بلا قيد.",
        "no_selection": "اختر سطراً من الجدول أولاً.",
        "busy": "جارٍ التنفيذ على الراوتر… انتظر لحظة",
        "connecting": "جارٍ الاتصال…",
        "working": "جارٍ التنفيذ…",
        "mac_pw_label": "كلمة مرور حسابات الماك المشتركة",
        "mac_pw_hint": "يجب أن تطابق القيمة في mac-access-profile على الراوتر",
        "autosave": "حفظ الإعداد تلقائياً بعد كل تغيير",
        "save_settings": "حفظ الإعدادات",
        "groups_hint": "المجموعات تُقرأ من الراوتر. الصلاحيات تُضبط بـ acl-id داخل كل مجموعة.",
        "sync_note": "الحقيقة عند الراوتر — الملف المحلي يحمل الأسماء والسجل فقط.",
        "lang_note": "تغيير اللغة يحتاج إعادة تشغيل البرنامج",
    },
    "en": {
        "title": "AR730 Access Manager",
        "connect": "Connect",
        "disconnect": "Disconnect",
        "host": "Router IP",
        "port": "Port",
        "user": "Username",
        "password": "Password",
        "status_off": "Disconnected",
        "status_on": "Connected",
        "tab_devices": "Trusted Devices",
        "tab_portal": "Portal Accounts",
        "tab_online": "Online Users",
        "tab_groups": "Permission Groups",
        "tab_log": "Command Log",
        "tab_settings": "Settings",
        "col_mac": "MAC Address",
        "col_name": "Description",
        "col_group": "Group",
        "col_state": "State",
        "col_added": "Added",
        "col_note": "Note",
        "col_members": "Members",
        "lang_label": "Language",
        "port_hint": "empty = 22",
        "err_bad_port": "The port must be a number between 1 and 65535, or leave it empty to use 22.",
        "search": "Search:",
        "search_hint": "Search MAC, name or status",
        "search_clear": "Clear",
        "shown_of": "%(shown)d of %(total)d",
        "no_match": "Nothing matches the search.",
        "dlg_ok": "OK",
        "dlg_cancel": "Cancel",
        "data_file": "Data file:",
        "col_user": "Account",
        "col_ip": "IP Address",
        "col_status": "Status",
        "col_acl": "ACL",
        "col_id": "ID",
        "add_device": "Add Device",
        "revoke_device": "Revoke",
        "change_group": "Change Group",
        "edit_meta": "Edit Name / Note",
        "about_title": "About",
        "about_close": "Close",
        "copy_email": "Copy e-mail",
        "email_copied": "E-mail copied to clipboard.",
        "about_hint": "Click for details and usage instructions",
        "add_user": "Add Account",
        "reset_pw": "Reset Password",
        "del_user": "Delete Account",
        "refresh": "Refresh",
        "cut_user": "Disconnect User",
        "export": "Export CSV",
        "state_active": "Active",
        "state_revoked": "Revoked",
        "state_orphan": "Not in local records",
        "state_missing": "Missing on router",
        "ask_mac": "MAC address (any format):",
        "ask_name": "Description (owner or location):",
        "ask_note": "Note (optional):",
        "ask_reason": "Reason for revoking:",
        "ask_user": "Account name (letters/digits, no spaces):",
        "ask_pw": "Password (8+ characters):",
        "ask_group": "Group:",
        "err_no_conn": "Not connected. Press Connect first.",
        "err_bad_mac": "Invalid MAC. Expected 12 hex digits.",
        "err_dup": "This MAC already exists on the router.",
        "err_bad_user": "Invalid account name.",
        "err_short_pw": "Password too short - 8 characters minimum.",
        "err_pw_eq_user": "Password must not equal the account name.",
        "ok_added": "Added and verified on the router.",
        "ok_revoked": "Revoked and disconnected.",
        "ok_group": "Group changed, session re-authenticated.",
        "ok_edit": "Name and note saved locally (router untouched).",
        "ok_saved": "Configuration saved on the router.",
        "confirm_revoke": "Revoke trust for this device and disconnect it now?",
        "confirm_del": "Permanently delete this account from the router?",
        "warn_no_group": "Warning: an account with no group gets unrestricted access.",
        "no_selection": "Select a row from the table first.",
        "busy": "Working on the router... please wait",
        "connecting": "Connecting...",
        "working": "Working...",
        "mac_pw_label": "Shared password for MAC accounts",
        "mac_pw_hint": "Must match the value in mac-access-profile on the router",
        "autosave": "Save router configuration after every change",
        "save_settings": "Save Settings",
        "groups_hint": "Groups are read from the router. Permissions come from acl-id in each group.",
        "sync_note": "The router is the source of truth - the local file holds names and history.",
        "lang_note": "Language change requires restarting the application",
    },
}


# ----------------------------------------------------------------------------
# نص نافذة "حول البرنامج"
# ----------------------------------------------------------------------------

ABOUT_AR = u"""ما هذا البرنامج
‏
أداة لإدارة من يدخل شبكة المكتب عبر راوتر Huawei NetEngine AR730، دون أن
تحتاج إلى معرفة أي أمر من أوامر الجهاز. كل ما تضغطه هنا يتحول إلى أوامر
تُرسل إلى الراوتر عبر اتصال مشفّر، ويمكنك رؤيتها كاملة في تبويب "سجل الأوامر".

طريقتان لدخول الشبكة
‏
١) جهاز موثوق — تسجّل عنوان الماك في القائمة البيضاء، فيدخل الجهاز
   تلقائياً بلا صفحة تسجيل دخول. مناسب للكمبيوترات والطابعات والكاميرات
   ونقاط الوصول.
٢) حساب بوابة — اسم مستخدم وكلمة سر، يدخل بهما صاحبه من صفحة تسجيل
   الدخول. هذا هو المناسب للهواتف.

لماذا الهواتف لا تصلح للقائمة البيضاء: الهواتف الحديثة تولّد عنوان ماك
عشوائياً لكل شبكة، فيتغير العنوان ويسقط التوثيق. استخدم حساب بوابة لها.

خطوات الاستخدام
‏
١) اكتب عنوان الراوتر واسم المستخدم وكلمة السر، ثم اضغط "اتصال".
   كلمة السر تُطلب في كل مرة ولا تُحفظ في أي ملف — هذا مقصود.
   خانة المنفذ اتركها فارغة ما لم يكن الراوتر يستمع على منفذ غير 22.
٢) تبويب "المتصلون الآن" يريك من يستخدم الشبكة هذه اللحظة. إن رأيت جهازاً
   تعرفه وتريد إعفاءه من صفحة الدخول، اختر سطره واضغط "وثّق هذا الجهاز"
   فيُنقل عنوانه إلى نموذج الإضافة جاهزاً.
٣) تبويب "الأجهزة الموثوقة" لإضافة جهاز يدوياً أو تغيير مجموعته أو إلغائه.
٤) تبويب "حسابات البوابة" لإنشاء حساب لموظف أو ضيف وتغيير كلمة سره.
٥) تبويب "مجموعات الصلاحيات" يعرض المجموعات المتاحة ورقم قائمة التحكم
   المرتبطة بكل واحدة.

أشياء يحسن أن تعرفها قبل أن تستخدمه
‏
• المجموعة إلزامية. حساب بلا مجموعة يحصل على وصول غير مقيّد، والبرنامج
  يحذّرك إن حاولت الحفظ بلا مجموعة.
• تغيير المجموعة يقطع الجلسة القائمة. هذا ليس خللاً: الصلاحيات الجديدة
  لا تسري إلا بعد إعادة المصادقة، فالبرنامج يقطع الجلسة عمداً ليعود
  الجهاز بالصلاحيات الصحيحة خلال دقيقة تقريباً. لا تفعلها لمن هو في
  منتصف عمل مهم.
• الإلغاء لا يعني الحذف. عند إلغاء جهاز أو حساب يُحذف من الراوتر فعلاً
  ويفقد الوصول فوراً، لكنه يبقى في السجل المحلي بحالة "ملغى" مع التاريخ
  والسبب، ويظهر بلون رمادي. هكذا يبقى لديك أثر لمن كان لديه وصول ومتى سُحب.
• الاسم الوصفي والملاحظة بيانات محلية فقط. الراوتر لا يعرفهما، لذلك
  تعديلهما لا يرسل أي أمر إلى الراوتر ولا يحتاج اتصالاً ولا يقطع جلسة أحد.
  عدّلهما بزر "تعديل الاسم والملاحظة" أو بنقرة مزدوجة على السطر.
• الحفظ تلقائي. بعد كل تغيير ناجح يُنفَّذ أمر الحفظ على الراوتر كي لا
  يضيع العمل عند إعادة تشغيل الجهاز.
• التحقق بعد كل كتابة. بعد أي تعديل يعيد البرنامج قراءة إعداد الراوتر
  ليتأكد أن التغيير ثبت فعلاً قبل أن يقول "تم".

إن لم ينجح الاتصال
‏
• الراوتر يقبل الإدارة من شبكة الإدارة فقط. يجب أن يكون عنوان جهازك ضمن
  شبكات الإدارة المسموح بها في الراوتر. من أي شبكة أخرى لن يُقبل الاتصال أصلاً.
  إن احتجت الإدارة من خارج المكتب فالطريق الصحيح هو VPN إلى شبكة الإدارة.
• إن دخلت جهازاً إلى القائمة البيضاء ولم يتصل، فغالباً أن كلمة السر
  المشتركة في تبويب "الإعدادات" لا تطابق ما هو مضبوط داخل الراوتر.
  يجب أن تتطابق حرفياً.
• تبويب "سجل الأوامر" يعرض كل أمر أُرسل وكل رد جاء. ابدأ منه دائماً عند
  أي خلل، وأرسل نسخة منه عند طلب الدعم.

وضع التجربة
‏
داخل البرنامج راوتر وهمي كامل يفرض قواعد الجهاز الحقيقي. شغّله بوضع
التجربة لتتدرب على كل الأزرار بلا أي أثر على الشبكة. تكتب كلمة DEMO في
شريط العنوان كي لا يلتبس الوضعان. هذا هو المكان المناسب لتدريب موظف جديد.

الملفات التي ينشئها البرنامج بجانبه
‏
ar730_settings.json   الإعدادات (لا تُحفظ فيه كلمة سر الاتصال إطلاقاً)
ar730_devices.json    الأسماء والملاحظات والسجل التاريخي
ar730_session.log     نسخة من سجل الأوامر

خذ نسخة احتياطية من ar730_devices.json بين حين وآخر — فيه وحده أسماء
أصحاب الأجهزة وسجل من سُحبت منه الصلاحية ومتى.

الدعم
‏
%(vendor)s
%(email)s
""" % {"vendor": VENDOR, "email": VENDOR_EMAIL}


ABOUT_EN = u"""What this program is

A tool for managing who gets onto the office network through the Huawei
NetEngine AR730 router, without needing to know any of the device's commands.
Everything you click here becomes commands sent to the router over an
encrypted connection; you can read them all in the Command Log tab.

Two ways onto the network

1) Trusted device - you register the MAC address in the whitelist and the
   device joins automatically with no login page. Suitable for computers,
   printers, cameras and access points.
2) Portal account - a username and password the person types into the login
   page. This is what phones should use.

Why phones do not belong in the whitelist: modern phones generate a random
MAC address per network, so the address changes and the trust breaks. Give
them a portal account instead.

How to use it

1) Enter the router address, username and password, then press Connect.
   The password is asked for every time and is never written to any file.
   That is deliberate. Leave the port box empty unless the router listens
   on a port other than 22.
2) The Online Now tab shows who is using the network right now. If you see a
   device you recognise and want to spare it the login page, select its row
   and press Trust This Device - its address is carried into the add form.
3) The Trusted Devices tab adds a device manually, changes its group, or
   revokes it.
4) The Portal Accounts tab creates an account for a staff member or guest
   and changes its password.
5) The Permission Groups tab lists the available groups and the access
   control list number bound to each one.

Things worth knowing before you use it

- The group is mandatory. An account with no group gets unrestricted access,
  and the program warns you if you try to save without one.
- Changing the group cuts the existing session. This is not a fault: new
  permissions only take effect after re-authentication, so the program cuts
  the session deliberately and the device returns with the correct
  permissions within about a minute. Do not do it to someone in the middle
  of important work.
- Revoking is not deleting. Revoking a device or account really does remove
  it from the router and access is lost immediately, but it stays in the
  local record marked revoked, with the date and the reason, shown in grey.
  That leaves you a trace of who had access and when it was withdrawn.
- The description and note are local data only. The router does not know
  them, so editing them sends no command to the router, needs no connection
  and cuts nobody's session. Edit them with the Edit Name / Note button or
  by double-clicking the row.
- Saving is automatic. After every successful change the save command runs
  on the router so nothing is lost when the device restarts.
- Verification after every write. After any change the program re-reads the
  router configuration to confirm the change actually took hold before it
  reports success.

If the connection fails

- The router accepts management from the management network only. Your
  machine's address must be within the management networks allowed on the router. From any
  other network the connection is refused outright. If you need to manage it
  from outside the office, the correct route is a VPN into the management
  network.
- If you whitelisted a device and it still cannot connect, the shared
  password in the Settings tab most likely does not match what is configured
  inside the router. They must match exactly.
- The Command Log tab shows every command sent and every reply received.
  Always start there when something goes wrong, and include a copy of it
  when asking for support.

Demo mode

The program contains a complete simulated router that enforces the real
device's rules. Run it in demo mode to practise every button with no effect
on the network whatsoever. The title bar reads DEMO so the two modes are
never confused. This is the place to train a new member of staff.

Files the program creates beside itself

ar730_settings.json   settings (the connection password is never stored)
ar730_devices.json    names, notes and the historical record
ar730_session.log     a copy of the command log

Take a backup of ar730_devices.json from time to time - it alone holds the
device owners' names and the record of whose access was withdrawn and when.

Support

%(vendor)s
%(email)s
""" % {"vendor": VENDOR, "email": VENDOR_EMAIL}

ABOUT = {"ar": ABOUT_AR, "en": ABOUT_EN}


# ----------------------------------------------------------------------------
# أدوات مساعدة
# ----------------------------------------------------------------------------

def row_matches(query, values, mac_hint=None):
    """
    يطابق نص البحث على قيم الصف كلها. يتجاهل حالة الأحرف، ويطابق الماك
    ولو كُتب بلا فواصل — فمن يكتب 00005e00 يجد 00:00:5E:00:53:01.
    """
    if not query:
        return True
    q = query.strip().lower()
    if not q:
        return True
    hay = " ".join(str(v) for v in values if v is not None).lower()
    if q in hay:
        return True
    # مطابقة الماك بلا فواصل في الاتجاهين
    q_hex = re.sub(r"[^0-9a-f]", "", q)
    if q_hex:
        if mac_hint and q_hex in mac_hint.lower():
            return True
        hay_hex = re.sub(r"[^0-9a-f]", "", hay)
        if len(q_hex) >= 3 and q_hex in hay_hex:
            return True
    return False


def normalize_mac(raw):
    """يحوّل أي صيغة ماك إلى ١٢ رقماً ست عشرياً صغيرة، أو None إن كانت غير صالحة."""
    if not raw:
        return None
    hexonly = re.sub(r"[^0-9a-fA-F]", "", raw)
    if len(hexonly) != 12:
        return None
    return hexonly.lower()


def mac_dashed(mac12):
    """00005e005302 -> 0000-5e00-5302  (صيغة أوامر cut و display)"""
    return "%s-%s-%s" % (mac12[0:4], mac12[4:8], mac12[8:12])


def mac_pretty(mac12):
    """00005e005302 -> 00:00:5E:00:53:02  (للعرض البشري)"""
    return ":".join(mac12[i:i + 2] for i in range(0, 12, 2)).upper()


def now_stamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


# ----------------------------------------------------------------------------
# جلسة SSH مع الراوتر
# ----------------------------------------------------------------------------

class RouterError(Exception):
    pass


class RouterSession(object):
    """
    غلاف حول جلسة SSH تفاعلية مع VRP.

    نستخدم قناة تفاعلية لا exec_command لأن أوامر VRP مثل service-type و save
    تطرح أسئلة [Y/N] ويجب الإجابة عليها في وقتها. إرسال كتلة نصية واحدة
    يبتلع الإجابة ويعطي خطأ مضللاً.
    """

    PROMPT_RE = re.compile(r"[\r\n][<\[][^\r\n<>\[\]]{1,80}[>\]]\s*$")
    YESNO_RE = re.compile(r"\[Y/N\]|\[y/n\]|\(y/n\)|\[Y/N\]:|Continue\?|continue\?", re.I)
    MORE_RE = re.compile(r"---- More ----")

    def __init__(self, log_fn=None):
        self.client = None
        self.chan = None
        self.log_fn = log_fn or (lambda s: None)
        self.connected = False
        self.hostname = ""

    # -- الاتصال -------------------------------------------------------------

    def connect(self, host, port, username, password, timeout=15):
        if paramiko is None:
            raise RouterError(
                "مكتبة paramiko غير مثبتة.\nنفّذ: pip install paramiko"
            )
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        # أجهزة VRP القديمة تستخدم خوارزميات قديمة؛ نسمح بها صراحة
        self.client.connect(
            hostname=host,
            port=int(port),
            username=username,
            password=password,
            timeout=timeout,
            allow_agent=False,
            look_for_keys=False,
        )
        self.chan = self.client.invoke_shell(width=512, height=1000)
        self.chan.settimeout(30)
        time.sleep(1.2)
        banner = self._drain()
        self.log_fn(banner)
        self.connected = True
        m = re.search(r"[<\[]([^>\]\r\n]+)[>\]]", banner)
        self.hostname = m.group(1) if m else host
        # إيقاف الترقيم — وإلا ابتلع "---- More ----" أول حرف من الأمر التالي
        self.send("screen-length 0 temporary")
        return True

    def close(self):
        try:
            if self.chan:
                self.chan.close()
            if self.client:
                self.client.close()
        except Exception:
            pass
        self.connected = False
        self.chan = None
        self.client = None

    # -- الإرسال والقراءة ----------------------------------------------------

    def _drain(self, idle=0.4, limit=6.0):
        """يقرأ كل ما هو متاح حتى يتوقف التدفق."""
        buf = ""
        start = time.time()
        last = time.time()
        while time.time() - start < limit:
            if self.chan.recv_ready():
                chunk = self.chan.recv(65535).decode("utf-8", errors="replace")
                buf += chunk
                last = time.time()
            else:
                if buf and (time.time() - last) > idle:
                    break
                time.sleep(0.05)
        return buf

    def send(self, command, timeout=25, answer_yes=True):
        """
        يرسل أمراً ويعيد المخرجات كاملة.
        يجيب تلقائياً على أسئلة [Y/N] بـ Y، ويطعم الترقيم إن ظهر.
        """
        if not self.connected or self.chan is None:
            raise RouterError("not connected")

        self.log_fn("\n>>> " + command)
        self.chan.send(command + "\n")

        buf = ""
        start = time.time()
        answered = 0
        while time.time() - start < timeout:
            if self.chan.recv_ready():
                buf += self.chan.recv(65535).decode("utf-8", errors="replace")

                if self.MORE_RE.search(buf):
                    self.chan.send(" ")
                    buf = self.MORE_RE.sub("", buf)
                    continue

                tail = buf[-400:]
                if answer_yes and self.YESNO_RE.search(tail) and answered < 40:
                    # ننتظر لحظة حتى يكتمل السؤال ثم نجيب
                    time.sleep(0.25)
                    self.chan.send("Y\n")
                    answered += 1
                    # نمحو نص السؤال من المخزن وإلا بقي في آخر ٤٠٠ حرف
                    # فأجبنا عليه مرة ثانية وأُرسل Y زائد إلى موجّه الأوامر
                    buf = self.YESNO_RE.sub("", buf) + "Y\n"
                    time.sleep(0.2)
                    continue

                if self.PROMPT_RE.search(buf):
                    break
            else:
                time.sleep(0.06)

        self.log_fn(buf)
        return buf

    def send_many(self, commands, timeout=25):
        out = []
        for c in commands:
            out.append(self.send(c, timeout=timeout))
        return "\n".join(out)

    # -- عمليات عالية المستوى ------------------------------------------------

    def save_config(self):
        """VRP يسأل [Y/N] عند الحفظ — send يجيب تلقائياً."""
        out = self.send("save", timeout=90)
        return "successfully" in out.lower() or "saved" in out.lower()

    def read_aaa(self):
        """يقرأ حسابات AAA من الراوتر — هذه هي مصدر الحقيقة."""
        return self.send("display current-configuration configuration aaa", timeout=40)

    def read_groups(self):
        return self.send("display user-group", timeout=20)

    def read_group_acls(self):
        """
        لا نستخدم "| include acl-id" لأن الترشيح يحذف سطر user-group نفسه
        فيصبح رقم الـACL بلا صاحب. نقرأ الإعداد كاملاً ونحلله.
        """
        return self.send("display current-configuration", timeout=90)

    def read_online(self):
        return self.send("display access-user", timeout=30)


# ----------------------------------------------------------------------------
# تحليل مخرجات الراوتر
# ----------------------------------------------------------------------------

def parse_local_users(aaa_output):
    """
    يستخرج الحسابات من مخرجات display current-configuration configuration aaa.
    يعيد dict: username -> {service_types:set, group:str|None, has_password:bool}
    """
    users = {}
    for line in aaa_output.splitlines():
        line = line.strip()
        if not line.startswith("local-user "):
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        name = parts[1]
        rec = users.setdefault(
            name, {"service_types": set(), "group": None, "has_password": False}
        )
        if "service-type" in parts:
            i = parts.index("service-type")
            for st in parts[i + 1:]:
                if st in ("8021x", "web", "ssh", "http", "telnet", "terminal",
                          "ftp", "ppp", "sslvpn", "bind", "x25-pad"):
                    rec["service_types"].add(st)
        if "user-group" in parts:
            i = parts.index("user-group")
            if i + 1 < len(parts):
                rec["group"] = parts[i + 1]
        if "password" in parts:
            rec["has_password"] = True
        if "privilege" in parts and "level" in parts:
            try:
                i = parts.index("level")
                rec["privilege"] = int(parts[i + 1])
            except Exception:
                pass
    return users


def split_user_kinds(users):
    """يفصل حسابات الماك عن حسابات البوابة عن حسابات الإدارة."""
    macs, portals, admins = {}, {}, {}
    mac_re = re.compile(r"^[0-9a-f]{12}$")
    for name, rec in users.items():
        st = rec["service_types"]
        if mac_re.match(name) and ("8021x" in st or not st):
            macs[name] = rec
        elif "web" in st:
            portals[name] = rec
        else:
            admins[name] = rec
    return macs, portals, admins


def parse_groups(group_output, acl_output):
    """يعيد dict: group_name -> acl_id|None"""
    groups = {}
    for line in group_output.splitlines():
        m = re.match(r"^\s*\d+\s+(\S+)\s+\d+\s*$", line)
        if m:
            groups[m.group(1)] = None
    current = None
    for line in acl_output.splitlines():
        s = line.strip()
        m = re.match(r"^user-group\s+(\S+)", s)
        if m:
            current = m.group(1)
            groups.setdefault(current, None)
            continue
        m = re.match(r"^acl-id\s+(\d+)", s)
        if m and current:
            groups[current] = m.group(1)
            continue
        # أي سطر بلا إزاحة يعني أننا خرجنا من كتلة user-group
        if s and not line.startswith((" ", "\t")):
            current = None
    return groups


def parse_online(output):
    """
    يحلل جدول display access-user.
      UserID  Username  IP address  MAC  Status
    """
    rows = []
    for line in output.splitlines():
        s = line.strip()
        if not s or s.startswith("-") or s.startswith("UserID"):
            continue
        if s.lower().startswith("total"):
            continue
        parts = s.split()
        if len(parts) < 4 or not parts[0].isdigit():
            continue
        uid = parts[0]
        uname = parts[1]
        ip = parts[2] if re.match(r"^\d+\.\d+\.\d+\.\d+$", parts[2]) else ""
        mac = ""
        for p in parts:
            if re.match(r"^[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}$", p):
                mac = p
                break
        status = parts[-1]
        if status in ("Pre-authen", "Success", "Authen", "Fail"):
            pass
        else:
            status = " ".join(parts[-2:])
        rows.append({"id": uid, "user": uname, "ip": ip, "mac": mac, "status": status})
    return rows


# ----------------------------------------------------------------------------
# قاعدة البيانات المحلية — أسماء وصفية وسجل
# ----------------------------------------------------------------------------

class LocalDB(object):
    def __init__(self, path=None):
        self.path = path or DB_FILE
        self.data = {"devices": {}, "portal": {}, "history": []}
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                for k in ("devices", "portal", "history"):
                    if k in loaded:
                        self.data[k] = loaded[k]
            except Exception:
                pass

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def log(self, action, target, detail=""):
        self.data["history"].append({
            "when": now_stamp(), "action": action,
            "target": target, "detail": detail,
        })
        self.data["history"] = self.data["history"][-2000:]
        self.save()

    # -- الأجهزة -------------------------------------------------------------

    def device(self, mac12):
        return self.data["devices"].get(mac12)

    def upsert_device(self, mac12, name, group, note=""):
        d = self.data["devices"].setdefault(mac12, {})
        d["name"] = name
        d["group"] = group
        d["note"] = note
        d["state"] = "active"
        d.setdefault("added", now_stamp())
        d.pop("revoked_at", None)
        d.pop("revoke_reason", None)
        self.save()

    def set_device_meta(self, mac12, name, note=""):
        """
        يعدّل الاسم والملاحظة وحدهما. لا يلمس state ولا group ولا added،
        فتعديل جهاز ملغى يبقيه ملغى، وتعديل جهاز على الراوتر بلا سجل محلي
        ينشئ له سجلاً دون أن يدّعي مجموعة لا يعرفها.
        """
        d = self.data["devices"].setdefault(mac12, {})
        d["name"] = name
        d["note"] = note
        d.setdefault("state", "active")
        d.setdefault("group", "")
        d.setdefault("added", now_stamp())
        self.save()

    def revoke_device(self, mac12, reason=""):
        d = self.data["devices"].setdefault(mac12, {"name": "", "group": "", "note": ""})
        d["state"] = "revoked"
        d["revoked_at"] = now_stamp()
        d["revoke_reason"] = reason
        self.save()

    # -- حسابات البوابة ------------------------------------------------------

    def portal(self, username):
        return self.data["portal"].get(username)

    def upsert_portal(self, username, name, group, note=""):
        p = self.data["portal"].setdefault(username, {})
        p["name"] = name
        p["group"] = group
        p["note"] = note
        p["state"] = "active"
        p.setdefault("added", now_stamp())
        p.pop("revoked_at", None)
        self.save()

    def set_portal_meta(self, username, name, note=""):
        """نظير set_device_meta لحسابات البوابة."""
        pr = self.data["portal"].setdefault(username, {})
        pr["name"] = name
        pr["note"] = note
        pr.setdefault("state", "active")
        pr.setdefault("group", "")
        pr.setdefault("added", now_stamp())
        self.save()

    def revoke_portal(self, username, reason=""):
        p = self.data["portal"].setdefault(username, {"name": "", "group": "", "note": ""})
        p["state"] = "revoked"
        p["revoked_at"] = now_stamp()
        p["revoke_reason"] = reason
        self.save()


# ----------------------------------------------------------------------------
# الإعدادات
# ----------------------------------------------------------------------------

def load_settings():
    s = dict(DEFAULT_SETTINGS)
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                s.update(json.load(f))
        except Exception:
            pass
    return s


def save_settings(s):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------------------
# نافذة إدخال متعددة الحقول
# ----------------------------------------------------------------------------

class FieldDialog(tk.Toplevel):
    """نافذة بسيطة بعدة حقول، بعضها قائمة منسدلة."""

    def __init__(self, parent, title, fields, rtl=None, txt=None):
        tk.Toplevel.__init__(self, parent)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result = None
        self._vars = {}

        self.rtl = getattr(parent, "rtl", False) if rtl is None else rtl
        t = txt if txt is not None else getattr(parent, "T", {})
        justify = "right" if self.rtl else "left"
        c_lab, c_fld = (1, 0) if self.rtl else (0, 1)
        s_lab = "w" if self.rtl else "e"
        s_fld = "e" if self.rtl else "w"
        pad_lab = (12, 0) if self.rtl else (0, 12)

        self.configure(background=C["surface"])
        frm = ttk.Frame(self, padding=22, style="Card.TFrame")
        frm.pack(fill="both", expand=True)

        for r, f in enumerate(fields):
            key, label, kind = f["key"], f["label"], f.get("kind", "text")
            ttk.Label(frm, text=label, style="Card.TLabel", justify=justify).grid(
                row=r, column=c_lab, sticky=s_lab, padx=pad_lab, pady=8)
            var = tk.StringVar(value=f.get("default", ""))
            if kind == "combo":
                w = ttk.Combobox(frm, textvariable=var, values=f.get("values", []),
                                 width=32, state="readonly", justify=justify)
            elif kind == "password":
                w = ttk.Entry(frm, textvariable=var, width=34, show="•", justify=justify)
            else:
                w = ttk.Entry(frm, textvariable=var, width=34, justify=justify)
            w.grid(row=r, column=c_fld, sticky=s_fld, pady=8)
            self._vars[key] = var
            if r == 0:
                w.focus_set()

        btns = ttk.Frame(frm, style="Card.TFrame")
        btns.grid(row=len(fields), column=0, columnspan=2, pady=(18, 0),
                  sticky="w" if self.rtl else "e")
        side = "left" if self.rtl else "right"
        ttk.Button(btns, text=t.get("dlg_ok", "OK"), style="Accent.TButton",
                   command=self._ok).pack(side=side, padx=4)
        ttk.Button(btns, text=t.get("dlg_cancel", "Cancel"),
                   command=self._cancel).pack(side=side, padx=4)

        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self._cancel())
        self.update_idletasks()
        self.geometry("+%d+%d" % (parent.winfo_rootx() + 120, parent.winfo_rooty() + 120))
        self.wait_window(self)

    def _ok(self):
        self.result = {k: v.get().strip() for k, v in self._vars.items()}
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


# ----------------------------------------------------------------------------
# التطبيق
# ----------------------------------------------------------------------------

class AboutDialog(tk.Toplevel):
    """بطاقة تعريف البرنامج وتعليمات الاستخدام للمستخدم النهائي."""

    def __init__(self, parent, txt, body, on_copy_msg, rtl=False, fonts=None):
        tk.Toplevel.__init__(self, parent)
        self.title(txt["about_title"])
        self.transient(parent)
        self.grab_set()
        self._on_copy_msg = on_copy_msg
        self.rtl = rtl

        near = "right" if rtl else "left"
        far = "left" if rtl else "right"
        anchor = "e" if rtl else "w"

        self.configure(background=C["surface"])
        frm = ttk.Frame(self, padding=(24, 22), style="Card.TFrame")
        frm.pack(fill="both", expand=True)

        head = ttk.Frame(frm, style="Card.TFrame")
        head.pack(fill="x", pady=(0, 16))
        ttk.Label(head, text="%s  v%s" % (APP_NAME, APP_VERSION),
                  style="H1.TLabel").pack(anchor=anchor)
        ttk.Label(head, text="Powered by %s" % VENDOR, style="Brand.TLabel",
                  background=C["surface"]).pack(anchor=anchor, pady=(4, 0))
        ttk.Label(head, text=VENDOR_EMAIL, style="Brand.TLabel",
                  background=C["surface"]).pack(anchor=anchor)

        ttk.Separator(frm, orient="horizontal").pack(side="top", fill="x", pady=(0, 16))

        # الأزرار تُرصف قبل صندوق النص وبـ side="bottom" كي تحجز مكانها.
        # النص ممتد (expand) فلو رُصف أولاً لابتلع المساحة كلها واختفت
        # الأزرار خارج حدود النافذة.
        btns = ttk.Frame(frm, style="Card.TFrame")
        btns.pack(side="bottom", fill="x", pady=(16, 0))
        far = "left" if rtl else "right"
        ttk.Button(btns, text=txt["about_close"], style="Accent.TButton",
                   command=self.destroy).pack(side=far)
        ttk.Button(btns, text=txt["copy_email"],
                   command=self._copy_email).pack(side=far, padx=8)

        box = ttk.Frame(frm, style="Card.TFrame")
        box.pack(side="top", fill="both", expand=True)
        # النص للقراءة والنسخ لا للتحرير؛ نبقيه state=normal كي تعمل
        # لوحة المفاتيح في النسخ، ونمنع الكتابة بحجب مفاتيح الإدخال
        self.txt = tk.Text(box, wrap="word", width=84, height=26,
                           relief="flat", padx=18, pady=16, spacing1=2, spacing3=4,
                           bg=C["surface"], fg=C["text"],
                           highlightthickness=0, borderwidth=0)
        if fonts:
            self.txt.configure(font=fonts)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        sb.pack(side=far, fill="y")
        self.txt.pack(side=near, fill="both", expand=True)

        self.txt.insert("1.0", body)
        # Tk لا يملك خوارزمية bidi، لكنه يحاذي الفقرات. المحاذاة إلى اليمين
        # هي ما نستطيع ضبطه، وتشكيل الحروف يتولاه نظام التشغيل.
        self.txt.tag_configure("dir", justify="right" if rtl else "left")
        self.txt.tag_add("dir", "1.0", "end")
        self.txt.bind("<Key>", self._readonly)

        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        # حجم أدنى يضمن بقاء الأزرار ظاهرة مهما صغّر المستخدم النافذة
        try:
            self.minsize(520, 360)
            w = max(640, min(920, self.winfo_reqwidth()))
            h = max(460, min(760, self.winfo_reqheight()))
            self.geometry("%dx%d+%d+%d" % (
                w, h, parent.winfo_rootx() + 70, parent.winfo_rooty() + 50))
        except Exception:
            pass

    def _readonly(self, ev):
        # نسمح بالتنقل والنسخ ونمنع التعديل
        if ev.state & 0x0008 or ev.state & 0x0004:      # Alt/Cmd أو Ctrl
            return None
        if ev.keysym in ("Up", "Down", "Left", "Right", "Prior", "Next",
                         "Home", "End", "Tab"):
            return None
        return "break"

    def _copy_email(self):
        try:
            self.clipboard_clear()
            self.clipboard_append(VENDOR_EMAIL)
            self._on_copy_msg()
        except Exception:
            pass


class BusyBox(tk.Toplevel):
    """نافذة صغيرة تحجب الواجهة أثناء تنفيذ أمر على الراوتر."""

    def __init__(self, parent, text):
        tk.Toplevel.__init__(self, parent)
        self.title("")
        self.resizable(False, False)
        self.transient(parent)
        self.configure(background=C["surface"])
        frm = ttk.Frame(self, padding=24, style="Card.TFrame")
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm, text=text, style="Card.TLabel").pack(pady=(0, 14))
        self.bar = ttk.Progressbar(frm, mode="indeterminate", length=260)
        self.bar.pack()
        self.bar.start(12)
        self.protocol("WM_DELETE_WINDOW", lambda: None)
        try:
            parent.update_idletasks()
            x = parent.winfo_rootx() + max(0, (parent.winfo_width() - 280) // 2)
            y = parent.winfo_rooty() + max(0, (parent.winfo_height() - 100) // 2)
            self.geometry("+%d+%d" % (x, y))
        except Exception:
            pass
        self.grab_set()

    def finish(self):
        try:
            self.bar.stop()
            self.grab_release()
            self.destroy()
        except Exception:
            pass


class UiRouter(object):
    """
    وسيط حول RouterSession.

    كل نداء إلى الراوتر ينفَّذ في خيط جانبي بينما تظل الحلقة الرسومية تعمل،
    وإلا تجمّدت النافذة وأظهر ويندوز "لا يستجيب" أثناء أمر save الذي قد
    يستغرق دقيقة. لا يلمس الخيط الجانبي أي عنصر واجهة — يتصل بالراوتر فقط
    ويعيد النتيجة، والواجهة محجوبة بنافذة انتظار طوال المدة.
    """

    def __init__(self, app, session):
        self._app = app
        self._s = session

    def __getattr__(self, name):
        value = getattr(self._s, name)
        if not callable(value):
            return value

        def wrapped(*a, **kw):
            return self._app.run_blocking(value, *a, **kw)

        return wrapped


class App(tk.Tk):

    def __init__(self):
        tk.Tk.__init__(self)
        self.settings = load_settings()
        self.lang = self.settings.get("ui_lang", "ar")
        self.T = TXT.get(self.lang, TXT["ar"])

        self.title("%s  v%s" % (self.T["title"], APP_VERSION))
        # المقاس يُحسب بعد البناء في _fit_window — الشريط العلوي هو الذي
        # يفرض أدنى عرض، وعدد حقوله يتغيّر بتغيّر اللغة والإصدار

        self.db = LocalDB()
        self.demo_mode = False
        self._busy = False
        # سجل الأوامر يُملأ من الخيط الجانبي، وTk لا تحتمل ذلك.
        # فنصفّ النص هنا ولا نكتبه في الويدجت إلا من الخيط الرئيسي.
        self._log_queue = []
        self._log_lock = threading.Lock()
        self.router = UiRouter(self, RouterSession(log_fn=self._log))
        self.router_users = {}
        self.router_groups = {}
        self.online_rows = []
        self._busy = False

        self._build_style()
        self._build_top()
        # الشريط السفلي يُرصف قبل التبويبات عمداً: pack يوزّع المساحة
        # بترتيب الرصف، ودفتر التبويبات ممتد (expand) فيبتلع كل ما تبقّى.
        # لو رُصف بعده لما بقي للشريط شيء ولاختفى حتى تُوسَّع النافذة يدوياً.
        self._build_status()
        self._build_tabs()

        self._fit_window()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._refresh_device_table()
        self._refresh_portal_table()

    # -- بناء الواجهة --------------------------------------------------------

    # -- اتجاه الواجهة --------------------------------------------------------

    def _side(self, primary=True):
        """جهة الرصف: primary تعني بداية السطر في لغة الواجهة."""
        if self.rtl:
            return "right" if primary else "left"
        return "left" if primary else "right"

    def _anchor(self, primary=True):
        if self.rtl:
            return "e" if primary else "w"
        return "w" if primary else "e"

    def _pad(self, before, after):
        """يقلب الحشو أفقياً في الواجهة العربية."""
        return (after, before) if self.rtl else (before, after)

    def _justify(self):
        return "right" if self.rtl else "left"

    def _build_style(self):
        self.rtl = (self.lang == "ar")

        fam = pick_font(self, FONTS_AR if self.rtl else FONTS_EN)
        mono = pick_font(self, FONTS_MONO, "Courier")
        size = 10 if sys.platform.startswith("win") else 12
        self.font_base = (fam, size)
        self.font_bold = (fam, size, "bold")
        self.font_h1 = (fam, size + 6, "bold")
        self.font_small = (fam, size - 1)
        self.font_mono = (mono, size - 1)
        self.option_add("*Font", self.font_base)

        self.configure(background=C["bg"])

        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except Exception:
            pass

        # -- الأساسيات
        st.configure(".", background=C["bg"], foreground=C["text"],
                     font=self.font_base, borderwidth=0, focuscolor=C["bg"])
        st.configure("TFrame", background=C["bg"])
        st.configure("Card.TFrame", background=C["surface"])
        st.configure("TLabel", background=C["bg"], foreground=C["text"])
        st.configure("Card.TLabel", background=C["surface"], foreground=C["text"])
        st.configure("TSeparator", background=C["border"])

        # -- الأزرار: مسطّحة بحواف داخلية مريحة
        st.configure("TButton", background=C["surface"], foreground=C["text"],
                     borderwidth=1, relief="flat", padding=(14, 7),
                     bordercolor=C["border"], lightcolor=C["surface"],
                     darkcolor=C["surface"])
        st.map("TButton",
               background=[("pressed", C["border"]), ("active", C["head_bg"])],
               bordercolor=[("active", C["accent"])])

        st.configure("Accent.TButton", background=C["accent"], foreground="#ffffff",
                     bordercolor=C["accent"], lightcolor=C["accent"],
                     darkcolor=C["accent"], padding=(16, 7))
        st.map("Accent.TButton",
               background=[("pressed", C["accent_hi"]), ("active", C["accent_hi"])],
               foreground=[("disabled", "#e8e8e8")])

        st.configure("Danger.TButton", foreground=C["danger"],
                     bordercolor=C["border"])
        st.map("Danger.TButton",
               background=[("active", "#fdeceb"), ("pressed", "#f8d9d7")],
               bordercolor=[("active", C["danger"])])

        # -- حقول الإدخال
        for name in ("TEntry", "TCombobox"):
            st.configure(name, fieldbackground=C["surface"], background=C["surface"],
                         foreground=C["text"], bordercolor=C["border"],
                         lightcolor=C["border"], darkcolor=C["border"],
                         insertcolor=C["text"], borderwidth=1,
                         padding=(8, 6), arrowcolor=C["muted"])
            st.map(name, bordercolor=[("focus", C["accent"])],
                   lightcolor=[("focus", C["accent"])],
                   darkcolor=[("focus", C["accent"])])

        st.configure("TCheckbutton", background=C["bg"], foreground=C["text"],
                     indicatorcolor=C["surface"], bordercolor=C["border"],
                     focuscolor=C["bg"])
        st.map("TCheckbutton",
               indicatorcolor=[("selected", C["accent"])],
               background=[("active", C["bg"])])

        # -- الجداول: صفوف مريحة، بلا إطارات، وتحديد بلون العلامة
        st.configure("Treeview", background=C["surface"], fieldbackground=C["surface"],
                     foreground=C["text"], rowheight=32, borderwidth=0, relief="flat")
        st.map("Treeview",
               background=[("selected", C["sel"])],
               foreground=[("selected", C["text"])])
        st.configure("Treeview.Heading", background=C["head_bg"],
                     foreground=C["muted"], font=(fam, size - 1, "bold"),
                     relief="flat", borderwidth=0, padding=(10, 9))
        st.map("Treeview.Heading", background=[("active", C["border"])])

        # -- التبويبات
        st.configure("TNotebook", background=C["bg"], borderwidth=0,
                     tabmargins=(0, 4, 0, 0))
        st.configure("TNotebook.Tab", background=C["bg"], foreground=C["muted"],
                     padding=(18, 10), borderwidth=0, font=self.font_base)
        st.map("TNotebook.Tab",
               background=[("selected", C["surface"])],
               foreground=[("selected", C["accent"]), ("active", C["text"])],
               font=[("selected", (fam, size, "bold"))])

        st.configure("TScrollbar", background=C["bg"], troughcolor=C["bg"],
                     bordercolor=C["bg"], arrowcolor=C["muted"],
                     lightcolor=C["bg"], darkcolor=C["bg"])

        st.configure("TProgressbar", background=C["accent"], troughcolor=C["border"],
                     bordercolor=C["border"], lightcolor=C["accent"],
                     darkcolor=C["accent"])

        # -- تسميات الحالة
        st.configure("Ok.TLabel", foreground=C["ok"], background=C["bg"])
        st.configure("Off.TLabel", foreground=C["danger"], background=C["bg"])
        st.configure("Demo.TLabel", foreground=C["warn"], background=C["bg"])
        st.configure("Brand.TLabel", foreground=C["muted"], background=C["bg"],
                     font=self.font_small)
        st.configure("Muted.TLabel", foreground=C["muted"], background=C["bg"],
                     font=self.font_small)
        st.configure("Warn.TLabel", foreground=C["warn"], background=C["bg"],
                     font=self.font_small)
        st.configure("H1.TLabel", font=self.font_h1, background=C["surface"])

    def _build_top(self):
        top = ttk.Frame(self, padding=(16, 14))
        top.pack(fill="x")
        self.top_bar = top

        self.v_host = tk.StringVar(value=self.settings["host"])
        # يبقى فارغاً ما دام المنفذ هو 22، كي لا يزحم الشريط بقيمة بديهية
        saved_port = self.settings.get("port", DEFAULT_SSH_PORT)
        self.v_port = tk.StringVar(
            value="" if int(saved_port or DEFAULT_SSH_PORT) == DEFAULT_SSH_PORT
            else str(saved_port))
        self.v_user = tk.StringVar(value=self.settings["username"])
        self.v_pass = tk.StringVar(value="")

        ent = {"justify": self._justify()}

        e_pass = ttk.Entry(top, textvariable=self.v_pass, width=16, show="•", **ent)
        e_pass.bind("<Return>", lambda ev: self.on_connect())
        # نص الزر ونص الحالة يطولان عند الاتصال. لو تُركا يتمدّدان لزاد
        # عرض الشريط المطلوب بعد أن حُسب مقاس النافذة على النص القصير،
        # فتُدفع الحقول خارج الحدود. نحجز لهما أوسع نص ممكن من البداية.
        self.btn_conn = ttk.Button(
            top, text=self.T["connect"], style="Accent.TButton",
            width=max(len(self.T["connect"]), len(self.T["disconnect"])) + 2,
            command=self.on_connect)

        self._state_chars = max(
            len("● " + self.T["status_off"]),
            len("● " + self.T["status_on"]) + 2 + HOSTNAME_ROOM,
            len(DEMO_STATE_TEXT),
        )
        self.lbl_state = ttk.Label(top, text="● " + self.T["status_off"],
                                   style="Off.TLabel", width=self._state_chars,
                                   anchor=self._anchor())

        # الترتيب المنطقي؛ يُعكس بصرياً في العربية دون تغيير المعنى.
        # الرقم الأخير هو المجموعة: عند ضيق النافذة تنزل المجموعة ١ سطراً.
        self._top_cells = [
            (ttk.Label(top, text=self.T["host"]), (0, 8), 0),
            (ttk.Entry(top, textvariable=self.v_host, width=15, **ent), (0, 18), 0),
            (ttk.Label(top, text=self.T["port"]), (0, 8), 0),
            (ttk.Entry(top, textvariable=self.v_port, width=6, **ent), (0, 6), 0),
            (ttk.Label(top, text=self.T["port_hint"], style="Muted.TLabel"), (0, 18), 0),
            (ttk.Label(top, text=self.T["user"]), (0, 8), 1),
            (ttk.Entry(top, textvariable=self.v_user, width=12, **ent), (0, 18), 1),
            (ttk.Label(top, text=self.T["password"]), (0, 8), 1),
            (e_pass, (0, 18), 1),
            (self.btn_conn, (0, 12), 1),
            (self.lbl_state, (0, 0), 1),
        ]

        # نقيس ما يحتاجه الشريط في الوضعين مرة واحدة، ثم نبدأ بسطر واحد
        self._top_rows = None
        self._layout_top(2)
        self._top_w2 = self._measure_top()
        self._layout_top(1)
        self._top_w1 = self._measure_top()

        self.bind("<Configure>", self._on_window_resize, add="+")

    def _measure_top(self):
        try:
            self.update_idletasks()
            return self.top_bar.winfo_reqwidth()
        except Exception:
            return 0

    def _layout_top(self, rows):
        """
        يرصف شريط الاتصال في سطر واحد أو سطرين.
        بلا هذا كان الشريط يُقصّ كلما ضاقت النافذة عن مجموع حقوله — وهو
        ما يحدث حتماً على الشاشات الصغيرة مهما ضبطنا عرض الفتح.
        """
        if self._top_rows == rows:
            return
        self._top_rows = rows

        for w, _, _ in self._top_cells:
            w.grid_forget()

        if rows == 1:
            lines = [self._top_cells]
        else:
            lines = [[c for c in self._top_cells if c[2] == 0],
                     [c for c in self._top_cells if c[2] == 1]]

        # العمود المطاطي يدفع الصف إلى جهة القراءة: صفر في العربية،
        # وعمود بعيد فارغ في الإنجليزية كي يصلح لأي عدد خلايا
        spacer = 0 if self.rtl else 99
        self.top_bar.columnconfigure(spacer, weight=1)

        for r, line in enumerate(lines):
            n = len(line)
            for i, (w, pad, _) in enumerate(line):
                col = (n - i) if self.rtl else i
                w.grid(row=r, column=col, sticky=self._anchor(False),
                       padx=self._pad(*pad),
                       pady=(0, 0) if rows == 1 else (2, 2))

    def _on_window_resize(self, ev):
        if getattr(ev, "widget", None) is not self:
            return
        need = getattr(self, "_top_w1", 0)
        if not need:
            return
        # هامش صغير يمنع التذبذب عند الحافة تماماً
        self._layout_top(1 if ev.width >= need + 8 else 2)

    def _build_tabs(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        builders = [self._tab_devices, self._tab_portal, self._tab_online,
                    self._tab_groups, self._tab_settings, self._tab_log]
        # Tk يرصف التبويبات من اليسار دائماً. فلنبنِها بالعكس في العربية
        # كي يقع التبويب الأول في أقصى اليمين حيث تبدأ القراءة.
        if self.rtl:
            builders = list(reversed(builders))
        for b in builders:
            b()
        # التبويب الأول منطقياً هو الأجهزة الموثوقة مهما كان ترتيب البناء
        try:
            self.nb.select(self._first_tab)
        except Exception:
            pass

    # ---- تبويب الأجهزة الموثوقة -------------------------------------------

    def _make_tree(self, parent, cols, heads, widths, height=None):
        """
        جدول بمظهر موحّد. في العربية نعكس ترتيب العرض عبر displaycolumns
        لا عبر قلب الأعمدة نفسها — فتبقى قيم الصفوف على ترتيبها المنطقي
        ولا يحتاج أي نداء insert إلى تغيير.
        """
        wrap = ttk.Frame(parent, style="Card.TFrame")
        wrap.pack(fill="both", expand=True)

        kw = {"columns": cols, "show": "headings", "selectmode": "browse"}
        if height:
            kw["height"] = height
        tv = ttk.Treeview(wrap, **kw)
        anchor = self._anchor()
        for c, h, w in zip(cols, heads, widths):
            tv.heading(c, text=h, anchor=anchor)
            tv.column(c, width=w, anchor=anchor, stretch=True)
        if self.rtl:
            tv.configure(displaycolumns=tuple(reversed(cols)))

        sb = ttk.Scrollbar(wrap, orient="vertical", command=tv.yview)
        tv.configure(yscroll=sb.set)
        sb.pack(side=self._side(False), fill="y")
        tv.pack(side=self._side(), fill="both", expand=True)

        tv.tag_configure("revoked", foreground=C["muted"])
        tv.tag_configure("orphan", foreground=C["warn"])
        tv.tag_configure("missing", foreground=C["danger"])
        return tv

    def _wrap(self, label, holder=None, margin=56, minimum=220):
        """
        ttk.Label لا يلتف من تلقائه: يبقى سطراً واحداً يُقتطع عند تصغير
        النافذة، ولا يعيد الانسياب عند تكبيرها. فنربط wraplength بعرض
        الحاوية الفعلي عند كل تغيّر حجم.
        """
        box = holder if holder is not None else label.master

        def on_configure(ev):
            width = max(minimum, ev.width - margin)
            try:
                if label.cget("wraplength") != width:
                    label.configure(wraplength=width)
            except Exception:
                pass

        box.bind("<Configure>", on_configure, add="+")
        # عرض ابتدائي معقول قبل أول حدث تغيير حجم
        try:
            label.configure(wraplength=minimum * 3)
        except Exception:
            pass
        return label

    def _search_bar(self, parent, var, on_change):
        """صف بحث موحّد فوق الجدول: حقل + زر مسح + عدّاد النتائج."""
        row = ttk.Frame(parent, style="Card.TFrame")
        row.pack(fill="x", pady=(0, 10))
        p = self._side()
        q = self._side(False)

        ttk.Label(row, text=self.T["search"], style="Card.TLabel").pack(
            side=p, padx=self._pad(0, 8))
        ent = ttk.Entry(row, textvariable=var, width=34, justify=self._justify())
        ent.pack(side=p)
        ent.bind("<Escape>", lambda e: var.set(""))
        ttk.Button(row, text=self.T["search_clear"],
                   command=lambda: var.set("")).pack(side=p, padx=self._pad(8, 0))

        count = ttk.Label(row, text="", style="Muted.TLabel", background=C["surface"])
        count.pack(side=q)

        var.trace_add("write", lambda *a: on_change())
        return count

    def _apply_count(self, label, shown, total):
        try:
            label.configure(text=self.T["shown_of"] % {"shown": shown, "total": total}
                            if shown != total else "")
        except Exception:
            pass

    def _tab_frame(self, title):
        f = ttk.Frame(self.nb, padding=16, style="Card.TFrame")
        self.nb.add(f, text="  %s  " % title)
        return f

    def _tab_devices(self):
        f = self._tab_frame(self.T["tab_devices"])
        self._first_tab = f

        bar = ttk.Frame(f, style="Card.TFrame")
        bar.pack(fill="x", pady=(0, 12))
        p = self._side()
        q = self._side(False)
        ttk.Button(bar, text=self.T["add_device"], style="Accent.TButton",
                   command=self.on_add_device).pack(side=p)
        ttk.Button(bar, text=self.T["change_group"],
                   command=self.on_change_device_group).pack(side=p, padx=6)
        ttk.Button(bar, text=self.T["edit_meta"],
                   command=self.on_edit_device_meta).pack(side=p)
        ttk.Button(bar, text=self.T["revoke_device"], command=self.on_revoke_device,
                   style="Danger.TButton").pack(side=p, padx=6)
        ttk.Button(bar, text=self.T["refresh"], command=self.on_refresh_all).pack(side=q)
        ttk.Button(bar, text=self.T["export"],
                   command=lambda: self.on_export("devices")).pack(side=q, padx=6)

        self.v_find_dev = tk.StringVar(value="")
        self.lbl_count_dev = self._search_bar(f, self.v_find_dev,
                                              self._refresh_device_table)

        self.tv_dev = self._make_tree(
            f, ("mac", "name", "group", "state", "added", "note"),
            [self.T["col_mac"], self.T["col_name"], self.T["col_group"],
             self.T["col_state"], self.T["col_added"], self.T["col_note"]],
            [160, 220, 140, 150, 130, 200])
        self.tv_dev.bind("<Double-1>", lambda e: self.on_edit_device_meta())

    # ---- تبويب حسابات البوابة ---------------------------------------------

    def _tab_portal(self):
        f = self._tab_frame(self.T["tab_portal"])

        bar = ttk.Frame(f, style="Card.TFrame")
        bar.pack(fill="x", pady=(0, 12))
        p = self._side()
        q = self._side(False)
        ttk.Button(bar, text=self.T["add_user"], style="Accent.TButton",
                   command=self.on_add_portal).pack(side=p)
        ttk.Button(bar, text=self.T["reset_pw"],
                   command=self.on_reset_portal_pw).pack(side=p, padx=6)
        ttk.Button(bar, text=self.T["change_group"],
                   command=self.on_change_portal_group).pack(side=p)
        ttk.Button(bar, text=self.T["edit_meta"],
                   command=self.on_edit_portal_meta).pack(side=p, padx=6)
        ttk.Button(bar, text=self.T["del_user"], command=self.on_del_portal,
                   style="Danger.TButton").pack(side=p)
        ttk.Button(bar, text=self.T["refresh"], command=self.on_refresh_all).pack(side=q)
        ttk.Button(bar, text=self.T["export"],
                   command=lambda: self.on_export("portal")).pack(side=q, padx=6)

        self.v_find_por = tk.StringVar(value="")
        self.lbl_count_por = self._search_bar(f, self.v_find_por,
                                              self._refresh_portal_table)

        self.tv_por = self._make_tree(
            f, ("user", "name", "group", "state", "added", "note"),
            [self.T["col_user"], self.T["col_name"], self.T["col_group"],
             self.T["col_state"], self.T["col_added"], self.T["col_note"]],
            [180, 220, 140, 150, 130, 200])
        self.tv_por.bind("<Double-1>", lambda e: self.on_edit_portal_meta())

    # ---- تبويب المتصلين ----------------------------------------------------

    def _tab_online(self):
        f = self._tab_frame(self.T["tab_online"])

        bar = ttk.Frame(f, style="Card.TFrame")
        bar.pack(fill="x", pady=(0, 12))
        p = self._side()
        ttk.Button(bar, text=self.T["refresh"], style="Accent.TButton",
                   command=self.on_refresh_online).pack(side=p)
        ttk.Button(bar, text=self.T["add_device"],
                   command=self.on_trust_online).pack(side=p, padx=6)
        ttk.Button(bar, text=self.T["cut_user"], command=self.on_cut_user,
                   style="Danger.TButton").pack(side=p)

        self.v_find_on = tk.StringVar(value="")
        self.lbl_count_on = self._search_bar(f, self.v_find_on,
                                             self._refresh_online_table)

        self.tv_on = self._make_tree(
            f, ("id", "user", "ip", "mac", "status", "name"),
            [self.T["col_id"], self.T["col_user"], self.T["col_ip"],
             self.T["col_mac"], self.T["col_status"], self.T["col_name"]],
            [70, 200, 130, 150, 130, 220])
        self.tv_on.tag_configure("ok", foreground=C["ok"])
        self.tv_on.tag_configure("pre", foreground=C["warn"])

    # ---- تبويب المجموعات ---------------------------------------------------

    def _tab_groups(self):
        f = self._tab_frame(self.T["tab_groups"])

        lbl_hint = ttk.Label(f, text=self.T["groups_hint"], style="Card.TLabel",
                             justify=self._justify())
        lbl_hint.pack(anchor=self._anchor(), fill="x", pady=(0, 10))
        self._wrap(lbl_hint, f)
        ttk.Button(f, text=self.T["refresh"], style="Accent.TButton",
                   command=self.on_refresh_all).pack(anchor=self._anchor(), pady=(0, 12))

        self.tv_grp = self._make_tree(
            f, ("group", "acl", "count"),
            [self.T["col_group"], self.T["col_acl"], self.T["col_members"]],
            [220, 140, 140], height=10)

    # ---- تبويب الإعدادات ---------------------------------------------------

    def _tab_settings(self):
        f = self._tab_frame(self.T["tab_settings"])

        self.v_macpw = tk.StringVar(value=self.settings["mac_shared_password"])
        self.v_autosave = tk.BooleanVar(value=self.settings.get("auto_save_config", True))
        self.v_lang = tk.StringVar(value=self.settings.get("ui_lang", "ar"))

        # عمود التسمية وعمود الحقل يتبادلان موضعيهما حسب اتجاه الواجهة
        c_lab, c_fld = (1, 0) if self.rtl else (0, 1)
        s_lab, s_fld = self._anchor(False), self._anchor()

        def label(row, text, style="Card.TLabel", **kw):
            ttk.Label(f, text=text, style=style, justify=self._justify(),
                      **kw).grid(row=row, column=c_lab, sticky=s_lab,
                                 padx=self._pad(0, 12), pady=8)

        def hint(row, text, style="Warn.TLabel"):
            lbl = ttk.Label(f, text=text, style=style, justify=self._justify())
            lbl.grid(row=row, column=c_fld, sticky="ew", pady=(0, 14))
            self._wrap(lbl, f)

        label(0, self.T["mac_pw_label"])
        ttk.Entry(f, textvariable=self.v_macpw, width=32,
                  justify=self._justify()).grid(row=0, column=c_fld, sticky=s_fld)
        hint(1, self.T["mac_pw_hint"])

        ttk.Checkbutton(f, text=self.T["autosave"], variable=self.v_autosave).grid(
            row=2, column=c_fld, sticky=s_fld, pady=8)

        label(3, self.T["lang_label"])
        ttk.Combobox(f, textvariable=self.v_lang, values=["ar", "en"], width=8,
                     state="readonly", justify=self._justify()).grid(
            row=3, column=c_fld, sticky=s_fld)
        hint(4, self.T["lang_note"])

        ttk.Button(f, text=self.T["save_settings"], style="Accent.TButton",
                   command=self.on_save_settings).grid(
            row=5, column=c_fld, sticky=s_fld, pady=14)

        ttk.Separator(f, orient="horizontal").grid(
            row=6, column=0, columnspan=2, sticky="ew", pady=(22, 14))
        lbl_sync = ttk.Label(f, text=self.T["sync_note"], style="Muted.TLabel",
                             justify=self._justify())
        lbl_sync.grid(row=7, column=0, columnspan=2, sticky="ew")
        self._wrap(lbl_sync, f)

        lbl_file = ttk.Label(f, text="%s  %s" % (self.T["data_file"], DB_FILE),
                             style="Muted.TLabel", justify=self._justify())
        lbl_file.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self._wrap(lbl_file, f)

        # عمود الحقول هو الذي يتمدد، فينساب النص فيه بدل أن يبقى مكدّساً
        f.columnconfigure(c_fld, weight=1)

    # ---- تبويب السجل -------------------------------------------------------

    def _tab_log(self):
        f = self._tab_frame(self.T["tab_log"])
        # مخرجات الراوتر إنجليزية ومحاذاة أعمدتها معتمدة على المسافات،
        # فتبقى يساراً بخط ثابت العرض مهما كانت لغة الواجهة
        self.txt_log = tk.Text(f, wrap="none", height=20, relief="flat",
                               bg=C["console"], fg=C["console_fg"],
                               insertbackground=C["console_fg"],
                               font=self.font_mono, padx=12, pady=10)
        sb = ttk.Scrollbar(f, orient="vertical", command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.txt_log.pack(side="left", fill="both", expand=True)

    def _fit_window(self):
        """
        يفتح النافذة بعرض يسع شريط الاتصال كاملاً.
        كان العرض ثابتاً (1080) فكان أي حقل يُضاف إلى الشريط يدفع
        عنوان الراوتر خارج الحدود — والشبكة تقصّ ما تجاوز عرضها،
        فيضطر المستخدم إلى توسيع النافذة يدوياً عند كل فتح.
        """
        MARGIN = 40          # حشو الإطار + إطار النافذة نفسها
        PREFERRED = (1120, 700)
        FLOOR = (860, 560)

        # نفتح على سطر واحد إن أمكن، والحد الأدنى هو ما يحتاجه السطران —
        # فأضيق نافذة ممكنة ما زالت تُظهر كل الحقول بلا قصّ
        want = getattr(self, "_top_w1", 0) + MARGIN
        floor_w = max(FLOOR[0], getattr(self, "_top_w2", 0) + MARGIN)

        try:
            screen_w = self.winfo_screenwidth()
            screen_h = self.winfo_screenheight()
        except Exception:
            screen_w, screen_h = PREFERRED

        usable = max(320, screen_w - 60)
        min_w = min(floor_w, max(320, screen_w - 40))
        w = min(max(PREFERRED[0], want, min_w), usable)
        h = min(PREFERRED[1], max(400, screen_h - 120))

        try:
            # نفتحها في وسط الشاشة كي لا تخرج أطرافها خارجها
            x = max(0, (screen_w - w) // 2)
            y = max(0, (screen_h - h) // 3)
            self.geometry("%dx%d+%d+%d" % (w, h, x, y))
            # الحد الأدنى يمنع قصّ الشريط حتى لو صغّرها المستخدم بنفسه
            self.minsize(min_w, min(FLOOR[1], h))
        except Exception:
            pass

    def _build_status(self):
        bar = ttk.Frame(self)
        bar.pack(fill="x", side="bottom")

        ttk.Separator(bar, orient="horizontal").pack(fill="x")
        row = ttk.Frame(bar)
        row.pack(fill="x")

        self.lbl_status = ttk.Label(row, text="", anchor=self._anchor(),
                                    padding=(16, 8))
        self.lbl_status.pack(side=self._side(), fill="x", expand=True)

        self.lbl_brand = ttk.Label(row, text="Powered by %s" % VENDOR,
                                   style="Brand.TLabel", padding=(14, 8), cursor="hand2")
        self.lbl_brand.pack(side=self._side(False))
        self.lbl_brand.bind("<Button-1>", lambda e: self.on_about())
        # التوقيع لا يبدو قابلاً للنقر من تلقائه، فنُظهر ذلك عند مرور المؤشر
        self.lbl_brand.bind("<Enter>", lambda e: self._brand_hover(True))
        self.lbl_brand.bind("<Leave>", lambda e: self._brand_hover(False))

    def _brand_hover(self, on):
        try:
            self.lbl_brand.configure(
                text=("Powered by %s  —  %s" % (VENDOR, self.T["about_hint"]))
                if on else "Powered by %s" % VENDOR)
        except Exception:
            pass

    def on_about(self):
        AboutDialog(self, self.T, ABOUT.get(self.lang, ABOUT["ar"]),
                    lambda: self._status(self.T["email_copied"]),
                    rtl=self.rtl, fonts=self.font_base)

    # -- أدوات مساعدة للواجهة ------------------------------------------------

    # -- تنفيذ بلا تجميد للواجهة ---------------------------------------------

    def run_blocking(self, fn, *a, **kw):
        """
        ينفّذ نداء الراوتر في خيط جانبي ويستمر في تحريك الحلقة الرسومية،
        فتبقى النافذة حيّة وتظهر شريط انتظار بدل أن يعلّقها ويندوز.
        الخيط لا يلمس أي عنصر واجهة، والواجهة محجوبة بنافذة الانتظار.
        """
        if self._busy:
            # لا نسمح بنداءين متزامنين على القناة نفسها
            raise RouterError("عملية أخرى قيد التنفيذ / another operation is running")

        self._busy = True
        try:
            box = BusyBox(self, self.T["busy"])
        except Exception:
            box = None

        result = {}

        def worker():
            try:
                result["value"] = fn(*a, **kw)
            except Exception as exc:
                result["error"] = exc

        t = threading.Thread(target=worker)
        t.daemon = True
        t.start()
        try:
            while t.is_alive():
                try:
                    self._drain_log()
                    self.update()
                except Exception:
                    break
                time.sleep(0.03)
            t.join(1.0)
            try:
                self._drain_log()
            except Exception:
                pass
        finally:
            self._busy = False
            if box is not None:
                box.finish()

        if "error" in result:
            raise result["error"]
        return result.get("value")

    def _log(self, text):
        """
        يُنادى من الخيط الجانبي أثناء نداءات الراوتر، فلا يلمس Tk إطلاقاً.
        الكتابة في الملف آمنة من أي خيط؛ نص الواجهة يُصفّ ويُفرَّغ لاحقاً
        من الخيط الرئيسي عبر _drain_log.
        """
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(text)
        except Exception:
            pass
        with self._log_lock:
            self._log_queue.append(text)
        if threading.current_thread() is threading.main_thread():
            self._drain_log()

    def _drain_log(self):
        """يُنادى من الخيط الرئيسي وحده."""
        with self._log_lock:
            pending = self._log_queue
            self._log_queue = []
        if not pending:
            return
        try:
            self.txt_log.insert("end", "".join(pending))
            self.txt_log.see("end")
        except Exception:
            # الويدجت لم يُبنَ بعد — نعيد النص إلى الطابور كي لا يضيع
            with self._log_lock:
                self._log_queue[:0] = pending

    def _status(self, msg, ok=True):
        self.lbl_status.configure(text=msg, foreground="#16704a" if ok else "#a3301c")
        self.update_idletasks()

    def _set_state(self, text, style):
        """يضبط تسمية الحالة ويختصر ما تجاوز العرض المحجوز."""
        limit = getattr(self, "_state_chars", 24)
        if len(text) > limit:
            text = text[:limit - 1] + "…"
        self.lbl_state.configure(text=text, style=style)

    def _need_conn(self):
        if not self.router.connected:
            messagebox.showwarning(APP_NAME, self.T["err_no_conn"])
            return False
        return True

    def _groups_list(self):
        gl = sorted(self.router_groups.keys()) if self.router_groups else []
        for g in self.settings.get("known_groups", []):
            if g not in gl:
                gl.append(g)
        return gl

    # -- الاتصال -------------------------------------------------------------

    def on_connect(self):
        if self.router.connected:
            self.router.close()
            self._set_state("● " + self.T["status_off"], "Off.TLabel")
            self.btn_conn.configure(text=self.T["connect"])
            self._status("")
            return

        host = self.v_host.get().strip()
        user = self.v_user.get().strip()
        pw = self.v_pass.get()
        if not host or not user or not pw:
            messagebox.showwarning(APP_NAME, "أكمل بيانات الاتصال / Fill in the connection fields")
            return

        # الحقل الفارغ يعني المنفذ القياسي؛ وأي شيء آخر يجب أن يكون رقماً
        # صالحاً وإلا انفجر int() لاحقاً برسالة لا يفهمها المستخدم
        port_raw = self.v_port.get().strip()
        if port_raw:
            if not port_raw.isdigit() or not (1 <= int(port_raw) <= 65535):
                messagebox.showerror(APP_NAME, self.T["err_bad_port"])
                return
        port = int(port_raw or DEFAULT_SSH_PORT)

        self._status(self.T["connecting"])
        try:
            self.router.connect(host, port, user, pw)
        except Exception as e:
            self._status("فشل الاتصال / Connection failed: %s" % e, ok=False)
            messagebox.showerror(APP_NAME, "فشل الاتصال:\n%s" % e)
            return

        self.settings["host"] = host
        self.settings["username"] = user
        self.settings["port"] = port
        save_settings(self.settings)

        self._set_state("● " + self.T["status_on"] + "  " + self.router.hostname,
                        "Ok.TLabel")
        self.btn_conn.configure(text=self.T["disconnect"])
        self.v_pass.set("")
        self.on_refresh_all()

    # -- القراءة والتحديث ----------------------------------------------------

    def on_refresh_all(self):
        if not self._need_conn():
            return
        self._status(self.T["working"])
        try:
            aaa = self.router.read_aaa()
            self.router_users = parse_local_users(aaa)
            groups_out = self.router.read_groups()
            acl_out = self.router.read_group_acls()
            self.router_groups = parse_groups(groups_out, acl_out)
        except Exception as e:
            self._status("خطأ في القراءة / Read error: %s" % e, ok=False)
            return

        self._refresh_device_table()
        self._refresh_portal_table()
        self._refresh_groups_table()
        self.on_refresh_online()
        self._status("تم التحديث من الراوتر / Refreshed from router")

    def _refresh_device_table(self):
        for i in self.tv_dev.get_children():
            self.tv_dev.delete(i)

        q = self.v_find_dev.get() if hasattr(self, "v_find_dev") else ""
        shown = total = 0

        macs, _, _ = split_user_kinds(self.router_users) if self.router_users else ({}, {}, {})
        seen = set()

        for mac12, rec in sorted(macs.items()):
            local = self.db.device(mac12) or {}
            seen.add(mac12)
            group = rec.get("group") or ""
            state = self.T["state_active"]
            tag = ""
            if not local:
                state = self.T["state_orphan"]
                tag = "orphan"
            if not group:
                state = state + " ⚠"
                tag = "orphan"
            vals = (mac_pretty(mac12), local.get("name", ""), group, state,
                    local.get("added", ""), local.get("note", ""))
            total += 1
            if not row_matches(q, vals, mac12):
                continue
            shown += 1
            self.tv_dev.insert("", "end", iid=mac12, values=vals, tags=(tag,))

        for mac12, local in sorted(self.db.data["devices"].items()):
            if mac12 in seen:
                continue
            if local.get("state") == "revoked":
                st, tag = self.T["state_revoked"], "revoked"
                # سبب الإلغاء والملاحظة كلاهما مفيد — نعرضهما معاً بدل
                # إخفاء أحدهما، وإلا اختفت ملاحظة عُدّلت بعد الإلغاء
                note = " — ".join([x for x in (local.get("revoke_reason", ""),
                                               local.get("note", "")) if x])
            else:
                st, tag = self.T["state_missing"], "missing"
                note = local.get("note", "")
            vals = (mac_pretty(mac12), local.get("name", ""), local.get("group", ""),
                    st, local.get("added", ""), note)
            total += 1
            if not row_matches(q, vals, mac12):
                continue
            shown += 1
            self.tv_dev.insert("", "end", iid=mac12, values=vals, tags=(tag,))

        self._apply_count(getattr(self, "lbl_count_dev", None), shown, total)

    def _refresh_portal_table(self):
        for i in self.tv_por.get_children():
            self.tv_por.delete(i)

        q = self.v_find_por.get() if hasattr(self, "v_find_por") else ""
        shown = total = 0

        _, portals, _ = split_user_kinds(self.router_users) if self.router_users else ({}, {}, {})
        seen = set()

        for name, rec in sorted(portals.items()):
            local = self.db.portal(name) or {}
            seen.add(name)
            group = rec.get("group") or ""
            state = self.T["state_active"]
            tag = ""
            if not local:
                state = self.T["state_orphan"]
                tag = "orphan"
            if not group:
                state = state + " ⚠"
                tag = "orphan"
            vals = (name, local.get("name", ""), group, state,
                    local.get("added", ""), local.get("note", ""))
            total += 1
            if not row_matches(q, vals):
                continue
            shown += 1
            self.tv_por.insert("", "end", iid=name, values=vals, tags=(tag,))

        for name, local in sorted(self.db.data["portal"].items()):
            if name in seen:
                continue
            if local.get("state") == "revoked":
                st, tag = self.T["state_revoked"], "revoked"
                # سبب الإلغاء والملاحظة كلاهما مفيد — نعرضهما معاً بدل
                # إخفاء أحدهما، وإلا اختفت ملاحظة عُدّلت بعد الإلغاء
                note = " — ".join([x for x in (local.get("revoke_reason", ""),
                                               local.get("note", "")) if x])
            else:
                st, tag = self.T["state_missing"], "missing"
                note = local.get("note", "")
            vals = (name, local.get("name", ""), local.get("group", ""),
                    st, local.get("added", ""), note)
            total += 1
            if not row_matches(q, vals):
                continue
            shown += 1
            self.tv_por.insert("", "end", iid=name, values=vals, tags=(tag,))

        self._apply_count(getattr(self, "lbl_count_por", None), shown, total)

    def _refresh_groups_table(self):
        for i in self.tv_grp.get_children():
            self.tv_grp.delete(i)
        counts = {}
        for _, rec in self.router_users.items():
            g = rec.get("group")
            if g:
                counts[g] = counts.get(g, 0) + 1
        for g in sorted(set(list(self.router_groups.keys()) + list(counts.keys()))):
            acl = self.router_groups.get(g) or "—"
            self.tv_grp.insert("", "end", values=(g, acl, counts.get(g, 0)))

    def on_refresh_online(self):
        if not self.router.connected:
            return
        try:
            out = self.router.read_online()
        except Exception as e:
            self._status("خطأ / Error: %s" % e, ok=False)
            return
        self.online_rows = parse_online(out)
        self._refresh_online_table()

    def _refresh_online_table(self):
        """
        يبني الجدول من self.online_rows وحدها. البحث يستدعيها مباشرة،
        فلا يُستعلم الراوتر من جديد عند كل حرف يُكتب.
        """
        for i in self.tv_on.get_children():
            self.tv_on.delete(i)

        q = self.v_find_on.get() if hasattr(self, "v_find_on") else ""
        shown = total = 0

        for r in self.online_rows:
            mac12 = normalize_mac(r["mac"]) if r["mac"] else None
            local = self.db.device(mac12) if mac12 else None
            desc = (local or {}).get("name", "")
            if not desc:
                pr = self.db.portal(r["user"])
                desc = (pr or {}).get("name", "")
            tag = "ok" if r["status"].startswith("Success") else "pre"
            vals = (r["id"], r["user"], r["ip"], r["mac"], r["status"], desc)
            total += 1
            if not row_matches(q, vals, mac12):
                continue
            shown += 1
            self.tv_on.insert("", "end", values=vals, tags=(tag,))

        self._apply_count(getattr(self, "lbl_count_on", None), shown, total)

    # -- عمليات الأجهزة ------------------------------------------------------

    def on_add_device(self, preset_mac=""):
        if not self._need_conn():
            return
        dlg = FieldDialog(self, self.T["add_device"], [
            {"key": "mac", "label": self.T["ask_mac"], "default": preset_mac},
            {"key": "name", "label": self.T["ask_name"]},
            {"key": "group", "label": self.T["ask_group"], "kind": "combo",
             "values": self._groups_list(),
             "default": self.settings.get("default_mac_group", "grp_staff")},
            {"key": "note", "label": self.T["ask_note"]},
        ])
        if not dlg.result:
            return

        mac12 = normalize_mac(dlg.result["mac"])
        if not mac12:
            messagebox.showerror(APP_NAME, self.T["err_bad_mac"])
            return
        if mac12 in self.router_users:
            messagebox.showerror(APP_NAME, self.T["err_dup"])
            return
        group = dlg.result["group"].strip()
        if not group:
            messagebox.showwarning(APP_NAME, self.T["warn_no_group"])
            return

        pw = self.v_macpw.get().strip() or self.settings["mac_shared_password"]
        if pw.lower() == mac12:
            messagebox.showerror(
                APP_NAME,
                "كلمة مرور حسابات الماك لا يجوز أن تساوي عنوان الماك.\n"
                "غيّرها من تبويب الإعدادات ومن mac-access-profile على الراوتر.")
            return

        self._status(self.T["working"])
        try:
            # الترتيب إجباري: النوع ← كلمة المرور ← المجموعة
            self.router.send_many([
                "system-view",
                "aaa",
                "local-user %s service-type 8021x" % mac12,
                "local-user %s password cipher %s" % (mac12, pw),
                "local-user %s user-group %s" % (mac12, group),
                "quit",
                "quit",
            ])
            ok = self._verify_user(mac12, expect_group=group, expect_type="8021x")
            if not ok:
                self._status("لم يثبت الحساب على الراوتر / Not confirmed on router", ok=False)
                messagebox.showerror(APP_NAME,
                                     "نُفّذت الأوامر لكن الحساب لم يظهر في إعداد الراوتر.\n"
                                     "راجع تبويب سجل الأوامر.")
                return
            self._maybe_save()
        except Exception as e:
            self._status("خطأ / Error: %s" % e, ok=False)
            messagebox.showerror(APP_NAME, str(e))
            return

        self.db.upsert_device(mac12, dlg.result["name"], group, dlg.result["note"])
        self.db.log("add_device", mac12, "%s / %s" % (dlg.result["name"], group))
        self._refresh_device_table()
        self._status(self.T["ok_added"])

    def on_revoke_device(self):
        if not self._need_conn():
            return
        sel = self.tv_dev.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, self.T["no_selection"])
            return
        mac12 = sel[0]
        if not messagebox.askyesno(APP_NAME, self.T["confirm_revoke"] + "\n\n" + mac_pretty(mac12)):
            return
        reason = simpledialog.askstring(APP_NAME, self.T["ask_reason"], parent=self) or ""

        self._status(self.T["working"])
        try:
            self.router.send_many([
                "system-view",
                "aaa",
                "undo local-user %s" % mac12,
                "cut access-user mac-address %s" % mac_dashed(mac12),
                "quit",
                "quit",
            ])
            self._maybe_save()
            self.router_users = parse_local_users(self.router.read_aaa())
        except Exception as e:
            self._status("خطأ / Error: %s" % e, ok=False)
            messagebox.showerror(APP_NAME, str(e))
            return

        self.db.revoke_device(mac12, reason)
        self.db.log("revoke_device", mac12, reason)
        self._refresh_device_table()
        self.on_refresh_online()
        self._status(self.T["ok_revoked"])

    def _edit_meta(self, tree, current, apply_fn, refresh_fn, log_kind):
        """
        الاسم والملاحظة بيانات محلية بحتة — الراوتر لا يخزّنهما.
        لذلك لا اتصال هنا ولا أمر save، ويعمل الزر على السطور الملغاة أيضاً.
        """
        sel = tree.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, self.T["no_selection"])
            return
        key = sel[0]
        local = current(key) or {}
        dlg = FieldDialog(self, self.T["edit_meta"], [
            {"key": "name", "label": self.T["ask_name"], "default": local.get("name", "")},
            {"key": "note", "label": self.T["ask_note"], "default": local.get("note", "")},
        ])
        if dlg.result is None:
            return
        name, note = dlg.result["name"], dlg.result["note"]
        if name == local.get("name", "") and note == local.get("note", ""):
            return

        apply_fn(key, name, note)
        self.db.log(log_kind, key, name)
        refresh_fn()
        # الجدول يُبنى من جديد عند التحديث، فنعيد التحديد إلى السطر نفسه
        if tree.exists(key):
            tree.selection_set(key)
            tree.see(key)
        self._status(self.T["ok_edit"])

    def on_edit_device_meta(self):
        self._edit_meta(self.tv_dev, self.db.device, self.db.set_device_meta,
                        self._refresh_device_table, "edit_device_meta")

    def on_edit_portal_meta(self):
        self._edit_meta(self.tv_por, self.db.portal, self.db.set_portal_meta,
                        self._refresh_portal_table, "edit_portal_meta")

    def on_change_device_group(self):
        if not self._need_conn():
            return
        sel = self.tv_dev.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, self.T["no_selection"])
            return
        mac12 = sel[0]
        cur = (self.router_users.get(mac12) or {}).get("group", "")
        dlg = FieldDialog(self, self.T["change_group"], [
            {"key": "group", "label": self.T["ask_group"], "kind": "combo",
             "values": self._groups_list(), "default": cur or ""},
        ])
        if not dlg.result:
            return
        group = dlg.result["group"].strip()
        if not group:
            return

        self._status(self.T["working"])
        try:
            # تغيير الصلاحيات لا يسري على جلسة قائمة — نقطعها ليعيد الجهاز المصادقة
            self.router.send_many([
                "system-view",
                "aaa",
                "local-user %s user-group %s" % (mac12, group),
                "cut access-user mac-address %s" % mac_dashed(mac12),
                "quit",
                "quit",
            ])
            self._verify_user(mac12, expect_group=group)
            self._maybe_save()
        except Exception as e:
            self._status("خطأ / Error: %s" % e, ok=False)
            return

        d = self.db.device(mac12)
        if d:
            d["group"] = group
            self.db.save()
        self.db.log("change_group", mac12, group)
        self._refresh_device_table()
        self._status(self.T["ok_group"] + "  —  قد يحتاج الجهاز دقيقة لإعادة الاتصال")

    def on_trust_online(self):
        """يضيف الجهاز المحدد في جدول المتصلين إلى القائمة الموثوقة."""
        sel = self.tv_on.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, self.T["no_selection"])
            return
        vals = self.tv_on.item(sel[0], "values")
        mac = vals[3] if len(vals) > 3 else ""
        if not mac:
            messagebox.showinfo(APP_NAME, "هذا السطر بلا عنوان ماك / This row has no MAC")
            return
        self.on_add_device(preset_mac=mac)

    def on_cut_user(self):
        if not self._need_conn():
            return
        sel = self.tv_on.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, self.T["no_selection"])
            return
        vals = self.tv_on.item(sel[0], "values")
        uid = vals[0]
        try:
            self.router.send_many(["system-view", "aaa",
                                   "cut access-user user-id %s" % uid,
                                   "quit", "quit"])
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))
            return
        self.on_refresh_online()
        self._status("فُصل المستخدم / User disconnected")

    # -- عمليات حسابات البوابة -----------------------------------------------

    def on_add_portal(self):
        if not self._need_conn():
            return
        dlg = FieldDialog(self, self.T["add_user"], [
            {"key": "user", "label": self.T["ask_user"]},
            {"key": "pw", "label": self.T["ask_pw"], "kind": "password"},
            {"key": "name", "label": self.T["ask_name"]},
            {"key": "group", "label": self.T["ask_group"], "kind": "combo",
             "values": self._groups_list(),
             "default": self.settings.get("default_portal_group", "grp_staff")},
            {"key": "note", "label": self.T["ask_note"]},
        ])
        if not dlg.result:
            return

        user = dlg.result["user"].strip()
        pw = dlg.result["pw"]
        group = dlg.result["group"].strip()

        if not re.match(r"^[A-Za-z0-9_.\-]{1,64}$", user):
            messagebox.showerror(APP_NAME, self.T["err_bad_user"])
            return
        if len(pw) < 8:
            messagebox.showerror(APP_NAME, self.T["err_short_pw"])
            return
        if pw.lower() == user.lower() or pw.lower() == user.lower()[::-1]:
            messagebox.showerror(APP_NAME, self.T["err_pw_eq_user"])
            return
        if not group:
            messagebox.showwarning(APP_NAME, self.T["warn_no_group"])
            return
        if user in self.router_users:
            messagebox.showerror(APP_NAME, "هذا الحساب موجود مسبقاً / Account already exists")
            return

        self._status(self.T["working"])
        try:
            self.router.send_many([
                "system-view",
                "aaa",
                "local-user %s service-type web" % user,
                "local-user %s password cipher %s" % (user, pw),
                "local-user %s user-group %s" % (user, group),
                "quit",
                "quit",
            ])
            ok = self._verify_user(user, expect_group=group, expect_type="web")
            if not ok:
                messagebox.showerror(APP_NAME,
                                     "نُفّذت الأوامر لكن الحساب لم يظهر في إعداد الراوتر.\n"
                                     "راجع تبويب سجل الأوامر.")
                return
            self._maybe_save()
        except Exception as e:
            self._status("خطأ / Error: %s" % e, ok=False)
            messagebox.showerror(APP_NAME, str(e))
            return

        self.db.upsert_portal(user, dlg.result["name"], group, dlg.result["note"])
        self.db.log("add_portal", user, "%s / %s" % (dlg.result["name"], group))
        self._refresh_portal_table()
        self._status(self.T["ok_added"])

    def on_reset_portal_pw(self):
        if not self._need_conn():
            return
        sel = self.tv_por.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, self.T["no_selection"])
            return
        user = sel[0]
        dlg = FieldDialog(self, self.T["reset_pw"], [
            {"key": "pw", "label": self.T["ask_pw"], "kind": "password"},
        ])
        if not dlg.result:
            return
        pw = dlg.result["pw"]
        if len(pw) < 8:
            messagebox.showerror(APP_NAME, self.T["err_short_pw"])
            return
        if pw.lower() == user.lower():
            messagebox.showerror(APP_NAME, self.T["err_pw_eq_user"])
            return
        try:
            self.router.send_many([
                "system-view", "aaa",
                "local-user %s password cipher %s" % (user, pw),
                "quit", "quit",
            ])
            self._maybe_save()
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))
            return
        self.db.log("reset_password", user, "")
        self._status("تم تغيير كلمة المرور / Password changed")

    def on_change_portal_group(self):
        if not self._need_conn():
            return
        sel = self.tv_por.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, self.T["no_selection"])
            return
        user = sel[0]
        cur = (self.router_users.get(user) or {}).get("group", "")
        dlg = FieldDialog(self, self.T["change_group"], [
            {"key": "group", "label": self.T["ask_group"], "kind": "combo",
             "values": self._groups_list(), "default": cur or ""},
        ])
        if not dlg.result:
            return
        group = dlg.result["group"].strip()
        if not group:
            return
        try:
            self.router.send_many([
                "system-view", "aaa",
                "local-user %s user-group %s" % (user, group),
            ])
            self._cut_portal_session(user)
            self.router.send_many(["quit", "quit"])
            self._verify_user(user, expect_group=group)
            self._maybe_save()
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))
            return
        p = self.db.portal(user)
        if p:
            p["group"] = group
            self.db.save()
        self.db.log("change_group", user, group)
        self._refresh_portal_table()
        self._status(self.T["ok_group"])

    def on_del_portal(self):
        if not self._need_conn():
            return
        sel = self.tv_por.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, self.T["no_selection"])
            return
        user = sel[0]
        if not messagebox.askyesno(APP_NAME, self.T["confirm_del"] + "\n\n" + user):
            return
        reason = simpledialog.askstring(APP_NAME, self.T["ask_reason"], parent=self) or ""
        try:
            self.router.send_many([
                "system-view", "aaa",
                "undo local-user %s" % user,
            ])
            self._cut_portal_session(user)
            self.router.send_many(["quit", "quit"])
            self._maybe_save()
            self.router_users = parse_local_users(self.router.read_aaa())
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))
            return
        self.db.revoke_portal(user, reason)
        self.db.log("delete_portal", user, reason)
        self._refresh_portal_table()
        self.on_refresh_online()
        self._status(self.T["ok_revoked"])

    # -- التحقق والحفظ -------------------------------------------------------

    def _cut_portal_session(self, user):
        """
        يفصل جلسة مستخدم البوابة كي تُطبَّق الصلاحيات الجديدة فوراً — VRP لا
        يحدّث جلسة قائمة. بعض الإصدارات تخزّن الاسم مقروناً بالنطاق، لذلك
        نعيد المحاولة بالصيغة user@domain إذا رفض الاسم المجرد.
        يجب أن نكون داخل عرض aaa عند الاستدعاء.
        """
        out = self.router.send("cut access-user username %s" % user)
        if re.search(r"Error|Wrong|Invalid|not exist|does not exist", out, re.I):
            dom = (self.settings.get("portal_domain") or "").strip()
            if dom:
                self.router.send("cut access-user username %s@%s" % (user, dom))

    def _verify_user(self, username, expect_group=None, expect_type=None):
        """يعيد قراءة إعداد الراوتر ويتأكد أن الحساب ثبت فعلاً."""
        aaa = self.router.read_aaa()
        users = parse_local_users(aaa)
        self.router_users = users
        rec = users.get(username)
        if not rec:
            return False
        if expect_type and expect_type not in rec["service_types"]:
            return False
        if expect_group and rec.get("group") != expect_group:
            return False
        return True

    def _maybe_save(self):
        if self.v_autosave.get():
            ok = self.router.save_config()
            self._status(self.T["ok_saved"] if ok else "تعذّر الحفظ / Save failed", ok=ok)

    def on_save_settings(self):
        self.settings["mac_shared_password"] = self.v_macpw.get().strip()
        self.settings["auto_save_config"] = bool(self.v_autosave.get())
        self.settings["ui_lang"] = self.v_lang.get()
        save_settings(self.settings)
        self._status("حُفظت الإعدادات / Settings saved")

    # -- التصدير -------------------------------------------------------------

    def on_export(self, which):
        tv = self.tv_dev if which == "devices" else self.tv_por
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile="ar730_%s_%s.csv" % (which, datetime.date.today()))
        if not path:
            return
        cols = tv["columns"]
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow([tv.heading(c)["text"] for c in cols])
            for iid in tv.get_children():
                w.writerow(tv.item(iid, "values"))
        self._status("صُدّر إلى / Exported to: %s" % path)

    def _on_close(self):
        if self._busy:
            messagebox.showinfo(APP_NAME, self.T["busy"])
            return
        try:
            self.router.close()
        except Exception:
            pass
        self.destroy()


# ----------------------------------------------------------------------------
# وضع التجربة —  python ar730_manager.py --demo
# راوتر AR730 وهمي داخل البرنامج: واجهة حقيقية بلا أي اتصال بجهاز حقيقي.
# يتصرف كالجهاز: يرفض الترتيب الخاطئ، ويرفض كلمة سر تساوي الاسم، ويسأل [Y/N]
# عند الحفظ. للتدريب ولتجربة كل زر قبل العمل على الشبكة الحقيقية.
# كلمة السر في هذا الوضع: أي شيء ما عدا كلمة wrong.
# ----------------------------------------------------------------------------

class _DemoDevice(object):
    def __init__(self):
        self.hostname = "AR730-DEMO"
        self.view = "user"
        self.groups = {"grp_managers": "3010", "grp_staff": "3020", "grp_infra": "3030"}
        self.users = {
            "admin": {"types": {"ssh", "http", "terminal"}, "group": None, "pw": True, "priv": 15},
            "00005e005302": {"types": {"8021x"}, "group": "grp_managers", "pw": True},
            "00005e005303": {"types": {"8021x"}, "group": "grp_infra", "pw": True},
            "sara": {"types": {"web"}, "group": "grp_staff", "pw": True},
        }
        self.online = [
            {"id": "1032", "user": "00005e005302", "ip": "10.0.20.166",
             "mac": "0000-5e00-5302", "status": "Success"},
            {"id": "1027", "user": "00005e005301", "ip": "10.0.21.207",
             "mac": "0000-5e00-5301", "status": "Pre-authen"},
            {"id": "1035", "user": "sara", "ip": "10.0.20.88",
             "mac": "3e4b-91aa-02d1", "status": "Success"},
        ]

    def prompt(self):
        return {"user": "<%s>", "system": "[%s]", "aaa": "[%s-aaa]"}[self.view] % self.hostname

    def run(self, cmd):
        cmd = cmd.strip()
        if not cmd:
            return ""
        if cmd in ("system-view", "sys"):
            self.view = "system"; return ""
        if cmd == "aaa":
            if self.view != "system":
                return "Error: Unrecognized command found at '^' position."
            self.view = "aaa"; return ""
        if cmd == "quit":
            self.view = {"aaa": "system", "system": "user", "user": "user"}[self.view]
            return ""
        if cmd.startswith("screen-length"):
            return ""
        if cmd == "save":
            return "__SAVE__"
        if cmd.startswith("display "):
            return self._display(cmd)
        if cmd.startswith("cut access-user"):
            return self._cut(cmd)
        if cmd.startswith("local-user ") or cmd.startswith("undo local-user "):
            if self.view != "aaa":
                return "Error: Unrecognized command found at '^' position."
            return self._local_user(cmd)
        if cmd.startswith("user-group "):
            self.groups.setdefault(cmd.split()[1], None); return ""
        return "Error: Unrecognized command found at '^' position."

    def _local_user(self, cmd):
        if cmd.startswith("undo "):
            name = cmd.split()[2]
            if name not in self.users:
                return "Error: The user does not exist."
            del self.users[name]; return ""
        parts = cmd.split(); name = parts[1]; rest = parts[2:]
        if rest and rest[0] == "service-type":
            u = self.users.setdefault(name, {"types": set(), "group": None, "pw": False})
            u["types"] |= set(rest[1:]); return ""
        if rest and rest[0] == "password":
            u = self.users.get(name)
            if u is None or not u["types"]:
                return "Error: The normal service type cannot be configured."
            if rest[1] == "irreversible-cipher":
                return ("Error: The local user is not allowed to use an "
                        "irreversible encryption algorithm.")
            if (rest[2] if len(rest) > 2 else "") == name:
                return "Error: The password cannot be the same as a user name."
            u["pw"] = True; return ""
        if rest and rest[0] == "user-group":
            u = self.users.get(name)
            if u is None:
                return "Error: The user does not exist."
            if rest[1] not in self.groups:
                return "Error: The user group does not exist."
            u["group"] = rest[1]; return ""
        if rest and rest[0] == "privilege":
            return ""
        return "Error: Unrecognized command found at '^' position."

    def _cut(self, cmd):
        if self.view != "aaa":
            return "Error: Unrecognized command found at '^' position."
        parts = cmd.split()
        key = parts[2]; val = parts[3] if len(parts) > 3 else ""
        n = len(self.online)
        if key == "mac-address":
            self.online = [o for o in self.online if o["mac"] != val]
        elif key == "username":
            self.online = [o for o in self.online if o["user"] != val.split("@")[0]]
        elif key == "user-id":
            self.online = [o for o in self.online if o["id"] != val]
        return ("Info: The users are cut successfully." if len(self.online) < n
                else "Error: The user does not exist.")

    def _aaa_config(self):
        out = ["#", "aaa", " authentication-scheme default", " domain default",
               " domain portalusers"]
        for name in sorted(self.users):
            u = self.users[name]
            if u["pw"]:
                out.append(" local-user %s password cipher %%^%%#demo" % name)
            if u["types"]:
                out.append(" local-user %s service-type %s" % (name, " ".join(sorted(u["types"]))))
            if u.get("priv"):
                out.append(" local-user %s privilege level %d" % (name, u["priv"]))
            if u["group"]:
                out.append(" local-user %s user-group %s" % (name, u["group"]))
        out.append("#")
        return "\n".join(out)

    def _display(self, cmd):
        if cmd.startswith("display current-configuration configuration aaa"):
            return self._aaa_config()
        if cmd.startswith("display current-configuration"):
            b = ["#", "sysname AR730-DEMO", "#"]
            for g in sorted(self.groups):
                b += ["user-group %s" % g]
                if self.groups[g]:
                    b += [" acl-id %s" % self.groups[g]]
                b += ["#"]
            b += ["acl number 3020", " rule 5 permit ip", "#"]
            b += self._aaa_config().splitlines()
            return "\n".join(b)
        if cmd.startswith("display user-group"):
            r = ["  " + "-" * 48,
                 "  Index  Group-name                       Priority",
                 "  " + "-" * 48]
            for i, g in enumerate(sorted(self.groups)):
                r.append("  %-6d %-32s %d" % (i, g, 0))
            r.append("  " + "-" * 48)
            return "\n".join(r)
        if cmd.startswith("display access-user"):
            r = ["  " + "-" * 78,
                 "  UserID Username                IP address       MAC            Status",
                 "  " + "-" * 78]
            for o in self.online:
                r.append("  %-6s %-23s %-16s %-14s %s" %
                         (o["id"], o["user"], o["ip"], o["mac"], o["status"]))
            r += ["  " + "-" * 78,
                  "  Total: %d, printed: %d" % (len(self.online), len(self.online))]
            return "\n".join(r)
        return "Error: Unrecognized command found at '^' position."


class _DemoChannel(object):
    def __init__(self, dev):
        self.dev = dev
        self.pending_save = False
        self._line = ""
        self.buf = ("\r\nInfo: وضع التجربة — راوتر وهمي، لا اتصال بأي جهاز حقيقي.\r\n"
                    + dev.prompt()).encode()

    def settimeout(self, t): pass

    def send(self, data):
        for ch in data:
            if ch in ("\n", "\r"):
                self._submit(self._line); self._line = ""
            elif ch == " " and not self._line:
                pass
            else:
                self._line += ch
        return len(data)

    def _submit(self, line):
        cmd = line.strip()
        time.sleep(0.05)          # كي يظهر شريط الانتظار كما في الجهاز الحقيقي
        if self.pending_save:
            self.pending_save = False
            self.buf += (("Y\r\nConfiguration file had been saved successfully\r\n"
                          if cmd.upper().startswith("Y") else "N\r\n")
                         + self.dev.prompt()).encode()
            return
        out = self.dev.run(cmd)
        if out == "__SAVE__":
            self.pending_save = True
            self.buf += b"\r\nAre you sure to continue?[Y/N]:"
            return
        self.buf += ((("\r\n" + out + "\r\n") if out else "\r\n")
                     + self.dev.prompt()).encode()

    def recv_ready(self): return len(self.buf) > 0

    def recv(self, n):
        d, self.buf = self.buf[:n], self.buf[n:]
        return d

    def close(self): pass


class _DemoParamiko(object):
    """بديل paramiko في وضع التجربة."""

    device = None

    class AutoAddPolicy(object): pass
    class AuthenticationException(Exception): pass
    class SSHException(Exception): pass

    class SSHClient(object):
        def set_missing_host_key_policy(self, p): pass

        def connect(self, hostname, port=22, username=None, password=None, **kw):
            if password == "wrong":
                raise _DemoParamiko.AuthenticationException(
                    "Authentication failed. (في وضع التجربة أي كلمة سر تُقبل عدا wrong)")

        def invoke_shell(self, width=80, height=24):
            if _DemoParamiko.device is None:
                _DemoParamiko.device = _DemoDevice()
            return _DemoChannel(_DemoParamiko.device)

        def close(self): pass


def main():
    global paramiko

    if "--demo" in sys.argv or "-d" in sys.argv:
        global SETTINGS_FILE, DB_FILE, LOG_FILE
        paramiko = _DemoParamiko()
        # ملفات منفصلة كي لا يختلط التدريب ببيانات الشبكة الحقيقية
        SETTINGS_FILE = os.path.join(BASE_DIR, "demo_settings.json")
        DB_FILE = os.path.join(BASE_DIR, "demo_devices.json")
        LOG_FILE = os.path.join(BASE_DIR, "demo_session.log")
        app = App()
        app.demo_mode = True
        app.title("%s  v%s   —   وضع التجربة (راوتر وهمي)  DEMO"
                  % (app.T["title"], APP_VERSION))
        app._set_state(DEMO_STATE_TEXT, "Demo.TLabel")
        app._status("وضع التجربة: لا اتصال بأي راوتر حقيقي. اضغط (اتصال) للبدء — "
                    "أي كلمة سر تُقبل.")
        app.mainloop()
        return

    if paramiko is None:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            APP_NAME,
            "مكتبة paramiko غير مثبتة.\n\nنفّذ في موجّه الأوامر:\n    pip install paramiko\n\n"
            "paramiko is not installed. Run:  pip install paramiko")
        return
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
