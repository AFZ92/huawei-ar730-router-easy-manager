#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Huawei AR730 Router Easy Manager
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
import zlib
import copy
import shutil
import base64
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

from release_update import check_for_update

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
except ImportError:
    hashes = serialization = padding = None

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

APP_NAME = "Huawei AR730 Router Easy Manager"
# Release tags are vMAJOR.MINOR.PATCH. Keep this in sync with the tag used to
# publish a release; the updater compares it with GitHub Releases on startup.
APP_VERSION = "1.0.1"
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

# القيمة الافتراضية لكلمة سر الماك. إن بقيت كما هي فالحسابات تُنشأ بكلمة سر
# لا يعرفها الراوتر، فيرفض الأجهزة حتى يحظرها — لذلك نمنع الإضافة بها.
MAC_PW_PLACEHOLDER = "CHANGE-ME-SHARED-MAC-PASSWORD"

DEFAULT_SETTINGS = {
    "host": "10.0.1.1",
    "port": 22,
    "username": "admin",
    # كلمة المرور المشتركة لحسابات الماك.
    # يجب أن تطابق حرفياً القيمة المضبوطة في:
    #   mac-access-profile name m_wl
    #    mac-authen username macaddress format without-hyphen password cipher <هنا>
    "mac_shared_password": MAC_PW_PLACEHOLDER,
    "mac_access_profile": "m_wl",
    "default_mac_group": "grp_staff",
    "default_portal_group": "grp_staff",
    "known_groups": ["grp_managers", "grp_staff", "grp_infra"],
    # نطاق حسابات البوابة — يُستخدم فقط عند فشل فصل الجلسة بالاسم المجرد
    "portal_domain": "portalusers",
    "ui_lang": "ar",
    # Qt keeps its own preference so an existing Tk Arabic preference does not
    # unexpectedly override the new application's English-first default.
    "qt_ui_lang": "en",
    "auto_save_config": True,
    # خطوط أخرجها البرنامج من التوزيع: بوابة -> الفحص المربوط وسبب الإخراج،
    # كي تُعاد كما كانت حتى بعد إغلاق البرنامج
    "withdrawn_lines": {},
    "wan_auto": False,
    "wan_auto_withdraw": False,
    # آخر شبكة وقائمة اختيرتا لجهاز إدارة — افتراضيان للنافذة التالية فقط
    "mgmt_iface": "Vlanif20",
    "mgmt_acl": "2999",
    # مزامنة Firebase اختيارية. تبقى بيانات الربط على هذا الجهاز ولا تُرفع.
    "firebase_api_key": "",
    "firebase_project_id": "",
    "firebase_email": "",
    "firebase_password": "",
    # مسار محلي فقط لملف Firebase service-account؛ لا يُرفع ولا يُسجّل.
    "firebase_service_account_file": "",
    "firebase_last_sync": "",
    "firebase_pending_sync": False,
}

BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
RESOURCE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def _user_data_dir():
    """Use a writable per-user location for packaged applications.

    Source checkouts retain adjacent data files for the existing test and
    developer workflow. Installed apps must not write into their replaceable
    installation folder.
    """
    if not getattr(sys, "frozen", False):
        return BASE_DIR
    if sys.platform == "win32":
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"),
                            "AFZ Systems", "AR730 Manager")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/AR730 Manager")
    return os.path.expanduser("~/.local/share/ar730-manager")


DATA_DIR = _user_data_dir()
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except OSError:
    DATA_DIR = BASE_DIR


def _migrate_legacy_data():
    """Copy old portable-release data once, leaving a recoverable original."""
    if DATA_DIR == BASE_DIR:
        return
    for filename in ("ar730_settings.json", "ar730_devices.json", "ar730_session.log",
                     "firebase_service_account.json"):
        old_path, new_path = os.path.join(BASE_DIR, filename), os.path.join(DATA_DIR, filename)
        if os.path.exists(old_path) and not os.path.exists(new_path):
            try:
                shutil.copy2(old_path, new_path)
            except OSError:
                pass
    # The Qt importer records an absolute credential path. Point a migrated
    # settings file at its copied credential before a portable folder is removed.
    settings_path = os.path.join(DATA_DIR, "ar730_settings.json")
    old_credential = os.path.join(BASE_DIR, "firebase_service_account.json")
    new_credential = os.path.join(DATA_DIR, "firebase_service_account.json")
    if os.path.exists(settings_path) and os.path.exists(new_credential):
        try:
            with open(settings_path, "r", encoding="utf-8") as handle:
                settings = json.load(handle)
            if settings.get("firebase_service_account_file") == old_credential:
                settings["firebase_service_account_file"] = new_credential
                with open(settings_path, "w", encoding="utf-8") as handle:
                    json.dump(settings, handle, ensure_ascii=False, indent=2)
        except (OSError, ValueError):
            pass


_migrate_legacy_data()
SETTINGS_FILE = os.path.join(DATA_DIR, "ar730_settings.json")
DB_FILE = os.path.join(DATA_DIR, "ar730_devices.json")
LOG_FILE = os.path.join(DATA_DIR, "ar730_session.log")
# قاعدة أسماء المُصنِّعين من IEEE (MA-L وMA-M وMA-S) مضغوطة بـ zlib.
# تُقرأ عند أول حاجة إليها؛ غيابها لا يعطّل شيئاً — يُعرض رمز المُصنِّع بدل اسمه.
OUI_DIRS = (RESOURCE_DIR, BASE_DIR, os.path.dirname(os.path.abspath(__file__)))
OUI_FILE = "data/oui.dat"


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
        "firebase_title": "مزامنة Firebase (اختيارية)",
        "firebase_key": "Firebase Web API Key",
        "firebase_project": "Firebase Project ID",
        "firebase_email": "بريد حساب المزامنة",
        "firebase_password": "كلمة مرور حساب المزامنة",
        "firebase_hint": "اترك الحقول فارغة للتخزين المحلي فقط. فعّل Email/Password في Firebase Authentication وأنشئ قاعدة Firestore. تُحفظ نسخة محلية دائماً وتُرفع التغييرات تلقائياً عند توفر الإنترنت.",
        "firebase_sync_now": "مزامنة الآن",
        "firebase_ok": "اكتملت مزامنة Firebase.",
        "firebase_offline": "تعذرت مزامنة Firebase؛ حُفظ التغيير محلياً وسيُعاد إرساله عند توفر الإنترنت.",
        "firebase_bad_config": "أكمل بيانات Firebase: API Key وProject ID والبريد وكلمة المرور.",
        "lang_note": "تغيير اللغة يحتاج إعادة تشغيل البرنامج",
        "state_blocked": "محظور على الراوتر ⚠",
        "copy_cell": "نسخ: %s",
        "copy_mac_plain": "نسخ الماك بصيغة الراوتر: %s",
        "copy_row": "نسخ الصف كاملاً",
        "add_online": "إضافة المحدد للموثوقة",
        "add_online_title": "إضافة جهاز متصل إلى الأجهزة الموثوقة",
        "ask_account": "الحساب الحالي:",
        "err_need_name": "اكتب اسماً وصفياً للجهاز كي تعرفه لاحقاً.",
        "info_already_trusted": "هذا الجهاز موثوق مسبقاً.\n\n%(mac)s\nالاسم: %(name)s\nالمجموعة: %(group)s",
        "ask_cut_after_trust": "أُضيف الجهاز. جلسته الحالية ما زالت بالصلاحيات القديمة "
                               "(%(user)s).\n\nفصلها الآن كي يعود خلال دقيقة موثوقاً "
                               "بصلاحيات %(group)s؟",
        "copied": "نُسخ إلى الحافظة: %s",
        "err_placeholder_pw": "كلمة مرور حسابات الماك ما زالت القيمة الافتراضية.\n\n"
                              "ضع في تبويب «الإعدادات» نفس كلمة السر المضبوطة في "
                              "mac-access-profile على الراوتر، أو استخدم زر «تغيير كلمة السر "
                              "وتعميمها». الإضافة بالقيمة الافتراضية تجعل الراوتر يرفض الجهاز "
                              "ثم يحظره.",
        "warn_blocked_after_add": "أُضيف الحساب لكن الراوتر يُظهره محظوراً (block).\n\n"
                                  "هذا يحدث عادةً حين لا تطابق كلمة السر المشتركة ما في "
                                  "mac-access-profile. استخدم «تغيير كلمة السر وتعميمها» من "
                                  "تبويب الإعدادات — فهو يفكّ الحظر أيضاً.",
        "warn_blocked_refresh": "تنبيه: %d من أجهزة الماك محظورة على الراوتر — غالباً كلمة السر المشتركة لا تطابق.",
        "rotate_pw": "تغيير كلمة السر وتعميمها على الأجهزة",
        "rotate_hint": "يغيّر كلمة السر في mac-access-profile وفي كل حسابات الماك دفعة واحدة، "
                       "ويفكّ حظر المحظور منها. الجلسات القائمة لا تنقطع.",
        "ask_profile": "ملف مصادقة الماك (mac-access-profile):",
        "ask_new_pw": "كلمة السر الجديدة:",
        "ask_new_pw2": "تأكيد كلمة السر:",
        "err_no_profile": "لم يُعثر على mac-access-profile فيه mac-authen على الراوتر.",
        "err_pw_mismatch": "كلمتا السر غير متطابقتين.",
        "err_pw_weak": "كلمة السر يجب أن تكون ٨ محارف فأكثر، وتجمع نوعين على الأقل من: "
                       "أحرف كبيرة، أحرف صغيرة، أرقام، رموز.",
        "err_pw_chars": "كلمة السر لا يجوز أن تحوي مسافات أو علامة ؟ أو علامات تنصيص.",
        "err_pw_is_mac": "كلمة السر لا يجوز أن تساوي عنوان ماك.",
        "confirm_rotate": "سيُغيَّر ما يلي على الراوتر:\n\n"
                          "• كلمة السر في mac-access-profile: %(profile)s\n"
                          "• كلمة سر %(count)d من حسابات الماك\n"
                          "• فكّ حظر %(blocked)d حساباً محظوراً\n\n"
                          "الأجهزة المتصلة الآن تبقى متصلة. متابعة؟",
        "err_rotate_profile": "لم تتغيّر كلمة السر في mac-access-profile، ولم يُمسّ أي حساب.\n\n%s",
        "err_rotate_partial": "تغيّرت كلمة السر في الملف لكن هذه الحسابات رفضت التحديث — "
                              "ستُرفض أجهزتها حتى تُصلَح:\n\n%s",
        "ok_rotated": "تغيّرت كلمة السر في الملف و%d من حسابات الماك، وحُفظت في الإعدادات.",
        "tab_wan": "خطوط الإنترنت",
        "wan_hint": "يقرأ من الراوتر حالة كل خط: فحص ping الذي يسحب الخط المقطوع تلقائياً، "
                    "وفحص HTTPS الذي يكشف انتهاء الحصة (المزود يترك ping ويحجب المواقع)، "
                    "وقياس السعة برزمة كبيرة يكشف الحصة المخنوقة التي تنجح فيها كل الفحوص، "
                    "مع زمن الاستجابة وحالة المنفذ.",
        "wan_check": "فحص الخطوط الآن",
        "wan_withdraw": "إخراج الخط من التوزيع",
        "wan_restore": "إعادة الخط إلى التوزيع",
        "wan_copy": "نسخ التقرير",
        "wan_auto": "مراقبة تلقائية كل دقيقة",
        "wan_auto_withdraw": "إخراج الخط المحجوب أو المخنوق تلقائياً وإعادته عند تعافيه",
        "wan_last": "آخر فحص: %s",
        "col_line": "الخط",
        "col_iface": "المنفذ",
        "col_gw": "البوابة",
        "col_route": "التوزيع",
        "col_icmp": "ping",
        "col_https": "HTTPS",
        "col_rtt": "الاستجابة",
        "col_bw": "السعة",
        "col_port": "المنفذ الفيزيائي",
        "col_verdict": "الحكم",
        "verdict_ok": "سليم",
        "verdict_slow": "بطيء / غير مستقر",
        "verdict_throttled": "مخنوق — انتهت الحصة؟",
        "verdict_blocked": "محجوب — انتهت الحصة؟",
        "verdict_down": "مقطوع",
        "verdict_port_down": "المنفذ مفصول",
        "verdict_withdrawn": "خارج التوزيع",
        "verdict_unknown": "غير معروف",
        "route_active": "في التوزيع",
        "route_invalid": "سحبه الراوتر",
        "route_manual": "أخرجه البرنامج (يدوياً)",
        "route_auto": "أخرجه البرنامج (تلقائياً)",
        "res_ok": "✓ يعمل",
        "res_fail": "✗ فشل",
        "res_none": "—",
        "rtt_fmt": "%(avg)s ms · %(loss)s%%",
        "bw_fmt": "%s ميغابت",
        "bw_over": "> %s ميغابت",
        "note_no_track": "المسار غير مربوط بأي فحص — لن يُسحب الخط تلقائياً إن انقطع.",
        "note_track_missing": "المسار مربوط بفحص غير موجود على الراوتر.",
        "note_track_not_icmp": "المسار مربوط بفحص ليس ICMP — هذا الإصدار يتجاهله ولا يسحب الخط. اربطه بفحص ICMP.",
        "note_probe_elsewhere": "عنوان الفحص المربوط لا يخرج عبر بوابة هذا الخط — نتيجته تقيس خطاً آخر.",
        "note_no_https": "لا يوجد فحص HTTPS (TCP 443) لهذا الخط — لا يمكن كشف انتهاء الحصة.",
        "note_speed": "المنفذ يعمل بسرعة %s ميغابت — غالباً كابل تالف أو موصل سيئ.",
        "note_crc": "أخطاء CRC على المنفذ: %s — علامة على مشكلة في الكابل.",
        "note_recent_down": "انقطع المنفذ فيزيائياً خلال آخر ٢٤ ساعة (%s).",
        "note_blocked": "ping يصل لكن HTTPS لا يصل: المزود يحجب التصفح، غالباً انتهت الحصة.",
        "note_throttled": "كل الفحوص تنجح لكن السعة المقاسة %s ميغابت فقط — المزود يخنق الخط، "
                          "غالباً انتهت حصته الشهرية: الرزمة الصغيرة تمرّ والتصفح لا يعمل.",
        "note_no_bw": "تعذّر قياس السعة — يلزمه نجاح فحصَي الرزمة الصغيرة والكبيرة معاً.",
        "rep_title": "تقرير خطوط الإنترنت — %s",
        "rep_verdict": "الحكم",
        "rep_route": "التوزيع",
        "rep_icmp": "فحص ping",
        "rep_https": "فحص HTTPS",
        "rep_live": "قياس مباشر",
        "rep_live_fmt": "%(recv)s/%(sent)s وصلت، فقد %(loss)s%%، المتوسط %(avg)s ms (%(min)s–%(max)s)",
        "rep_bw": "السعة المقاسة",
        "rep_bw_fmt": "%(bw)s (رزمة %(small)s بايت: %(rtt_small)s ms، "
                      "ورزمة %(big)s بايت: %(rtt_big)s ms)",
        "rep_port": "المنفذ",
        "rep_gw": "البوابة",
        "rep_rate": "المعدل الآن ↓%s ↑%s",
        "err_no_line": "اختر خطاً من الجدول أولاً.",
        "err_not_checked": "افحص الخطوط أولاً.",
        "err_last_line": "لا يوجد خط آخر يعمل في التوزيع — إخراج هذا الخط يقطع الإنترنت عن الجميع.",
        "err_already_out": "هذا الخط خارج التوزيع أصلاً.",
        "err_not_out": "هذا الخط لم يُخرجه البرنامج — المسار موجود على الراوتر.",
        "confirm_withdraw": "إخراج %(line)s (البوابة %(gw)s) من التوزيع؟\n\nسيُحذف مساره الافتراضي فيمر كل المستخدمين عبر الخطوط الأخرى، "
                            "ويحفظ البرنامج المسار كي يعيده كما كان.\nالاتصالات المفتوحة عبر هذا الخط ستنقطع وتعود عبر غيره.",
        "confirm_restore": "إعادة %(line)s (البوابة %(gw)s) إلى التوزيع؟\n\nالأمر الذي سيُنفَّذ:\n%(cmd)s",
        "ok_withdrawn": "أُخرج %s من التوزيع.",
        "ok_restored": "أُعيد %s إلى التوزيع.",
        "ok_checked": "فُحص %(n)d خط — سليم: %(ok)d، مشاكل: %(bad)d",
        "warn_blocked_lines": "⚠ خط محجوب أو مخنوق ما زال في التوزيع: %s",
        "auto_withdrew": "مراقبة تلقائية: أُخرج %s من التوزيع (HTTPS لا يعمل).",
        "auto_withdrew_bw": "مراقبة تلقائية: أُخرج %(line)s من التوزيع (السعة %(bw)s ميغابت فقط).",
        "auto_restored": "مراقبة تلقائية: أُعيد %s إلى التوزيع (HTTPS عاد يعمل).",
        "auto_restored_bw": "مراقبة تلقائية: أُعيد %(line)s إلى التوزيع (السعة عادت %(bw)s ميغابت).",
        "auto_error": "مراقبة تلقائية: %s",
        "tab_vlans": "المتّصلون حسب الشبكة",
        "vlan_hint": "اختر شبكة لترى كل جهاز عليها. الأساس هو جدول العناوين الفيزيائية في الراوتر، "
                     "فيظهر حتى الجهاز الذي لم يحصل على عنوان بعد — وهو ما لا يُظهره جدول ARP.",
        "vlan_pick": "الشبكة:",
        "vlan_item": "VLAN %(vid)s",
        "vlan_item_ip": "VLAN %(vid)s — %(ip)s/%(len)d",
        "vlan_summary": "الواجهة %(iface)s%(desc)s · المنافذ: %(ports)s · المجمّع: %(pool)s",
        "vlan_summary_l2": "شبكة بلا عنوان على الراوتر · المنافذ: %(ports)s",
        "vlan_no_iface": "لا عنوان لهذه الشبكة على الراوتر، فلا مجمّع عناوين لها ولا جدول ARP: "
                         "يظهر الجهاز بعنوانه الفيزيائي ومنفذه فقط.",
        "vlan_pool_fmt": "%(used)d مستعمَل من %(total)d، ومتاح %(idle)d",
        "vlan_pool_none": "لا مجمّع",
        "vlan_ports_none": "لا منفذ",
        "vlan_summary_sub": "الواجهة %(iface)s%(desc)s · شبكة موجَّهة: تصل موسومة على %(parent)s "
                            "وتُنهى هنا، فلا منفذ تبديل لها ولا عناوين فيزيائية · المجمّع: %(pool)s",
        "vlan_empty_quiet": "لا جهاز نشط على هذه الشبكة الآن: لا عنوان فيزيائي في جدول التبديل "
                            "ولا مدخل في جدول ARP.",
        "vlan_empty_noport": "لا منفذ على هذا الراوتر يحمل هذه الشبكة، فلا يمرّ به شيء منها: "
                             "الشبكة معرَّفة في جدوله فقط. أضِفها إلى منفذ الوصلة إن أردته أن يراها.",
        "vlan_empty_noswitch": "الشبكة على المنافذ %(ports)s لكنّ الراوتر لم يتعلّم منها أيّ عنوان "
                               "فيزيائي: لا حركة تعبره فيها. غالباً بوّابتها جهاز آخر وأجهزتها "
                               "تتخاطب فيما بينها دون المرور به.",
        "vlan_kind_dhcp": "مؤجَّر",
        "vlan_kind_bind": "محجوز",
        "vlan_kind_static": "ثابت",
        "vlan_kind_none": "بلا عنوان",
        "vlan_noaddr_warn": "%(n)d من %(total)d جهازاً على هذه الشبكة بلا عنوان — "
                            "راجع مجمّع العناوين والمصادقة.",
        "col_port": "المنفذ",
        "col_addr_kind": "نوع العنوان",
        "col_presence": "الحضور",
        "vlan_name_dev": "تسمية الجهاز",
        "vlan_cut": "فصل المحدَّد",
        "vlan_cut_ask": "فصل %(n)d جهازاً عن الشبكة؟ الجهاز يعود فور نجاح مصادقته من جديد.",
        "vlan_cut_no_nac": "لا مصادقة على هذه الشبكة، فلا جلسة تُقطع. "
                           "الفصل فيها يحتاج منع الحركة بقائمة وصول بعد تثبيت العنوان.",
        "vlan_cut_done": "قُطعت %(ok)d جلسة من %(n)d.",
        "vlan_cut_failed": "تعذّر قطع %s",
        "vlan_open_ip": "فتح %s في المتصفح",
        "vlan_named": "سُمّي %(mac)s: %(name)s",
        "vlan_pick_row": "اختر صفّاً من الجدول أولاً.",
        "col_vendor": "المُصنِّع",
        "pres_active": "نشط",
        "pres_seen": "يُرى في الشبكة",
        "pres_lease": "محجوز فقط",
        "vendor_random": "عنوان عشوائي",
        "vendor_private": "مُصنِّع غير معلن",
        "vlan_lease_note": "%(n)d عنواناً محجوزاً لأجهزة غير حاضرة الآن؛ تبقى محجوزة حتى ينتهي إيجارها.",
        "col_other_nets": "شبكات أخرى",
        "vlan_scan": "فحص التداخل",
        "vlan_scan_first": "حدّث قائمة الشبكات أولاً.",
        "vlan_scan_none": "لا جهاز يحمل عنواناً في أكثر من شبكة واحدة (فُحصت %(nets)d شبكة).",
        "vlan_scan_done": "%(n)d جهازاً يحمل عنواناً في أكثر من شبكة (فُحصت %(nets)d شبكة) — "
                          "انظر خانة «شبكات أخرى».",
        "vlan_scan_tight": "مجمّعات أوشكت على النفاد: %s.",
        "vlan_scan_tight_one": "VLAN %(vid)s (%(idle)d متاح من %(usable)d)",
        "vlan_scan_here": "%(n)d من أجهزة هذه الشبكة يحمل عنواناً في شبكة أخرى أيضاً: "
                          "غالباً تصله هذه الشبكة غير موسومة عبر وصلة التبديل.",
        "col_auth": "المصادقة",
        "tab_mgmt": "أجهزة الإدارة",
        "mgmt_hint": "جهاز بعينه يدخل إدارة الراوتر بـ SSH من شبكته العادية دون شبكة الإدارة. "
                     "الراوتر يقيّد الإدارة بالعنوان لا بالماك، فيثبّت البرنامج للجهاز عنواناً بربط DHCP، "
                     "ويمنع انتحال العنوان بـ ARP ثابت، ثم يسمح للعنوان وحده في قائمة الإدارة. "
                     "صفحة الويب تبقى من منفذ الإدارة فقط: http acl يمنع صفحة البوابة عن كل من هو خارج قائمته.",
        "mgmt_add": "إضافة جهاز إدارة",
        "mgmt_remove": "سحب صلاحية الإدارة",
        "mgmt_access": "SSH: قائمة %(vty)s   ·   الويب: %(http)s",
        "mgmt_http_any": "كل المنافذ",
        "mgmt_http_fmt": "قائمة %(acl)s، المنافذ: %(ifaces)s",
        "mgmt_http_noacl": "بلا قائمة",
        "col_net": "الشبكة",
        "col_rule": "القاعدة",
        "col_dhcp": "ربط DHCP",
        "col_arp": "ARP ثابت",
        "mgmt_ready": "جاهز ✓",
        "mgmt_incomplete": "ناقص ⚠",
        "mgmt_on_ip": "متصل الآن",
        "mgmt_on_other": "متصل بعنوان آخر %s — أعد توصيله",
        "mgmt_offline": "غير متصل",
        "ask_net": "الشبكة:",
        "ask_ip": "العنوان (فارغ = أعلى عنوان متاح):",
        "ask_acl": "قائمة الإدارة (ACL):",
        "yes": "نعم",
        "no": "لا",
        "acl_tag_vty": "SSH",
        "acl_tag_http": "ويب",
        "mgmt_err_title": "لا يمكن التنفيذ — صحّح ما يلي:",
        "mgmt_err_net": "الشبكة %(net)s غير موجودة على الراوتر.",
        "mgmt_err_acl": "القائمة %(acl)s غير موجودة أو ليست قائمة أساسية (2000-2999).",
        "mgmt_err_no_free": "لا يوجد عنوان متاح في %(net)s.",
        "mgmt_err_ip_format": "العنوان %(ip)s غير صالح.",
        "mgmt_err_ip_subnet": "العنوان %(ip)s خارج الشبكة المختارة %(net)s.",
        "mgmt_err_ip_router": "العنوان %(ip)s عنوان الراوتر نفسه.",
        "mgmt_err_ip_leased": "العنوان %(ip)s مؤجّر الآن لجهاز آخر (%(mac)s).",
        "mgmt_err_ip_bound": "العنوان %(ip)s مربوط مسبقاً بجهاز آخر (%(mac)s).",
        "mgmt_err_mac_bound": "هذا الماك مربوط مسبقاً بالعنوان %(ip)s — اسحبه أولاً أو اختر ذلك العنوان.",
        "mgmt_err_ip_arp": "على العنوان %(ip)s سجل ARP ثابت مسبقاً (%(mac)s).",
        "mgmt_err_rule_exists": "للعنوان %(ip)s قاعدة مسبقاً في القائمة %(acl)s (rule %(rule)s).",
        "mgmt_err_port": "تعذّر معرفة منفذ الجهاز على %(net)s. وصّل الجهاز بالشبكة أولاً ثم أعد المحاولة.",
        "mgmt_err_rule_id": "لا يوجد رقم قاعدة متاح قبل قاعدة المنع في القائمة %(acl)s.",
        "mgmt_err_untrusted": "على %(net)s مصادقة، والجهاز ليس في الأجهزة الموثوقة فلن يدخل الشبكة أصلاً. "
                              "أضفه أولاً من تبويب «الأجهزة الموثوقة».",
        "mgmt_warn_not_vty": "القائمة %(acl)s ليست مربوطة بـ SSH (المربوطة: %(vty)s) — لن يدخل الجهاز SSH.",
        "mgmt_warn_http_acl": "⚠ على الراوتر http acl %(acl)s، وهو يمنع صفحة البوابة عن كل جهاز خارج هذه القائمة. "
                              "أزله: system-view ثم undo http acl ثم return.",
        "mgmt_warn_reconnect": "الجهاز يستخدم الآن العنوان %(old)s. سيُحرَّر هذا العقد، وبعد التنفيذ أعد توصيل الجهاز ليأخذ %(ip)s.",
        "mgmt_confirm": "سيُنفَّذ على الراوتر:\n\n%(cmds)s\n\nمتابعة؟",
        "mgmt_warn_head": "تنبيهات:",
        "mgmt_step_release": "تحرير عقد DHCP القديم",
        "mgmt_step_bind": "ربط DHCP",
        "mgmt_step_arp": "ARP الثابت",
        "mgmt_step_acl": "قاعدة ACL",
        "mgmt_ok": "تم ✓ الجهاز %(mac)s صار جهاز إدارة.\n\nالعنوان: %(ip)s على %(net)s\n"
                   "SSH: ssh %(user)s@%(gw)s\n\n"
                   "تحقق البرنامج من الربط وARP والقاعدة على الراوتر.",
        "mgmt_ok_status": "تمت إضافة جهاز الإدارة %s والتحقق منه.",
        "mgmt_fail": "فشلت خطوة «%(step)s»، ولم يكتمل التنفيذ.\n\nرد الراوتر:\n%(error)s\n\n%(rollback)s",
        "mgmt_rolled_back": "تم التراجع عن: %s",
        "mgmt_nothing_applied": "لم يُطبَّق أي تغيير قبلها.",
        "mgmt_missing": "نُفّذت الأوامر بلا خطأ، لكن هذه الأجزاء لم تظهر عند إعادة القراءة: %s\n\nراجع سجل الأوامر.",
        "mgmt_desc_dropped": "(رفض الراوتر الوصف فرُبط العنوان بلا وصف.)",
        "mgmt_confirm_remove": "سحب صلاحية الإدارة عن %(ip)s (%(mac)s)؟\n\nسيُنفَّذ: حذف %(parts)s.",
        "mgmt_err_self": "العنوان %s هو عنوان جهازك الذي تتصل منه الآن — حذفه يقطع اتصالك بالراوتر.",
        "mgmt_removed": "سُحبت صلاحية الإدارة عن %s وتحقق البرنامج من حذفها.",
        "mgmt_remove_partial": "لم يُحذف كل شيء عن %(ip)s:\n\n%(detail)s",
        "mgmt_select": "اختر جهازاً من الجدول أولاً.",
    },
    "en": {
        "title": "Huawei AR730 Router Easy Manager",
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
        "firebase_title": "Firebase sync (optional)",
        "firebase_key": "Firebase Web API Key",
        "firebase_project": "Firebase Project ID",
        "firebase_email": "Sync account e-mail",
        "firebase_password": "Sync account password",
        "firebase_hint": "Leave these fields empty for local storage only. Enable Email/Password in Firebase Authentication and create a Firestore database. A local copy is always kept; changes upload automatically when the internet is available.",
        "firebase_sync_now": "Sync now",
        "firebase_ok": "Firebase sync completed.",
        "firebase_offline": "Firebase sync failed; the change is saved locally and will be sent when the internet is available.",
        "firebase_bad_config": "Complete Firebase API Key, Project ID, e-mail and password.",
        "lang_note": "Language change requires restarting the application",
        "state_blocked": "Blocked on router ⚠",
        "copy_cell": "Copy: %s",
        "copy_mac_plain": "Copy MAC in router format: %s",
        "copy_row": "Copy entire row",
        "add_online": "Trust Selected Device",
        "add_online_title": "Add connected device to Trusted Devices",
        "ask_account": "Current account:",
        "err_need_name": "Enter a description so you can recognise the device later.",
        "info_already_trusted": "This device is already trusted.\n\n%(mac)s\nName: %(name)s\nGroup: %(group)s",
        "ask_cut_after_trust": "The device was added. Its current session still has the old "
                               "permissions (%(user)s).\n\nDisconnect it now so it returns "
                               "trusted with %(group)s permissions within a minute?",
        "copied": "Copied to clipboard: %s",
        "err_placeholder_pw": "The shared MAC-account password is still the default value.\n\n"
                              "In the Settings tab, enter the same password configured in "
                              "mac-access-profile on the router, or use Change & Apply "
                              "Password. Adding with the default makes the router reject the "
                              "device and then block it.",
        "warn_blocked_after_add": "The account was added but the router shows it blocked.\n\n"
                                  "This usually means the shared password does not match "
                                  "mac-access-profile. Use Change & Apply Password in the "
                                  "Settings tab - it also unblocks accounts.",
        "warn_blocked_refresh": "Warning: %d MAC account(s) blocked on the router - the shared password likely does not match.",
        "rotate_pw": "Change & Apply Password to Devices",
        "rotate_hint": "Changes the password in mac-access-profile and in every MAC account at "
                       "once, and unblocks blocked ones. Existing sessions stay connected.",
        "ask_profile": "MAC authentication profile (mac-access-profile):",
        "ask_new_pw": "New password:",
        "ask_new_pw2": "Confirm password:",
        "err_no_profile": "No mac-access-profile with mac-authen was found on the router.",
        "err_pw_mismatch": "The passwords do not match.",
        "err_pw_weak": "The password needs 8+ characters and at least two of: uppercase, "
                       "lowercase, digits, symbols.",
        "err_pw_chars": "The password must not contain spaces, ? or quotes.",
        "err_pw_is_mac": "The password must not equal a MAC address.",
        "confirm_rotate": "The following will change on the router:\n\n"
                          "- Password in mac-access-profile: %(profile)s\n"
                          "- Password of %(count)d MAC account(s)\n"
                          "- Unblock %(blocked)d blocked account(s)\n\n"
                          "Connected devices stay connected. Continue?",
        "err_rotate_profile": "The mac-access-profile password did not change; no account was touched.\n\n%s",
        "err_rotate_partial": "The profile password changed but these accounts rejected the "
                              "update - their devices will be refused until fixed:\n\n%s",
        "ok_rotated": "Password changed in the profile and %d MAC account(s), and saved to settings.",
        "tab_wan": "Internet Lines",
        "wan_hint": "Reads each line's state from the router: the ping probe that makes the router drop a dead line, "
                    "the HTTPS probe that reveals an exhausted quota (the ISP lets ping through but blocks websites), "
                    "a big-packet bandwidth measurement that catches a throttled quota every probe still passes, "
                    "plus latency and the port health.",
        "wan_check": "Check Lines Now",
        "wan_withdraw": "Take Line Out of Rotation",
        "wan_restore": "Put Line Back",
        "wan_copy": "Copy Report",
        "wan_auto": "Monitor automatically every minute",
        "wan_auto_withdraw": "Take blocked or throttled lines out automatically and put them back when they recover",
        "wan_last": "Last check: %s",
        "col_line": "Line",
        "col_iface": "Interface",
        "col_gw": "Gateway",
        "col_route": "Rotation",
        "col_icmp": "ping",
        "col_https": "HTTPS",
        "col_rtt": "Latency",
        "col_bw": "Bandwidth",
        "col_port": "Physical Port",
        "col_verdict": "Verdict",
        "verdict_ok": "Healthy",
        "verdict_slow": "Slow / Unstable",
        "verdict_throttled": "Throttled — quota used up?",
        "verdict_blocked": "Blocked — quota used up?",
        "verdict_down": "Down",
        "verdict_port_down": "Port disconnected",
        "verdict_withdrawn": "Out of rotation",
        "verdict_unknown": "Unknown",
        "route_active": "In rotation",
        "route_invalid": "Dropped by router",
        "route_manual": "Taken out (manually)",
        "route_auto": "Taken out (automatically)",
        "res_ok": "✓ Up",
        "res_fail": "✗ Failed",
        "res_none": "—",
        "rtt_fmt": "%(avg)s ms · %(loss)s%%",
        "bw_fmt": "%s Mbit/s",
        "bw_over": "> %s Mbit/s",
        "note_no_track": "The route is not tied to any probe — the line will not be dropped if it goes down.",
        "note_track_missing": "The route is tied to a probe that does not exist on the router.",
        "note_track_not_icmp": "The route is tied to a non-ICMP probe — this firmware ignores it and never drops the line. Tie it to an ICMP probe.",
        "note_probe_elsewhere": "The tied probe's address does not leave through this line's gateway — it measures another line.",
        "note_no_https": "No HTTPS (TCP 443) probe for this line — an exhausted quota cannot be detected.",
        "note_speed": "The port negotiated %s Mbps — usually a damaged cable or a bad connector.",
        "note_crc": "CRC errors on the port: %s — a sign of a cabling problem.",
        "note_recent_down": "The port physically went down within the last 24 hours (%s).",
        "note_blocked": "ping gets through but HTTPS does not: the ISP is blocking browsing, most likely the quota is used up.",
        "note_throttled": "Every probe passes, yet the measured bandwidth is only %s Mbit/s — the ISP is throttling this "
                          "line, most likely its monthly quota is used up: a small packet gets through, browsing does not.",
        "note_no_bw": "Bandwidth could not be measured — it needs both the small and the big ping to answer.",
        "rep_title": "Internet lines report — %s",
        "rep_verdict": "Verdict",
        "rep_route": "Rotation",
        "rep_icmp": "ping probe",
        "rep_https": "HTTPS probe",
        "rep_live": "Live measurement",
        "rep_live_fmt": "%(recv)s/%(sent)s received, %(loss)s%% loss, average %(avg)s ms (%(min)s–%(max)s)",
        "rep_bw": "Measured bandwidth",
        "rep_bw_fmt": "%(bw)s (%(small)s-byte packet: %(rtt_small)s ms, "
                      "%(big)s-byte packet: %(rtt_big)s ms)",
        "rep_port": "Port",
        "rep_gw": "gateway",
        "rep_rate": "current rate ↓%s ↑%s",
        "err_no_line": "Select a line in the table first.",
        "err_not_checked": "Check the lines first.",
        "err_last_line": "No other line is working in rotation — taking this one out would cut everyone off.",
        "err_already_out": "This line is already out of rotation.",
        "err_not_out": "This line was not taken out by the program — its route is on the router.",
        "confirm_withdraw": "Take %(line)s (gateway %(gw)s) out of rotation?\n\nIts default route will be removed so all users go through the other lines, "
                            "and the program keeps the route so it can put it back exactly.\nConnections open through this line will drop and reconnect through another.",
        "confirm_restore": "Put %(line)s (gateway %(gw)s) back into rotation?\n\nCommand to run:\n%(cmd)s",
        "ok_withdrawn": "%s was taken out of rotation.",
        "ok_restored": "%s is back in rotation.",
        "ok_checked": "Checked %(n)d line(s) — healthy: %(ok)d, problems: %(bad)d",
        "warn_blocked_lines": "⚠ A blocked or throttled line is still in rotation: %s",
        "auto_withdrew": "Auto monitor: %s taken out of rotation (HTTPS is failing).",
        "auto_withdrew_bw": "Auto monitor: %(line)s taken out of rotation (only %(bw)s Mbit/s).",
        "auto_restored": "Auto monitor: %s put back into rotation (HTTPS works again).",
        "auto_restored_bw": "Auto monitor: %(line)s put back into rotation (%(bw)s Mbit/s again).",
        "auto_error": "Auto monitor: %s",
        "tab_vlans": "Clients by Network",
        "vlan_hint": "Pick a network to see every device on it. The list is built from the router's "
                     "MAC address table, so even a device that has not got an address yet shows up — "
                     "which the ARP table never reveals.",
        "vlan_pick": "Network:",
        "vlan_item": "VLAN %(vid)s",
        "vlan_item_ip": "VLAN %(vid)s — %(ip)s/%(len)d",
        "vlan_summary": "Interface %(iface)s%(desc)s · Ports: %(ports)s · Pool: %(pool)s",
        "vlan_summary_l2": "No IP interface on the router · Ports: %(ports)s",
        "vlan_no_iface": "This network has no address on the router, so it has no DHCP pool and no "
                         "ARP table: devices show with their MAC and port only.",
        "vlan_pool_fmt": "%(used)d used of %(total)d, %(idle)d free",
        "vlan_pool_none": "no pool",
        "vlan_ports_none": "no port",
        "vlan_summary_sub": "Interface %(iface)s%(desc)s · Routed network: it arrives tagged on "
                            "%(parent)s and terminates here, so it has no switch port and no MAC "
                            "entries · Pool: %(pool)s",
        "vlan_empty_quiet": "No device is active on this network right now: nothing in the MAC "
                            "table and nothing in the ARP table.",
        "vlan_empty_noport": "No port on this router carries this network, so nothing of it passes "
                             "through: the VLAN exists in its table only. Add it to the uplink port "
                             "if you want the router to see it.",
        "vlan_empty_noswitch": "The network is on ports %(ports)s but the router has learned no MAC "
                               "address from it: no traffic crosses it here. Its gateway is most "
                               "likely another device and its clients talk among themselves.",
        "vlan_kind_dhcp": "Leased",
        "vlan_kind_bind": "Reserved",
        "vlan_kind_static": "Static",
        "vlan_kind_none": "No address",
        "vlan_noaddr_warn": "%(n)d of %(total)d devices on this network have no address — "
                            "check the address pool and authentication.",
        "col_port": "Port",
        "col_addr_kind": "Address type",
        "col_presence": "Presence",
        "vlan_name_dev": "Name this device",
        "vlan_cut": "Disconnect selected",
        "vlan_cut_ask": "Disconnect %(n)d device(s)? Each returns as soon as it authenticates again.",
        "vlan_cut_no_nac": "This network has no authentication, so there is no session to cut. "
                           "Disconnecting here needs an ACL after pinning the address.",
        "vlan_cut_done": "%(ok)d of %(n)d sessions cut.",
        "vlan_cut_failed": "Could not cut %s",
        "vlan_open_ip": "Open %s in the browser",
        "vlan_named": "%(mac)s named: %(name)s",
        "vlan_pick_row": "Select a row in the table first.",
        "col_vendor": "Vendor",
        "pres_active": "Active",
        "pres_seen": "Seen on the network",
        "pres_lease": "Address reserved only",
        "vendor_random": "Randomised MAC",
        "vendor_private": "Undisclosed vendor",
        "vlan_lease_note": "%(n)d addresses are reserved for devices that are not here now; they stay reserved until their lease ends.",
        "col_other_nets": "Other networks",
        "vlan_scan": "Cross-network scan",
        "vlan_scan_first": "Refresh the network list first.",
        "vlan_scan_none": "No device holds an address on more than one network (%(nets)d networks scanned).",
        "vlan_scan_done": "%(n)d devices hold an address on more than one network "
                          "(%(nets)d networks scanned) — see the \"Other networks\" column.",
        "vlan_scan_tight": "Pools close to exhaustion: %s.",
        "vlan_scan_tight_one": "VLAN %(vid)s (%(idle)d free of %(usable)d)",
        "vlan_scan_here": "%(n)d devices on this network also hold an address elsewhere: "
                          "this network most likely reaches them untagged over the switch trunk.",
        "col_auth": "Authentication",
        "tab_mgmt": "Management Devices",
        "mgmt_hint": "A specific device reaches router management over SSH from its normal network "
                     "without joining the management network. The router restricts management by address, "
                     "not MAC, so the program pins the device's address with a DHCP binding, blocks address "
                     "spoofing with a static ARP entry, then permits that address alone in the management ACL. "
                     "The web page stays on the management port only: http acl blocks the captive portal "
                     "for everyone outside that ACL.",
        "mgmt_add": "Add Management Device",
        "mgmt_remove": "Remove Management Access",
        "mgmt_access": "SSH: ACL %(vty)s   ·   Web: %(http)s",
        "mgmt_http_any": "all interfaces",
        "mgmt_http_fmt": "ACL %(acl)s, interfaces: %(ifaces)s",
        "mgmt_http_noacl": "no ACL",
        "col_net": "Network",
        "col_rule": "Rule",
        "col_dhcp": "DHCP bind",
        "col_arp": "Static ARP",
        "mgmt_ready": "Ready ✓",
        "mgmt_incomplete": "Incomplete ⚠",
        "mgmt_on_ip": "Connected",
        "mgmt_on_other": "Connected on another address %s — reconnect it",
        "mgmt_offline": "Not connected",
        "ask_net": "Network:",
        "ask_ip": "Address (empty = highest free):",
        "ask_acl": "Management ACL:",
        "yes": "Yes",
        "no": "No",
        "acl_tag_vty": "SSH",
        "acl_tag_http": "web",
        "mgmt_err_title": "Cannot proceed — fix the following:",
        "mgmt_err_net": "Network %(net)s does not exist on the router.",
        "mgmt_err_acl": "ACL %(acl)s does not exist or is not a basic ACL (2000-2999).",
        "mgmt_err_no_free": "No free address in %(net)s.",
        "mgmt_err_ip_format": "%(ip)s is not a valid address.",
        "mgmt_err_ip_subnet": "%(ip)s is outside the selected network %(net)s.",
        "mgmt_err_ip_router": "%(ip)s is the router's own address.",
        "mgmt_err_ip_leased": "%(ip)s is currently leased to another device (%(mac)s).",
        "mgmt_err_ip_bound": "%(ip)s is already bound to another device (%(mac)s).",
        "mgmt_err_mac_bound": "This MAC is already bound to %(ip)s — remove it first or choose that address.",
        "mgmt_err_ip_arp": "%(ip)s already has a static ARP entry (%(mac)s).",
        "mgmt_err_rule_exists": "%(ip)s already has a rule in ACL %(acl)s (rule %(rule)s).",
        "mgmt_err_port": "Could not find the device's port on %(net)s. Connect the device to the network first, then retry.",
        "mgmt_err_rule_id": "No free rule number before the deny rule in ACL %(acl)s.",
        "mgmt_err_untrusted": "%(net)s requires authentication and the device is not trusted, so it cannot join "
                              "the network at all. Add it in the Trusted Devices tab first.",
        "mgmt_warn_not_vty": "ACL %(acl)s is not bound to SSH (bound: %(vty)s) — the device will not get SSH.",
        "mgmt_warn_http_acl": "⚠ The router has http acl %(acl)s, which blocks the captive portal page for every "
                              "device outside that ACL. Remove it: system-view, then undo http acl, then return.",
        "mgmt_warn_reconnect": "The device is using %(old)s now. That lease will be released; reconnect the device afterwards so it takes %(ip)s.",
        "mgmt_confirm": "The following will run on the router:\n\n%(cmds)s\n\nContinue?",
        "mgmt_warn_head": "Warnings:",
        "mgmt_step_release": "releasing the old DHCP lease",
        "mgmt_step_bind": "DHCP binding",
        "mgmt_step_arp": "static ARP",
        "mgmt_step_acl": "ACL rule",
        "mgmt_ok": "Done ✓ %(mac)s is now a management device.\n\nAddress: %(ip)s on %(net)s\n"
                   "SSH: ssh %(user)s@%(gw)s\n\n"
                   "The binding, ARP entry and rule were verified on the router.",
        "mgmt_ok_status": "Management device %s added and verified.",
        "mgmt_fail": "The \"%(step)s\" step failed; the change was not completed.\n\nRouter reply:\n%(error)s\n\n%(rollback)s",
        "mgmt_rolled_back": "Rolled back: %s",
        "mgmt_nothing_applied": "Nothing had been applied before it.",
        "mgmt_missing": "The commands ran without errors, but these parts were not found on re-reading: %s\n\nCheck the command log.",
        "mgmt_desc_dropped": "(The router rejected the description, so the address was bound without one.)",
        "mgmt_confirm_remove": "Remove management access for %(ip)s (%(mac)s)?\n\nWill delete: %(parts)s.",
        "mgmt_err_self": "%s is the address of the computer you are connected from — deleting it cuts your own connection.",
        "mgmt_removed": "Management access for %s removed and verified.",
        "mgmt_remove_partial": "Not everything was removed for %(ip)s:\n\n%(detail)s",
        "mgmt_select": "Select a device in the table first.",
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


_PW_IN_CMD_RE = re.compile(r"(password cipher )\S+")


def mask_password(text):
    """يخفي كلمة السر من السجل — الملف يبقى على القرص ويُرسل عند طلب الدعم."""
    return _PW_IN_CMD_RE.sub(r"\1******", text)


def first_error(output):
    """أول سطر Error: في رد الراوتر، أو سلسلة فارغة."""
    m = re.search(r"^\s*(Error:.*)$", output or "", re.M)
    return m.group(1).strip() if m else ""


def mac_password_problem(pw):
    """يعيد مفتاح رسالة الخطأ إن كانت كلمة سر الماك المشتركة الجديدة غير صالحة، أو None."""
    if not pw or pw == MAC_PW_PLACEHOLDER:
        return "err_placeholder_pw"
    if re.search(r"[\s?\"']", pw):
        return "err_pw_chars"
    # أي صيغة ماك مرفوضة: الراوتر يرفض كلمة سر تساوي اسم الحساب
    if normalize_mac(pw):
        return "err_pw_is_mac"
    classes = sum(bool(re.search(p, pw))
                  for p in (r"[A-Z]", r"[a-z]", r"[0-9]", r"[^A-Za-z0-9]"))
    if len(pw) < 8 or classes < 2:
        return "err_pw_weak"
    return None


def make_text_readonly(widget):
    """
    يجعل صندوق نص للقراءة فقط مع إبقاء التحديد والنسخ. لا نستخدم
    state=disabled لأنه يمنع التحديد بالفأرة على بعض الأنظمة.
    اللصق والقص يمرّان عبر أحداث افتراضية لا عبر <Key>، فنسدّها صراحةً.
    """
    def on_key(ev):
        if ev.state & 0x0008 or ev.state & 0x0004:      # Cmd/Alt أو Ctrl: نسخ وتحديد الكل
            return None
        if ev.keysym in ("Up", "Down", "Left", "Right", "Prior", "Next",
                         "Home", "End", "Tab"):
            return None
        return "break"

    widget.bind("<Key>", on_key)
    for seq in ("<<Paste>>", "<<Cut>>", "<<Clear>>", "<<PasteSelection>>"):
        widget.bind(seq, lambda e: "break")


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
        self._prompt_re = self.PROMPT_RE

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
        # الموجّه هو آخر سطر في الترحيب؛ نأخذ آخر تطابق لا أوله
        found = re.findall(r"(?:^|[\r\n])[<\[]([^<>\[\]\r\n]+)[>\]]", banner)
        self.hostname = found[-1] if found else host
        if found:
            # الموجّه باسم الجهاز تحديداً، لا أي سطر بين قوسين. مخرجات
            # display current-configuration تبدأ بسطر مثل [V300R024C00SPC100]،
            # والراوتر يتوقف بعده لحظة وهو يبني الإعداد — فكان النمط العام
            # يظنه موجّهاً ويقطع القراءة، ويصل باقي الإعداد مع الأمر التالي
            # فتختل كل الأوامر بعده وتفشل عملية التحقق.
            self._prompt_re = re.compile(
                r"[\r\n][<\[][~*]?%s(?:-[^\r\n<>\[\]]{1,80})?[>\]]\s*$"
                % re.escape(self.hostname))
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

        # بقايا رد سابق لم تُقرأ بعد تُنسب إلى الأمر الجديد وتقطعه قبل أوانه؛
        # نفرّغها في السجل أولاً كي يبدأ كل أمر من قناة نظيفة
        stale = self._drain(idle=0.3, limit=3.0) if self.chan.recv_ready() else ""
        if stale:
            self.log_fn(mask_password(stale))

        self.log_fn("\n>>> " + mask_password(command))
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

                if self._prompt_re.search(buf):
                    break
            else:
                time.sleep(0.06)

        # الراوتر يصدي الأمر، فكلمة السر تظهر في الرد أيضاً
        self.log_fn(mask_password(buf))
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

    def read_local_user_states(self):
        """حالة كل حساب (A فعّال / B محظور) — لا تظهر في الإعداد، فقط هنا."""
        return parse_local_user_states(self.send("display local-user", timeout=30))

    def read_mac_profiles(self):
        return parse_mac_profiles(self.send(
            "display current-configuration configuration mac-access-profile", timeout=30))

    def rotate_mac_password(self, profile, password, macs, unblock=()):
        """
        يغيّر كلمة السر المشتركة في mac-access-profile ثم في كل حسابات الماك.

        الملف أولاً: هو الأمر الذي قد يرفضه الراوتر (التعقيد مثلاً)، فإن رُفض
        توقفنا قبل أن نمسّ أي حساب وبقي كل شيء متطابقاً كما كان. ولا نثق بغياب
        Error وحده — نعيد قراءة الملف ونتأكد أن القيمة المشفّرة تغيّرت فعلاً.
        """
        res = {"profile_ok": False, "profile_error": "", "failed": {}, "unblocked": []}
        before = self.read_mac_profiles().get(profile)
        if not before:
            res["profile_error"] = "mac-access-profile %s not found" % profile
            return res
        try:
            self.send("system-view")
            self.send("mac-access-profile name %s" % profile)
            out = self.send("%s password cipher %s" % (before["prefix"], password))
            self.send("quit")
            err = first_error(out)
            after = self.read_mac_profiles().get(profile)
            if err or not after or after["cipher"] == before["cipher"]:
                res["profile_error"] = err or "the encrypted value did not change"
                return res
            res["profile_ok"] = True

            self.send("aaa")
            for mac12 in macs:
                err = first_error(self.send(
                    "local-user %s password cipher %s" % (mac12, password)))
                if err:
                    res["failed"][mac12] = err
            for mac12 in unblock:
                if mac12 in res["failed"]:
                    continue
                err = first_error(self.send("local-user %s state active" % mac12))
                if err:
                    res["failed"][mac12] = err
                else:
                    res["unblocked"].append(mac12)
        finally:
            # return يعيد إلى وضع المستخدم من أي عمق، حتى لو انقطع التسلسل
            try:
                self.send("return")
            except RouterError:
                pass
        return res

    # -- خطوط الإنترنت -------------------------------------------------------

    def read_wan_lines(self, withdrawn=None, live_ping=True):
        """
        يقرأ كل ما يلزم لتقرير الخطوط ويعيد قائمة خطوط مصنّفة.
        كل الأوامر هنا للقراءة فقط.
        """
        routes = parse_static_routes(
            self.send("display current-configuration | include ip route-static", timeout=40))
        states = parse_default_route_states(
            self.send("display ip routing-table 0.0.0.0 0 verbose", timeout=30))
        nqa = parse_nqa_config(
            self.send("display current-configuration configuration nqa", timeout=40))
        brief = parse_ip_brief(self.send("display ip interface brief", timeout=30))
        lines = build_wan_lines(routes, nqa, brief, withdrawn)

        port_cache = {}
        for ln in lines:
            st = states.get(ln["gw"], {})
            ln["route_state"] = st.get("state", "") if ln["in_config"] else ""
            ln["route_age"] = st.get("age", "")
            for slot in ("icmp", "tcp"):
                t = ln[slot]
                ln[slot + "_result"] = parse_nqa_result(self.send(
                    "display nqa results test-instance %s %s" % t["key"], timeout=30)) if t else None
            ln["port"] = None
            ln["phys"] = ""
            if ln["iface"]:
                info = parse_interface(self.send("display interface %s" % ln["iface"], timeout=30))
                ln["desc"] = info["desc"]
                phys = ln["iface"]
                if ln["iface"].lower().startswith("vlanif"):
                    # الـVlanif لا سرعة له ولا أخطاء؛ نقرأ المنفذ الفيزيائي خلفه
                    vid = re.sub(r"\D", "", ln["iface"])
                    members = parse_vlan_ports(self.send("display vlan %s" % vid, timeout=30))
                    phys = members[0] if members else ""
                    if phys:
                        if phys not in port_cache:
                            port_cache[phys] = parse_interface(
                                self.send("display interface %s" % phys, timeout=30))
                        info = dict(port_cache[phys], desc=ln["desc"] or port_cache[phys]["desc"])
                        ln["iface_up"] = ln.get("iface_up") and (info["state"] or "").upper() == "UP"
                ln["phys"] = phys
                ln["port"] = info
            ln["ping"] = None
            ln["ping_big"] = None
            ln["kbps"] = None
            probe = (ln["icmp"] or ln["tcp"] or {}).get("dest")
            if live_ping and probe and ln.get("iface_up"):
                # -nexthop يجبر ping على بوابة الخط حتى لو كان خارج التوزيع،
                # والمنفذ المفصول نتخطاه كي لا ننتظر مهلة كل رزمة بلا فائدة
                ln["ping"] = parse_ping(self.send(
                    "ping -c 10 -t 1000 -nexthop %s %s" % (ln["gw"], probe), timeout=60))
                # الرزمة الكبيرة وحدها تكشف الخط المخنوق: الصغيرة تمر من أضيق
                # خنق فتُظهره سليماً. -s فقط، بلا -f، كي لا تبدو التجزئة فقداً
                ln["ping_big"] = parse_ping(self.send(
                    "ping -c 10 -s %d -t 1000 -nexthop %s %s"
                    % (WAN_BIG_BYTES, ln["gw"], probe), timeout=60))
                ln["kbps"] = estimate_kbps(ln["ping"], ln["ping_big"])
            classify_line(ln)
        return lines

    def withdraw_wan_line(self, gw):
        """يحذف المسار الافتراضي للخط ثم يتحقق من غيابه. يعيد السطر المحذوف."""
        routes = parse_static_routes(
            self.send("display current-configuration | include ip route-static", timeout=40))
        target = [r for r in routes if r["dest"] == "0.0.0.0" and r["len"] == 0
                  and r["nexthop"] == gw]
        if not target:
            raise RouterError("no default route via %s" % gw)
        try:
            self.send("system-view")
            err = first_error(self.send("undo ip route-static 0.0.0.0 0.0.0.0 %s" % gw))
        finally:
            self.send("return")
        if err:
            raise RouterError(err)
        after = parse_static_routes(
            self.send("display current-configuration | include ip route-static", timeout=40))
        if any(r["dest"] == "0.0.0.0" and r["len"] == 0 and r["nexthop"] == gw for r in after):
            raise RouterError("the route via %s is still configured" % gw)
        return target[0]

    def restore_wan_line(self, gw, track=None):
        """يعيد المسار الافتراضي للخط مربوطاً بفحصه كما كان."""
        cmd = "ip route-static 0.0.0.0 0.0.0.0 %s" % gw
        if track:
            cmd += " track nqa %s %s" % tuple(track)
        try:
            self.send("system-view")
            err = first_error(self.send(cmd))
        finally:
            self.send("return")
        if err:
            raise RouterError(err)
        after = parse_static_routes(
            self.send("display current-configuration | include ip route-static", timeout=40))
        if not any(r["dest"] == "0.0.0.0" and r["len"] == 0 and r["nexthop"] == gw
                   for r in after):
            raise RouterError("the route via %s did not appear" % gw)
        return True

    # -- أجهزة الإدارة -------------------------------------------------------

    def read_mgmt_state(self, iface=None, mac12=None):
        """
        صورة كل ما يخص أجهزة الإدارة. كل الأوامر للقراءة فقط.
        مع iface نقرأ أيضاً ما يلزم للإضافة على تلك الشبكة: عناوين DHCP
        المؤجّرة، ومنفذ الجهاز من جدول ARP، والمصادقة على الـVlanif.
        """
        http_cfg = self.send("display current-configuration | include http", timeout=30)
        st = {
            "networks": vlanif_networks(parse_ip_brief(
                self.send("display ip interface brief", timeout=30))),
            "acls": parse_basic_acls(self.send("display acl all", timeout=60)),
            "bindings": parse_acl_bindings(
                self.send("display current-configuration | include acl", timeout=40)),
            "http_permit": parse_http_permit(http_cfg),
            "http_enabled": bool(re.search(r"^\s*http (?:secure-)?server enable", http_cfg, re.M)),
            # خادم البوابة المدمج يخضع لـ http acl أيضاً (ثبت على الجهاز 2026-09-15)
            "portal": bool(re.search(r"^\s*portal local-server", http_cfg, re.M)),
            "binds": parse_static_binds(
                self.send("display current-configuration | include static-bind", timeout=30)),
            "arp_static": parse_arp_static(
                self.send("display current-configuration | include arp static", timeout=30)),
            "nac": {}, "pool": None, "arp_dynamic": {}, "vlan_ports": [],
        }
        if iface:
            st["nac"][iface] = parse_interface_nac(
                self.send("display current-configuration interface %s" % iface, timeout=30))
            st["pool"] = parse_pool_used(
                self.send("display ip pool interface %s used" % iface, timeout=40))
            st["arp_dynamic"] = parse_arp_table(
                self.send("display arp interface %s" % iface, timeout=30))
            vid = re.sub(r"\D", "", iface)
            if not (mac12 and mac12 in st["arp_dynamic"]):
                st["vlan_ports"] = parse_vlan_ports(self.send("display vlan %s" % vid, timeout=30))
        return st

    # -- الشبكات (VLAN) ومن عليها ---------------------------------------------

    def read_vlans(self):
        """
        كل شبكات الجهاز، ومعها واجهة العنونة إن كانت لها واحدة.
        قائمة الشبكات ليست قائمة الـVlanif: أكثر الشبكات هنا بلا عنوان
        (docs/router/lessons-learned.md#L16).
        """
        vlans = parse_vlan_list(self.send("display vlan", timeout=40))
        nets = {}
        for row in parse_ip_brief(self.send("display ip interface brief", timeout=30)):
            m = re.match(r"^Vlanif(\d+)$", row["iface"])
            if m:
                nets[m.group(1)] = dict(row, vid=m.group(1))
            elif "." in row["iface"]:
                # واجهة فرعية: رقم شبكتها من dot1q لا من لاحقة الاسم
                vid = parse_dot1q_vid(self.send(
                    "display current-configuration interface %s" % row["iface"], timeout=30))
                if vid:
                    nets[vid] = dict(row, vid=vid)
        for v in vlans:
            n = nets.get(v["vid"]) or {}
            v["iface"] = n.get("iface", "")
            v["ip"] = n.get("ip", "")
            v["len"] = n.get("len", 0)
        return vlans

    def read_vlan_clients(self, vid, iface=""):
        """
        من على الشبكة vid. كل الأوامر للقراءة فقط.
        الأساس جدول العناوين الفيزيائية لأنه يرى الجهاز الذي لم يأخذ عنواناً،
        ثم نُثريه بـARP وعقود DHCP وجلسات المصادقة حين تكون للشبكة واجهة.
        """
        st = {"vid": str(vid), "iface": iface, "desc": "", "ports": [],
              "pool": None, "rows": [], "nac": False}
        mac_rows = parse_mac_table(self.send("display mac-address", timeout=90))
        st["ports"] = parse_vlan_ports(self.send("display vlan %s" % vid, timeout=30))
        arp, leases = {}, {}
        if iface:
            cfg = self.send("display current-configuration interface %s" % iface, timeout=30)
            m = re.search(r"^\s*description (.+?)\s*$", cfg or "", re.M)
            st["desc"] = m.group(1) if m else ""
            # بلا authentication-profile لا جلسة للجهاز، فلا شيء يُقطع
            st["nac"] = parse_interface_nac(cfg)
            arp = parse_arp_table(self.send("display arp interface %s" % iface, timeout=40))
            pool = self.send("display ip pool interface %s used" % iface, timeout=60)
            st["pool"] = parse_pool_stats(pool)
            leases = parse_pool_leases(pool)
        online = {}
        for r in parse_online(self.read_online()):
            mac12 = normalize_mac(r["mac"]) if r["mac"] else None
            if mac12:
                online[mac12] = r
        st["rows"] = vlan_clients(mac_rows, arp, leases, online, vid)
        return st

    def scan_pools(self, nets):
        """
        يقرأ مجمَّع العناوين لكل شبكة لها واجهة. أمر قراءة واحد لكل شبكة،
        ومنه يُعرف من يحمل عنواناً في أكثر من شبكة (جهاز يتسرّب من شبكته إلى
        غيرها) ومن قارب مجمَّعه على النفاد. الشبكة بلا واجهة لا مجمَّع لها
        فتُتخطّى. يعيد [{"vid", "iface", "pool", "leases"}].
        """
        out = []
        for v in nets:
            iface = v.get("iface")
            if not iface:
                continue
            pool = self.send("display ip pool interface %s used" % iface, timeout=60)
            out.append({"vid": str(v["vid"]), "iface": iface,
                        "pool": parse_pool_stats(pool),
                        "leases": parse_pool_leases(pool)})
        return out

    def cut_users(self, macs):
        """
        يقطع جلسات المصادقة لعناوين فيزيائية بعينها. الأمر لا يُقبل إلا في
        عرض aaa (docs/router/command-reference.md)، ويعمل على المصادَق عليهم
        وحدهم: شبكة بلا authentication-profile لا جلسة فيها تُقطع.
        يعيد {ماك: نص الردّ} كي يُعرض الفشل بدل أن يُبتلع.
        """
        res = {}
        self._system_view()
        self.send("aaa")
        for mac12 in macs:
            res[mac12] = self.send("cut access-user mac-address %s" % mac_dashed(mac12),
                                   timeout=40)
        self.send("quit")
        self.send("quit")
        return res

    def local_address(self):
        """عنوان هذا الجهاز كما يراه الراوتر — كي لا يحذف المستخدم باب دخوله هو."""
        try:
            return self.client.get_transport().sock.getsockname()[0]
        except Exception:
            return ""

    def _system_view(self):
        """يعود إلى system-view من أي عمق."""
        self.send("return")
        self.send("system-view")

    def _run_steps(self, steps, key):
        """ينفّذ أوامر خطوة داخل system-view؛ يعيد أول خطأ أو ''."""
        err = ""
        for cmd in steps[key]:
            err = first_error(self.send(cmd))
            if err:
                break
        return err

    def apply_mgmt_device(self, plan, desc=""):
        """
        ينفّذ الخطة خطوة خطوة. عند أول رفض يتراجع عن كل ما طُبّق قبله
        بالترتيب العكسي ويتوقف، فلا يبقى على الراوتر نصف جهاز.
        ثم يعيد القراءة ويتأكد أن كل جزء ثبت فعلاً.
        يعيد {"ok", "failed_step", "error", "rolled_back", "missing"}.
        """
        res = {"ok": False, "failed_step": "", "error": "", "rolled_back": [],
               "missing": [], "desc_dropped": False}
        steps = mgmt_steps(plan, desc)
        done = []
        try:
            # التحرير يعمل من وضع المستخدم وحده؛ نضمنه مهما كان العرض الحالي
            self.send("return")
            for step in [x for x in steps if x.get("view") == "user"]:
                err = self._run_steps(step, "do")
                if err:
                    res["failed_step"], res["error"] = step["key"], err
                    return res
            steps = [x for x in steps if x.get("view") != "user"]
            self.send("system-view")
            for step in steps:
                err = self._run_steps(step, "do")
                if err and step["key"] == "bind" and desc:
                    # الوصف اختياري؛ إن رفضه الراوتر نربط بلا وصف
                    self._system_view()
                    step = [x for x in mgmt_steps(plan, "") if x["key"] == "bind"][0]
                    err = self._run_steps(step, "do")
                    res["desc_dropped"] = not err
                if err:
                    res["failed_step"], res["error"] = step["key"], err
                    for prev in reversed(done):
                        # الخطأ قد يتركنا داخل interface أو acl
                        self._system_view()
                        if prev["undo"] and not self._run_steps(prev, "undo"):
                            res["rolled_back"].append(prev["key"])
                    return res
                done.append(step)
        finally:
            try:
                self.send("return")
            except RouterError:
                pass

        st = self.read_mgmt_state()
        if not any(b["ip"] == plan["ip"] and b["mac"] == plan["mac"] for b in st["binds"]):
            res["missing"].append("bind")
        a = st["arp_static"].get(plan["ip"])
        if not a or a["mac"] != plan["mac"]:
            res["missing"].append("arp")
        if acl_host_rule(st["acls"].get(plan["acl"]), plan["ip"]) is None:
            res["missing"].append("acl")
        res["ok"] = not res["missing"]
        res["state"] = st
        return res

    def remove_mgmt_device(self, entry):
        """
        يحذف قواعد ACL أولاً (يُغلق الباب فوراً)، ثم ARP، ثم الربط.
        يكمل رغم خطأ في جزء كي لا يبقى الباب مفتوحاً بسبب جزء آخر، ثم يتحقق.
        """
        errors = {}
        ip, mac = entry["ip"], mac_dashed(entry["mac"]) if entry["mac"] else ""
        try:
            self.send("system-view")
            for acl_no, rule_id in entry["rules"]:
                self.send("acl number %s" % acl_no)
                err = first_error(self.send("undo rule %d" % rule_id))
                self.send("quit")
                if err:
                    errors["acl %s rule %d" % (acl_no, rule_id)] = err
            if entry["arp"]:
                amac = mac_dashed(entry.get("arp_mac") or entry["mac"])
                # صيغة الحذف لم تثبت بعد على الجهاز؛ نجرب الأقصر ثم الأطول
                for cmd in ("undo arp static %s" % ip, "undo arp static %s %s" % (ip, amac)):
                    err = first_error(self.send(cmd))
                    if not err:
                        break
                if err:
                    errors["arp"] = err
            if entry["bind"] and entry["iface"]:
                self.send("interface %s" % entry["iface"])
                err = first_error(self.send(
                    "undo dhcp server static-bind ip-address %s" % ip))
                self.send("quit")
                if err:
                    errors["bind"] = err
        finally:
            try:
                self.send("return")
            except RouterError:
                pass
        st = self.read_mgmt_state()
        left = [e for e in mgmt_entries(st) if e["ip"] == ip]
        return {"errors": errors, "left": left[0] if left else None, "state": st}


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


def parse_local_user_states(output):
    """
    يستخرج الحالة من جدول display local-user:
        00005e005368                   B      X         0
    يعيد dict: username -> "A" | "B". الأسماء الطويلة يقصّها الراوتر بـ "..."
    وهي ليست حسابات ماك أصلاً.
    """
    states = {}
    for m in re.finditer(r"^\s*(\S+)\s+([AB])\s+\S+\s+\d+\s*$", output or "", re.M):
        states[m.group(1)] = m.group(2)
    return states


def parse_mac_profiles(output):
    """
    يستخرج ملفات mac-access-profile التي فيها mac-authen بكلمة سر.
    يعيد dict: name -> {"prefix": "mac-authen username ... format without-hyphen",
                        "cipher": "%^%#...%^%#"}
    نحتفظ بما قبل password كما هو كي لا نغيّر صيغة اسم المستخدم عند التعديل.
    """
    profiles = {}
    current = None
    for line in (output or "").splitlines():
        m = re.match(r"^mac-access-profile name (\S+)", line.strip())
        if m:
            current = m.group(1)
            continue
        if not line.startswith(" "):
            current = None
            continue
        m = re.match(r"^\s+(mac-authen username .*?) password cipher (\S+)", line)
        if current and m:
            profiles[current] = {"prefix": m.group(1), "cipher": m.group(2)}
    return profiles


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
# خطوط الإنترنت — تحليل المسارات وفحوص NQA والمنافذ
#
# ما ثبت على الجهاز نفسه (V300R024C00SPC100) ويُبنى عليه كل ما يلي:
#   - كل خط مسار افتراضي ip route-static 0.0.0.0 0.0.0.0 <بوابة> track nqa ...
#   - الراوتر يسحب المسار عند فشل فحص ICMP فقط؛ فحص TCP المربوط بمسار
#     يعمل ويُظهر نتائجه لكن الراوتر يتجاهله ولا يسحب شيئاً.
#   - انتهاء الحصة لا يكشفه ping: المزود يترك ICMP ويمنع كل موقع سوى موقعه.
#     لذلك لكل خط فحص TCP 443 غير مربوط، والبرنامج هو من يقرؤه ويتصرف.
#   - عنوان كل فحص له مسار /32 عبر بوابة خطه، وإلا خرج الفحص من خط آخر.
#   - توقيت NQA على الجهاز غير دقيق (300ms مقابل 44ms فعلياً)، فزمن
#     الاستجابة يُقاس بـ ping -nexthop لا من نتائج NQA.
# ----------------------------------------------------------------------------

_IP_RE = r"\d{1,3}(?:\.\d{1,3}){3}"


def _ip_int(ip):
    a, b, c, d = [int(x) for x in ip.split(".")]
    return (a << 24) | (b << 16) | (c << 8) | d


def _mask_len(mask):
    if mask.isdigit():
        return int(mask)
    return bin(_ip_int(mask)).count("1")


def ip_in_subnet(ip, net_ip, length):
    if length <= 0:
        return True
    shift = 32 - length
    return (_ip_int(ip) >> shift) == (_ip_int(net_ip) >> shift)


def parse_static_routes(output):
    """
    يحلل display current-configuration | include ip route-static.
    يتجاهل مسارات vpn-instance والمسارات عبر اسم منفذ (dhcp).
    """
    routes = []
    for line in output.splitlines():
        m = re.match(r"^\s*ip route-static (%s) (\S+) (%s)(.*)$" % (_IP_RE, _IP_RE), line)
        if not m:
            continue
        dest, mask, nexthop, rest = m.groups()
        track = re.search(r"track nqa (\S+) (\S+)", rest)
        routes.append({
            "dest": dest, "len": _mask_len(mask), "nexthop": nexthop,
            "track": (track.group(1), track.group(2)) if track else None,
            "line": line.strip(),
        })
    return routes


def parse_default_route_states(output):
    """
    يحلل display ip routing-table 0.0.0.0 0 verbose.
    يعيد {بوابة: {"state": Active|Invalid, "iface": ..., "age": ...}}.
    """
    states = {}
    for block in re.split(r"\n\s*Destination:", "\n" + output)[1:]:
        hop = re.search(r"NextHop:\s*(%s)" % _IP_RE, block)
        state = re.search(r"State:\s*(\w+)", block)
        if not hop or not state or hop.group(1) == "0.0.0.0":
            continue
        iface = re.search(r"Interface:\s*(\S+)", block)
        age = re.search(r"Age:\s*(\S+)", block)
        states[hop.group(1)] = {
            "state": state.group(1),
            "iface": iface.group(1) if iface and iface.group(1) != "Unknown" else "",
            "age": age.group(1) if age else "",
        }
    return states


def parse_nqa_config(output):
    """يحلل display current-configuration configuration nqa."""
    tests = {}
    cur = None
    for line in output.splitlines():
        m = re.match(r"^nqa test-instance (\S+) (\S+)\s*$", line)
        if m:
            cur = {"admin": m.group(1), "name": m.group(2), "type": "", "dest": "",
                   "port": "", "started": False}
            tests[(m.group(1), m.group(2))] = cur
            continue
        if cur is None or not line.startswith(" "):
            if line.strip() and not line.startswith(" "):
                cur = None
            continue
        s = line.strip()
        if s.startswith("test-type "):
            cur["type"] = s.split()[1]
        elif s.startswith("destination-address "):
            cur["dest"] = s.split()[-1]
        elif s.startswith("destination-port "):
            cur["port"] = s.split()[1]
        elif s.startswith("start "):
            cur["started"] = True
    return tests


def parse_nqa_result(output):
    """
    آخر نتيجة في display nqa results test-instance.
    الجهاز يعرض السجلات من الأقدم إلى الأحدث، فنأخذ أكبر رقم Test.
    """
    best = None
    parts = re.split(r"\n\s*\d+\s*\.\s*Test\s+", "\n" + output)
    for part in parts[1:]:
        num = re.match(r"(\d+)", part)
        if not num:
            continue

        def num_of(pattern):
            m = re.search(pattern, part)
            return int(m.group(1)) if m else 0

        res = {
            "test": int(num.group(1)),
            "ok": bool(re.search(r"Completion:\s*success", part)),
            "sent": num_of(r"Send operation times:\s*(\d+)"),
            "recv": num_of(r"Receive response times:\s*(\d+)"),
            "loss": num_of(r"Lost packet ratio:\s*(\d+)"),
            "avg": None,
        }
        avg = re.search(r"Min/Max/Average Completion Time:\s*\d+/\d+/(\d+)", part)
        if avg and res["recv"]:
            res["avg"] = int(avg.group(1))
        if best is None or res["test"] > best["test"]:
            best = res
    return best


def parse_ip_brief(output):
    """يحلل display ip interface brief."""
    rows = []
    for line in output.splitlines():
        m = re.match(r"^(\S+)\s+(%s)/(\d+)\s+(\S+)\s+(\S+)" % _IP_RE, line.strip())
        if m:
            rows.append({"iface": m.group(1), "ip": m.group(2), "len": int(m.group(3)),
                         "phy": m.group(4), "proto": m.group(5)})
    return rows


def _vrp_time(text):
    m = re.search(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", text or "")
    if not m:
        return None
    try:
        return datetime.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def parse_interface(output):
    """يحلل display interface <منفذ> — الحالة والسرعة والمعدل والأخطاء."""
    def grab(pattern, cast=str):
        m = re.search(pattern, output)
        if not m:
            return None
        try:
            return cast(m.group(1).strip())
        except ValueError:
            return None

    info = {
        "state": grab(r"current state\s*:\s*(\S+)"),
        "desc": grab(r"Description:([^\r\n]*)") or "",
        "speed": grab(r"Speed\s*:\s*(\d+)", int),
        "duplex": grab(r"Duplex\s*:\s*(\w+)"),
        "in_bps": grab(r"input rate (\d+) bits/sec", int),
        "out_bps": grab(r"output rate (\d+) bits/sec", int),
        "crc": grab(r"CRC:\s*(\d+)", int),
        "in_errors": None,
        "pvid": grab(r"PVID\s*:\s*(\d+)", int),
        "last_down": grab(r"Last physical down time\s*:\s*([^\r\n]+)"),
        "now": grab(r"Current system time:\s*([^\r\n]+)"),
    }
    # أول Total Error بعد Input هو أخطاء الاستقبال؛ الثاني للإرسال
    m = re.search(r"Input:.*?Total Error:\s*(\d+)", output, re.S)
    if m:
        info["in_errors"] = int(m.group(1))
    return info


def parse_vlan_ports(output):
    """المنافذ الفيزيائية الأعضاء في VLAN من display vlan <رقم>."""
    ports = []
    for line in output.splitlines():
        if "Port:" not in line:
            continue
        for name in re.findall(r"[A-Za-z-]*Ethernet\d+/\d+/\d+", line.split("Port:", 1)[1]):
            if name not in ports:
                ports.append(name)
    return ports


def parse_ping(output):
    """ملخص ping في VRP."""
    def grab(pattern, cast):
        m = re.search(pattern, output)
        return cast(m.group(1)) if m else None

    sent = grab(r"(\d+) packet\(s\) transmitted", int)
    if sent is None:
        return None
    rtt = re.search(r"min/avg/max = (\d+)/(\d+)/(\d+)", output)
    return {
        "sent": sent,
        "recv": grab(r"(\d+) packet\(s\) received", int) or 0,
        "loss": grab(r"([\d.]+)% packet loss", float),
        "min": int(rtt.group(1)) if rtt else None,
        "avg": int(rtt.group(2)) if rtt else None,
        "max": int(rtt.group(3)) if rtt else None,
    }


def build_wan_lines(routes, nqa, brief, withdrawn=None):
    """
    يجمع صورة الخطوط من الإعداد وحده، بلا أي نتائج فحص بعد.

    الخط = بوابة لها مسار افتراضي، أو بوابة أخرجها البرنامج من التوزيع
    (المسار محذوف من الراوتر لكنه محفوظ في withdrawn كي نعيده كما كان).
    """
    withdrawn = withdrawn or {}
    host_via = {r["dest"]: r["nexthop"] for r in routes if r["len"] == 32}
    lines = {}

    def line_for(gw):
        if gw not in lines:
            lines[gw] = {"gw": gw, "track": None, "in_config": False, "withdrawn": None,
                         "icmp": None, "tcp": None, "iface": "", "notes": []}
        return lines[gw]

    for r in routes:
        if r["dest"] == "0.0.0.0" and r["len"] == 0:
            ln = line_for(r["nexthop"])
            ln["in_config"] = True
            ln["track"] = r["track"]
    for gw, rec in withdrawn.items():
        ln = line_for(gw)
        if not ln["in_config"]:
            ln["withdrawn"] = rec
            if rec.get("track"):
                ln["track"] = tuple(rec["track"])

    for key, t in sorted(nqa.items()):
        gw = host_via.get(t["dest"])
        if gw not in lines:
            continue
        ln = lines[gw]
        slot = "tcp" if t["type"] == "tcp" else ("icmp" if t["type"] == "icmp" else None)
        if slot is None:
            continue
        tracked = ln["track"] == key
        # الفحص المربوط بالمسار له الأولوية على فحص آخر من النوع نفسه
        if ln[slot] is None or tracked:
            ln[slot] = dict(t, key=key)

    for gw, ln in lines.items():
        for row in brief:
            if ip_in_subnet(gw, row["ip"], row["len"]):
                ln["iface"] = row["iface"]
                ln["iface_up"] = row["phy"].lower() == "up"
                break
        tr = ln["track"]
        if ln["in_config"] and not tr:
            ln["notes"].append("note_no_track")
        elif tr:
            t = nqa.get(tr)
            if not t:
                ln["notes"].append("note_track_missing")
            else:
                if t["type"] != "icmp":
                    ln["notes"].append("note_track_not_icmp")
                if host_via.get(t["dest"]) != gw:
                    ln["notes"].append("note_probe_elsewhere")
        if ln["tcp"] is None:
            ln["notes"].append("note_no_https")
    return [lines[gw] for gw in sorted(lines, key=_ip_int)]


WAN_SLOW_LOSS = 10          # نسبة فقد (%) تجعل الخط «غير مستقر»
WAN_SLOW_RTT = 250          # متوسط زمن استجابة (ms) يجعل الخط «بطيئاً»

# قياس السعة: رزمة صغيرة ورزمة كبيرة، والفارق بين أدنى زمنيهما هو زمن دفع
# البايتات الزائدة عبر الأنبوب، فيعطينا سعته. انظر docs/router/lessons-learned.md#L15
WAN_SMALL_BYTES = 56        # حجم ping الافتراضي على الجهاز
WAN_BIG_BYTES = 1400        # أكبر حجم يبقى تحت MTU 1500 بلا تجزئة
WAN_MIN_KBPS = 2000         # تحت هذا يُعدّ الخط مخنوقاً (انتهت حصته)
WAN_OK_KBPS = 4000          # وفوق هذا وحده يُعاد إلى التوزيع — عتبتان تمنعان التأرجح
WAN_BW_CAP_KBPS = 50000     # سقف التقدير: فوقه يصير الفارق أصغر من دقة القياس


def estimate_kbps(small, big):
    """
    يقدّر سعة الخط بالكيلوبت/ثانية من قياسَي ping بحجمين.

    نستعمل أدنى زمن لا متوسطه: الأدنى هو زمن الدفع الصافي بلا طوابير.

    وللقياس ضجيج: على خط سليم قرأنا أدنى ٥٠ ms للرزمة الصغيرة و٣٠ ms
    للكبيرة — فارق سالب لا معنى له. لذلك لا نصدّق فارقاً أصغر من تشتّت
    الرزمة الصغيرة نفسها (max-min)، ونعدّ الخط عندها سريعاً. الثمن أننا
    نتغاضى عن خنق طفيف، والمكسب أننا لا نُخرج خطاً سليماً بضجيج قياس.
    """
    if not small or not big or not small.get("min") or not big.get("min"):
        return None
    delta = big["min"] - small["min"]
    noise = (small.get("max") or small["min"]) - small["min"]
    if delta <= noise:
        return WAN_BW_CAP_KBPS
    bits = 2.0 * (WAN_BIG_BYTES - WAN_SMALL_BYTES) * 8
    return min(WAN_BW_CAP_KBPS, int(bits / (delta / 1000.0) / 1000.0))


def classify_line(ln):
    """
    يعيد الحكم على الخط:
      withdrawn  أخرجه البرنامج من التوزيع
      port_down  المنفذ مفصول أو لا عنوان له
      down       فحص ping فشل — الراوتر يسحبه بنفسه
      blocked    ping يعمل وHTTPS لا — انتهت الحصة أو المزود يحجب
      throttled  كل الفحوص تنجح لكن السعة المقاسة تحت الحد — حصة مخنوقة
      slow       يعمل بفقد أو تأخير مرتفع
      ok         سليم
      unknown    لا فحوص تكفي للحكم
    """
    icmp = ln.get("icmp_result")
    tcp = ln.get("tcp_result")
    ping = ln.get("ping")
    if not ln.get("iface") or not ln.get("iface_up"):
        health = "port_down"
    elif icmp is not None and not icmp["ok"]:
        health = "down"
    elif icmp is None and ln.get("route_state") == "Invalid":
        health = "down"
    elif tcp is not None and not tcp["ok"]:
        health = "blocked"
    elif ln.get("kbps") is not None and ln["kbps"] < WAN_MIN_KBPS:
        # يسبق slow لأنه سببه لا عَرَضه: الفقد والتأخير نتيجتان للخنق
        health = "throttled"
    elif ping and (ping["recv"] == 0 or (ping["loss"] or 0) >= WAN_SLOW_LOSS
                   or (ping["avg"] or 0) >= WAN_SLOW_RTT):
        health = "down" if ping["recv"] == 0 and icmp is None else "slow"
    elif icmp is None and tcp is None and not ping:
        health = "unknown"
    else:
        health = "ok"
    ln["health"] = health
    ln["verdict"] = "withdrawn" if ln.get("withdrawn") else health
    return ln["verdict"]


# ----------------------------------------------------------------------------
# أجهزة الإدارة — جهاز بعينه يدخل SSH والويب من شبكة المستخدمين
#
# الراوتر لا يقيّد الإدارة بالماك، فقوائم vty وhttp أساسية (2000-2999) تطابق
# عنوان المصدر فقط. فنثبّت للجهاز عنواناً ونسمح بهذا العنوان وحده:
#   ١) ربط DHCP ثابت: الماك يأخذ العنوان نفسه دائماً
#   ٢) ARP ثابت: الراوتر لا يرد على العنوان إلا بهذا الماك، فمن ينتحل
#      العنوان يدوياً من جهاز آخر لا يكتمل اتصاله
#   ٣) قاعدة permit للعنوان في ACL الإدارة
# الصيغ الثلاث ثبتت على الجهاز نفسه (V300R024C00SPC100): static-bind يقبل
# description، وarp static بعد vid يلزمه interface، وhttp acl يقبل 2000-2999.
# ----------------------------------------------------------------------------

_MAC_DASH_RE = r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
_IFACE_ABBR = (("XGE", "XGigabitEthernet"), ("GE", "GigabitEthernet"),
               ("Eth", "Ethernet"))


def expand_iface(name):
    """GE0/0/2 -> GigabitEthernet0/0/2 (جدول ARP يختصر أسماء المنافذ)."""
    for short, full in _IFACE_ABBR:
        if re.match(r"^%s\d" % short, name or ""):
            return full + name[len(short):]
    return name


def valid_ip(text):
    if not re.match(r"^%s$" % _IP_RE, text or ""):
        return False
    return all(0 <= int(x) <= 255 for x in text.split("."))


def parse_basic_acls(output):
    """
    يحلل display acl all ويعيد القوائم الأساسية وحدها:
        Basic ACL 2999, 3 rules
        MGMT-ACCESS
        Acl's step is 5
         rule 5 permit source 10.0.1.0 0.0.0.255 (38 matches)
         rule 3000 deny (180 matches)
    {رقم: {"desc": str, "rules": [{"id", "action", "src", "wild"}]}}
    """
    acls = {}
    cur = None
    for line in (output or "").splitlines():
        s = line.strip()
        m = re.match(r"^(\w+) ACL (\d+),", s)
        if m:
            cur = None
            if m.group(1) == "Basic":
                cur = acls[m.group(2)] = {"desc": "", "rules": []}
            continue
        if cur is None or not s:
            continue
        # قاعدة المضيف يعرضها الجهاز بقناع 0 مجرد: rule 7 permit source 10.0.20.250 0
        m = re.match(r"^rule (\d+) (permit|deny)(?: source (%s)(?: (%s|0)\b)?)?" % (_IP_RE, _IP_RE), s)
        if m:
            cur["rules"].append({"id": int(m.group(1)), "action": m.group(2),
                                 "src": m.group(3) or "", "wild": m.group(4) or ""})
        elif not line.startswith(" ") and not s.startswith("Acl's step") and not cur["rules"]:
            cur["desc"] = s
    return acls


def acl_host_rule(acl, ip):
    """رقم قاعدة permit لهذا العنوان وحده داخل القائمة، أو None."""
    for r in (acl or {}).get("rules", []):
        if r["action"] == "permit" and r["src"] == ip and r["wild"] in ("0", "0.0.0.0"):
            return r["id"]
    return None


def acl_free_rule_id(acl, start=100):
    """
    رقم قاعدة فارغ يقع قبل أول قاعدة deny عامة، وإلا لم يُطبَّق الإذن أبداً
    لأن القوائم تُطابَق بترتيب الأرقام. نبدأ من 100 كي تتجمع أجهزة الإدارة
    بعيداً عن قواعد الشبكات (5، 10...).
    """
    rules = (acl or {}).get("rules", [])
    used = set(r["id"] for r in rules)
    deny = [r["id"] for r in rules if r["action"] == "deny" and not r["src"]]
    limit = min(deny) if deny else 4294967294
    for lo in (start, 1):
        for rid in range(lo, min(limit, lo + 5000)):
            if rid not in used:
                return rid
    return None


def parse_acl_bindings(output):
    """
    من display current-configuration | include acl:
      ' acl 2999 inbound'  داخل user-interface vty -> SSH
      ' http acl 2999'     -> الويب
    """
    vty, http = set(), None
    for line in (output or "").splitlines():
        m = re.match(r"^\s*acl (\d+) inbound\s*$", line)
        if m:
            vty.add(m.group(1))
        m = re.match(r"^\s*http acl (\d+)\s*$", line)
        if m:
            http = m.group(1)
    return {"vty": vty, "http": http}


def parse_http_permit(output):
    """قائمة المنافذ في http server permit interface، أو None إن كان الويب مسموحاً من كل المنافذ."""
    for line in (output or "").splitlines():
        m = re.match(r"^\s*http server permit interface (.+?)\s*$", line)
        if m:
            return m.group(1).split()
    return None


def parse_static_binds(output):
    """أسطر dhcp server static-bind من الإعداد: [{"ip", "mac", "desc"}]."""
    binds = []
    for line in (output or "").splitlines():
        m = re.match(r"^\s*dhcp server static-bind ip-address (%s) mac-address (%s)(?: description (.+?))?\s*$"
                     % (_IP_RE, _MAC_DASH_RE), line)
        if m:
            binds.append({"ip": m.group(1), "mac": normalize_mac(m.group(2)),
                          "desc": m.group(3) or ""})
    return binds


def parse_arp_static(output):
    """أسطر arp static من الإعداد: {عنوان: {"mac", "vid", "iface", "line"}}."""
    entries = {}
    for line in (output or "").splitlines():
        m = re.match(r"^\s*arp static (%s) (%s)(.*)$" % (_IP_RE, _MAC_DASH_RE), line)
        if not m:
            continue
        rest = m.group(3)
        vid = re.search(r"vid (\d+)", rest)
        iface = re.search(r"interface (\S+)", rest)
        entries[m.group(1)] = {"mac": normalize_mac(m.group(2)),
                               "vid": vid.group(1) if vid else "",
                               "iface": iface.group(1) if iface else "",
                               "line": line.strip()}
    return entries


def parse_arp_table(output):
    """
    يحلل display arp interface VlanifN. كل مدخل ديناميكي سطران:
        10.0.20.53      0000-5e00-5362  17        D-0         GE0/0/2
                                                    20/-
    {ماك: {"ip", "iface", "type"}}
    """
    table = {}
    for line in (output or "").splitlines():
        m = re.match(r"^\s*(%s)\s+(%s)\s+(?:\d+\s+)?(\S+)\s+(\S+)" % (_IP_RE, _MAC_DASH_RE), line)
        if m:
            table[normalize_mac(m.group(2))] = {"ip": m.group(1), "type": m.group(3),
                                                "iface": expand_iface(m.group(4))}
    return table


def parse_pool_used(output):
    """
    يحلل display ip pool interface VlanifN used:
      المدى من Network section، والعناوين المؤجّرة من جدول Index IP Client-ID.
    """
    res = {"start": "", "end": "", "used": {}}
    m = re.search(r"^\s*(%s)\s+(%s)\s+\d+\s+\d+" % (_IP_RE, _IP_RE), output or "", re.M)
    if m:
        res["start"], res["end"] = m.group(1), m.group(2)
    for m in re.finditer(r"^\s*\d+\s+(%s)\s+(%s)\s+\S+\s+\S+\s+(\S+)" % (_IP_RE, _MAC_DASH_RE),
                         output or "", re.M):
        res["used"][m.group(1)] = normalize_mac(m.group(2))
    return res


def parse_interface_nac(output):
    """هل على الـVlanif مصادقة (authentication-profile)؟ الجهاز غير الموثوق لا يعبرها."""
    return bool(re.search(r"^\s*authentication-profile \S+", output or "", re.M))


def parse_vlan_list(output):
    """
    يحلل display vlan المجرّد: كل شبكات الجهاز لا الشبكات ذات العنوان فقط.
        VLAN ID Type         Status   MAC Learning ...
        20      common       enable   enable       ...
    [{"vid", "type", "status"}] مرتّبة رقمياً.
    """
    vlans = []
    for line in (output or "").splitlines():
        m = re.match(r"^\s*(\d+)\s+(\S+)\s+(\S+)\s+\S+", line)
        if m and m.group(2) in ("common", "super", "sub"):
            vlans.append({"vid": m.group(1), "type": m.group(2), "status": m.group(3)})
    return sorted(vlans, key=lambda v: int(v["vid"]))


def mac_is_random(mac12):
    """
    هل العنوان الفيزيائي مُولَّد عشوائياً؟ البت الثاني من أول بايت (locally
    administered) يرفعه الجهاز حين يخفي عنوانه الحقيقي — وهو سلوك الهواتف
    الحديثة افتراضياً. مثل هذا العنوان يتبدّل بين الجلسات، فلا يصلح لحجز
    عنوان ولا لقائمة ثقة.
    """
    try:
        return bool(int(mac12[1], 16) & 0x2)
    except (ValueError, IndexError, TypeError):
        return False


_OUI_TABLE = None


def load_oui():
    """{بادئة سداسية عشرية: اسم المُصنِّع}. يُقرأ مرة واحدة ويُحفظ في الذاكرة."""
    global _OUI_TABLE
    if _OUI_TABLE is None:
        _OUI_TABLE = {}
        for d in OUI_DIRS:
            path = os.path.join(d, *OUI_FILE.split("/"))
            try:
                with open(path, "rb") as f:
                    text = zlib.decompress(f.read()).decode("utf-8")
            except Exception:
                continue
            for line in text.splitlines():
                if "\t" in line:
                    pref, name = line.split("\t", 1)
                    _OUI_TABLE[pref] = name
            break
    return _OUI_TABLE


def mac_vendor(mac12):
    """
    اسم المُصنِّع من بادئة العنوان. IEEE تخصّص بثلاثة أطوال — ٣٦ بت للشركات
    الصغيرة و٢٨ و٢٤ بت — فنجرّب الأطول أولاً وإلا نسبنا الجهاز إلى الشركة
    الكبرى التي اشترت الكتلة. العنوان العشوائي لا مُصنِّع له أصلاً.
    بادئة مسجَّلة باسم مخفي تعود بـ"\x00" كي تميّزها الواجهة عن غير المسجَّلة.
    """
    if not mac12 or mac_is_random(mac12):
        return ""
    table = load_oui()
    up = mac12.upper()
    for n in (9, 7, 6):
        name = table.get(up[:n])
        if name:
            return name
    return ""


def mac_oui(mac12):
    """أول ثلاثة بايتات: رمز المُصنِّع كما تنشره IEEE. 00005e -> 00:00:5E"""
    return ":".join(mac12[i:i + 2] for i in range(0, 6, 2)).upper() if mac12 else ""


def parse_dot1q_vid(output):
    """
    رقم الشبكة الذي تُنهيه واجهة فرعية: dot1q termination vid 60 -> "60".
    اللاحقة .60 في اسم الواجهة عُرف محلي لا قاعدة، فالمصدر هو هذا السطر.
    """
    m = re.search(r"^\s*dot1q termination vid (\d+)", output or "", re.M)
    return m.group(1) if m else ""


def parse_mac_table(output):
    """
    يحلل display mac-address:
        0000-5e00-5371      20/-/-/-             GE0/0/2      dynamic   public
    المدخل لكل (ماك، شبكة) لا لكل جهاز — الماك نفسه قد يظهر في شبكتين
    (docs/router/lessons-learned.md#L16). [{"mac", "vid", "port", "kind"}]
    """
    rows = []
    for m in re.finditer(r"^\s*(%s)\s+(\d+)/\S*\s+(\S+)\s+(\S+)" % _MAC_DASH_RE,
                         output or "", re.M):
        rows.append({"mac": normalize_mac(m.group(1)), "vid": m.group(2),
                     "port": expand_iface(m.group(3)), "kind": m.group(4)})
    return rows


def parse_pool_leases(output):
    """
    عقود العنونة من display ip pool interface VlanifN used مفهرسة بالماك:
        199      10.0.1.200        0000-5e00-5365    DHCP      85619   Used
    {ماك: {"ip", "left", "type", "status"}}. مجمّع بلا عقود لا يطبع الجدول
    أصلاً فيعود القاموس فارغاً (docs/router/lessons-learned.md#L16).
    """
    leases = {}
    for m in re.finditer(r"^\s*\d+\s+(%s)\s+(%s)\s+(\S+)\s+(\S+)\s+(\S+)"
                         % (_IP_RE, _MAC_DASH_RE), output or "", re.M):
        leases[normalize_mac(m.group(2))] = {"ip": m.group(1), "type": m.group(3),
                                             "left": m.group(4), "status": m.group(5)}
    return leases


def parse_pool_stats(output):
    """أرقام المجمّع من سطر Address Statistic: {"total", "used", "idle", ...} أو None."""
    body = (output or "").split("Address Statistic", 1)
    if len(body) < 2:
        return None
    body = body[1]
    nums = {}
    for key in ("Total", "Used", "Idle", "Expired", "Conflict", "Disabled"):
        m = re.search(r"%s\s*:(\d+)" % key, body)
        if m:
            nums[key.lower()] = int(m.group(1))
    return nums or None


def vlan_clients(mac_rows, arp, leases, online, vid):
    """
    يدمج الجداول في صفّ واحد لكل جهاز حاضر على الشبكة vid.
    الحضور يشهد به مصدران: جدول العناوين الفيزيائية، وهو وحده يرى الجهاز الذي
    لم يحصل على عنوان في شبكة مبدَّلة؛ وجدول ARP، وهو وحده يرى أجهزة شبكةٍ
    موجَّهة عبر واجهة فرعية لأن وسمها يُنهى فلا يُبدَّل. ثم تُثري العقود
    وجلسات المصادقة كل ماك. انظر docs/router/lessons-learned.md#L16
    العقود لا تُنشئ صفوفاً: عقد جهاز غادر يبقى محجوزاً أياماً، والجدول للحاضرين.
    """
    seen = {}
    for r in mac_rows:
        if r["vid"] == str(vid):
            seen[r["mac"]] = r["port"]
    live = {}
    for mac, a in arp.items():
        # مدخل الواجهة نفسها (TYPE = I) هو عنوان البوّابة لا جهاز متصل
        if (a.get("type") or "").startswith("I"):
            continue
        live[mac] = a
        seen.setdefault(mac, a.get("iface", ""))
    # عقدٌ بلا أثر حيّ = عنوان محجوز لجهاز غائب. يُعرض ليُعرف أنه يستهلك
    # من المجمَّع دون أن يكون أحد هنا.
    for mac in leases:
        seen.setdefault(mac, "")

    rows = []
    for mac, port in seen.items():
        lease = leases.get(mac) or {}
        ip = (arp.get(mac) or {}).get("ip") or lease.get("ip") or ""
        presence = "active" if mac in live else ("seen" if port else "lease")
        if lease.get("status", "").lower().startswith("static"):
            kind = "bind"
        elif lease:
            kind = "dhcp"
        elif ip:
            kind = "static"
        else:
            kind = "none"
        rows.append({"mac": mac, "ip": ip, "port": port, "kind": kind,
                     "presence": presence, "random": mac_is_random(mac),
                     "left": lease.get("left", ""),
                     "auth": (online.get(mac) or {}).get("status", "")})
    rows.sort(key=lambda r: (_ip_int(r["ip"]) if r["ip"] else 1 << 32, r["mac"]))
    return rows


def overlap_report(scans, tight=0.1):
    """
    يقارن عقود كل الشبكات ببعضها. عقدان لماك واحد في شبكتين يعنيان أن الجهاز
    وصل الشبكتين معاً: إمّا انتقل بينهما، وإمّا — وهو الأهمّ — تصله إحداهما
    غير موسومة عبر وصلة تبديل فيأخذ منها عنواناً وهو ليس من أهلها
    (docs/router/lessons-learned.md#L16).
    يعيد {"dups": {ماك: [{"vid","ip"}...]}, "tight": [{"vid","idle","usable"}...]}
    """
    where = {}
    for s in scans:
        for mac, lease in (s.get("leases") or {}).items():
            where.setdefault(mac, []).append({"vid": s["vid"], "ip": lease.get("ip", "")})
    dups = {}
    for mac, seen in where.items():
        if len({e["vid"] for e in seen}) > 1:
            dups[mac] = sorted(seen, key=lambda e: int(e["vid"]))
    low = []
    for s in scans:
        p = s.get("pool") or {}
        # المتاح الحقيقي هو الكلّي ناقص المستبعَد بـ excluded-ip-address
        usable = (p.get("total") or 0) - (p.get("disabled") or 0)
        idle = p.get("idle")
        if idle is None or usable <= 0:
            continue
        if idle <= usable * tight:
            low.append({"vid": s["vid"], "idle": idle, "usable": usable})
    low.sort(key=lambda e: int(e["vid"]))
    return {"dups": dups, "tight": low}


def vlanif_networks(brief):
    """شبكات الـVlanif من display ip interface brief: [{"iface", "vid", "ip", "len"}]."""
    nets = []
    for row in brief:
        m = re.match(r"^Vlanif(\d+)$", row["iface"])
        if m:
            nets.append(dict(row, vid=m.group(1)))
    return nets


def subnet_bounds(ip, length):
    """(عنوان الشبكة، عنوان البث) كأعداد."""
    mask = (0xffffffff << (32 - length)) & 0xffffffff if length else 0
    net = _ip_int(ip) & mask
    return net, net | (~mask & 0xffffffff)


def _int_ip(n):
    return "%d.%d.%d.%d" % ((n >> 24) & 255, (n >> 16) & 255, (n >> 8) & 255, n & 255)


def mgmt_free_ip(net, taken):
    """أعلى عنوان متاح في الشبكة — بعيداً عن العناوين التي يوزعها DHCP من أولها."""
    lo, hi = subnet_bounds(net["ip"], net["len"])
    for n in range(hi - 1, max(lo, hi - 4096), -1):
        ip = _int_ip(n)
        if ip not in taken:
            return ip
    return ""


def plan_mgmt_device(st, mac12, iface, ip, acl_no, trusted):
    """
    يتحقق من اختيارات المستخدم ويعيد (خطة، أخطاء، تحذيرات).
    لا يتصل بالراوتر: st صورة قُرئت مسبقاً، فيُختبر بلا جهاز.
    كل خطأ (مفتاح نص، معاملات) كي تعرضه الواجهة بلغتها.
    """
    errors, warns = [], []
    net = next((n for n in st["networks"] if n["iface"] == iface), None)
    if net is None:
        return None, [("mgmt_err_net", {"net": iface})], warns
    acl = st["acls"].get(acl_no)
    if acl is None:
        errors.append(("mgmt_err_acl", {"acl": acl_no}))

    router_ips = set(n["ip"] for n in st["networks"])
    pool = st.get("pool") or {"used": {}}
    binds = st["binds"]
    arp_static = st["arp_static"]
    taken = set(router_ips) | set(pool["used"]) | set(b["ip"] for b in binds) | set(arp_static)
    if not ip:
        ip = mgmt_free_ip(net, taken)
        if not ip:
            errors.append(("mgmt_err_no_free", {"net": iface}))
    if ip:
        lo, hi = subnet_bounds(net["ip"], net["len"])
        if not valid_ip(ip):
            errors.append(("mgmt_err_ip_format", {"ip": ip}))
        elif not (lo < _ip_int(ip) < hi):
            errors.append(("mgmt_err_ip_subnet", {"ip": ip, "net": "%s/%d" % (net["ip"], net["len"])}))
        elif ip in router_ips:
            errors.append(("mgmt_err_ip_router", {"ip": ip}))
        else:
            holder = pool["used"].get(ip)
            if holder and holder != mac12:
                errors.append(("mgmt_err_ip_leased", {"ip": ip, "mac": mac_pretty(holder)}))
            for b in binds:
                if b["ip"] == ip and b["mac"] != mac12:
                    errors.append(("mgmt_err_ip_bound", {"ip": ip, "mac": mac_pretty(b["mac"])}))
                if b["mac"] == mac12 and b["ip"] != ip:
                    errors.append(("mgmt_err_mac_bound", {"ip": b["ip"]}))
            if ip in arp_static:
                errors.append(("mgmt_err_ip_arp", {"ip": ip, "mac": mac_pretty(arp_static[ip]["mac"])}))
            if acl is not None and acl_host_rule(acl, ip) is not None:
                errors.append(("mgmt_err_rule_exists", {"ip": ip, "acl": acl_no,
                                                         "rule": acl_host_rule(acl, ip)}))

    port = ""
    dyn = st.get("arp_dynamic", {}).get(mac12)
    if dyn and dyn.get("iface"):
        port = dyn["iface"]
    elif len(st.get("vlan_ports") or []) == 1:
        port = st["vlan_ports"][0]
    else:
        errors.append(("mgmt_err_port", {"net": iface}))

    rule_id = acl_free_rule_id(acl) if acl is not None else None
    if acl is not None and rule_id is None:
        errors.append(("mgmt_err_rule_id", {"acl": acl_no}))

    if st.get("nac", {}).get(iface) and not trusted:
        errors.append(("mgmt_err_untrusted", {"net": iface}))

    # الإدارة هنا SSH وحده. لا نلمس الويب أبداً: http acl يطبّقه الراوتر على خادم
    # البوابة المدمج أيضاً، فيحرم كل جهاز خارج القائمة من صفحة الدخول.
    b = st["bindings"]
    if acl is not None and acl_no not in b["vty"]:
        errors.append(("mgmt_warn_not_vty", {"acl": acl_no, "vty": ", ".join(sorted(b["vty"])) or "—"}))

    # الراوتر يرفض ربط ماك له عقد DHCP على عنوان آخر:
    #   Error: This MAC address uses another IP address in the ip pool.
    # فنحرر ذلك العقد قبل الربط. الجهاز يبقى على عنوانه القديم حتى يجدد،
    # فيرفض الراوتر التجديد ويعطيه العنوان المربوط.
    release = next((lip for lip, lmac in sorted(pool["used"].items())
                    if lmac == mac12 and lip != ip), "")
    old_ip = release or (dyn or {}).get("ip", "")
    if old_ip and old_ip != ip:
        warns.append(("mgmt_warn_reconnect", {"old": old_ip, "ip": ip}))

    if errors:
        return None, errors, warns
    plan = {"mac": mac12, "iface": iface, "vid": net["vid"], "ip": ip, "acl": acl_no,
            "release": release,
            "rule": rule_id, "port": port}
    return plan, errors, warns


def mgmt_description(name):
    """وصف ربط DHCP: حروف لاتينية وأرقام فقط، فالاسم العربي لا يُرسل إلى الراوتر."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", name or "").strip("-")[:30]


def mgmt_steps(plan, desc=""):
    """
    خطوات التنفيذ بالترتيب، ولكل خطوة أوامرها وأوامر التراجع عنها.
    الإذن في ACL آخر شيء: لا يُفتح باب الإدارة قبل أن يثبت العنوان للماك.
    """
    ip, mac = plan["ip"], mac_dashed(plan["mac"])
    bind = "dhcp server static-bind ip-address %s mac-address %s" % (ip, mac)
    steps = []
    if plan.get("release"):
        # في وضع المستخدم؛ لا تراجع عنه — الجهاز يطلب عنواناً من جديد فقط
        steps.append({"key": "release", "view": "user",
                      "do": ["reset ip pool interface %s %s" % (plan["iface"], plan["release"])],
                      "undo": []})
    steps += [
        {"key": "bind",
         "do": ["interface %s" % plan["iface"], bind + (" description %s" % desc if desc else ""), "quit"],
         # الجهاز يرفض الماك في صيغة الحذف: Error:Too many parameters
         "undo": ["interface %s" % plan["iface"],
                  "undo dhcp server static-bind ip-address %s" % ip, "quit"]},
        {"key": "arp",
         "do": ["arp static %s %s vid %s interface %s" % (ip, mac, plan["vid"], plan["port"])],
         "undo": ["undo arp static %s" % ip]},
        {"key": "acl",
         "do": ["acl number %s" % plan["acl"], "rule %d permit source %s 0" % (plan["rule"], ip), "quit"],
         "undo": ["acl number %s" % plan["acl"], "undo rule %d" % plan["rule"], "quit"]},
    ]
    return steps


def mgmt_entries(st):
    """
    صفوف جدول أجهزة الإدارة: كل عنوان له ربط ثابت أو ARP ثابت أو قاعدة
    مضيف في قائمة مربوطة بالإدارة. يجمعها بالعنوان كي يظهر الجهاز الناقص
    (خطوة حُذفت يدوياً مثلاً) لا المكتمل وحده.
    """
    rows = {}

    def row(ip):
        if ip not in rows:
            net = next((n for n in st["networks"]
                        if ip_in_subnet(ip, n["ip"], n["len"])), None)
            rows[ip] = {"ip": ip, "mac": "", "iface": net["iface"] if net else "",
                        "bind": False, "arp": False, "rules": [], "desc": ""}
        return rows[ip]

    for b in st["binds"]:
        r = row(b["ip"])
        r["bind"], r["mac"], r["desc"] = True, b["mac"], b["desc"]
    for ip, a in st["arp_static"].items():
        r = row(ip)
        r["arp"] = True
        r["mac"] = r["mac"] or a["mac"]
        r["arp_mac"] = a["mac"]
    mgmt_acls = set(st["bindings"]["vty"])
    if st["bindings"]["http"]:
        mgmt_acls.add(st["bindings"]["http"])
    for no in sorted(mgmt_acls):
        for rule in st["acls"].get(no, {}).get("rules", []):
            if rule["action"] == "permit" and rule["wild"] in ("0", "0.0.0.0") and rule["src"]:
                row(rule["src"])["rules"].append((no, rule["id"]))
    for r in rows.values():
        r["complete"] = bool(r["bind"] and r["arp"] and r["rules"]
                             and r.get("arp_mac", r["mac"]) == r["mac"])
    return [rows[ip] for ip in sorted(rows, key=_ip_int)]


# ----------------------------------------------------------------------------
# قاعدة البيانات المحلية — أسماء وصفية وسجل
# ----------------------------------------------------------------------------

FIREBASE_LOCAL_KEYS = set(("firebase_api_key", "firebase_project_id",
                           "firebase_email", "firebase_password",
                           "firebase_service_account_file", "firebase_last_sync",
                           "firebase_pending_sync"))


class FirebaseSync(object):
    """مخزن Firestore اختياري، يبقي ملف JSON المحلي هو النسخة العاملة دائماً."""

    COLLECTION = "ar730_manager"
    DOCUMENT = "shared_state"

    def __init__(self, settings):
        self.settings = settings
        self._service_account_data = None

    def configured(self):
        if self.settings.get("firebase_service_account_file"):
            try:
                self._service_account()
                return True
            except RuntimeError:
                return False
        return all(str(self.settings.get(k, "")).strip() for k in
                   ("firebase_api_key", "firebase_project_id", "firebase_email",
                    "firebase_password"))

    def _service_account(self):
        """يقرأ اعتماد الخدمة محلياً فقط ويتحقق من أقل الحقول اللازمة."""
        if self._service_account_data is not None:
            return self._service_account_data
        path = self.settings.get("firebase_service_account_file", "")
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            raise RuntimeError("تعذر قراءة ملف بيانات اعتماد Firebase.")
        required = ("project_id", "client_email", "private_key", "token_uri")
        if data.get("type") != "service_account" or not all(data.get(key) for key in required):
            raise RuntimeError("ملف Firebase ليس بيانات اعتماد service account صالحة.")
        self._service_account_data = data
        return data

    @staticmethod
    def _field(value):
        if value is None:
            return {"nullValue": None}
        if isinstance(value, bool):
            return {"booleanValue": value}
        if isinstance(value, int):
            return {"integerValue": str(value)}
        if isinstance(value, float):
            return {"doubleValue": value}
        if isinstance(value, str):
            return {"stringValue": value}
        if isinstance(value, list):
            return {"arrayValue": {"values": [FirebaseSync._field(v) for v in value]}}
        if isinstance(value, dict):
            return {"mapValue": {"fields": {str(k): FirebaseSync._field(v)
                                                 for k, v in value.items()}}}
        return {"stringValue": str(value)}

    @staticmethod
    def _value(field):
        if "nullValue" in field:
            return None
        if "booleanValue" in field:
            return field["booleanValue"]
        if "integerValue" in field:
            return int(field["integerValue"])
        if "doubleValue" in field:
            return field["doubleValue"]
        if "stringValue" in field:
            return field["stringValue"]
        if "arrayValue" in field:
            return [FirebaseSync._value(v) for v in field["arrayValue"].get("values", [])]
        if "mapValue" in field:
            return {k: FirebaseSync._value(v)
                    for k, v in field["mapValue"].get("fields", {}).items()}
        return None

    def _request(self, url, method="GET", payload=None, token=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as exc:
            raise RuntimeError("Firebase: %s" % exc)

    def _form_request(self, url, payload):
        body = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/x-www-form-urlencoded"},
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as exc:
            raise RuntimeError("Firebase: %s" % exc)

    @staticmethod
    def _b64url(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    def _service_account_token(self, account):
        """ينشئ JWT قصير العمر ويبدّله برمز OAuth لصلاحية Firestore فقط."""
        if serialization is None:
            raise RuntimeError("مكتبة cryptography مطلوبة لبيانات اعتماد Firebase.")
        now = int(time.time())
        header = self._b64url(json.dumps({"alg": "RS256", "typ": "JWT"},
                                         separators=(",", ":")).encode("utf-8"))
        claims = self._b64url(json.dumps({
            "iss": account["client_email"],
            "scope": "https://www.googleapis.com/auth/datastore",
            "aud": account["token_uri"], "iat": now, "exp": now + 3600,
        }, separators=(",", ":")).encode("utf-8"))
        signed = (header + "." + claims).encode("ascii")
        try:
            private_key = serialization.load_pem_private_key(
                account["private_key"].encode("utf-8"), password=None)
            signature = private_key.sign(signed, padding.PKCS1v15(), hashes.SHA256())
        except (TypeError, ValueError):
            raise RuntimeError("تعذر استخدام المفتاح الخاص لبيانات اعتماد Firebase.")
        reply = self._form_request(account["token_uri"], {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": signed.decode("ascii") + "." + self._b64url(signature),
        })
        token = reply.get("access_token")
        if not token:
            raise RuntimeError("لم تُرجع Firebase رمز وصول صالحاً.")
        return token

    def _token(self):
        if self.settings.get("firebase_service_account_file"):
            return self._service_account_token(self._service_account())
        key = urllib.parse.quote(self.settings["firebase_api_key"], safe="")
        return self._request("https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=" + key,
                             method="POST", payload={
                                 "email": self.settings["firebase_email"],
                                 "password": self.settings["firebase_password"],
                                 "returnSecureToken": True})["idToken"]

    def _url(self):
        project_id = self.settings.get("firebase_project_id", "")
        if self.settings.get("firebase_service_account_file"):
            project_id = self._service_account()["project_id"]
        project = urllib.parse.quote(project_id, safe="")
        return ("https://firestore.googleapis.com/v1/projects/%s/databases/(default)/documents/%s/%s"
                % (project, self.COLLECTION, self.DOCUMENT))

    def pull(self):
        """يعيد الحالة أو None حين لا توجد بعد في Firestore."""
        if not self.configured():
            return None
        try:
            doc = self._request(self._url(), token=self._token())
        except RuntimeError as exc:
            if "HTTP Error 404" in str(exc):
                return None
            raise
        fields = doc.get("fields", {})
        state = self._value(fields.get("state", {})) if fields.get("state") else None
        return state if isinstance(state, dict) else None

    def push(self, db_data):
        if not self.configured():
            return None
        # لا تُرفع بيانات دخول Firebase ولا كلمة مرور MAC المشتركة إلى السحابة.
        shared_settings = {k: copy.deepcopy(v) for k, v in self.settings.items()
                           if k not in FIREBASE_LOCAL_KEYS and k != "mac_shared_password"}
        state = {"saved_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                 "settings": shared_settings, "db": copy.deepcopy(db_data)}
        self._request(self._url(), method="PATCH", token=self._token(),
                      payload={"fields": {"state": self._field(state)}})
        return state["saved_at"]

class LocalDB(object):
    def __init__(self, path=None, on_save=None):
        self.path = path or DB_FILE
        self.on_save = on_save
        self.data = {"devices": {}, "portal": {}, "mgmt": {}, "names": {}, "history": []}
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                for k in ("devices", "portal", "mgmt", "names", "history"):
                    if k in loaded:
                        self.data[k] = loaded[k]
            except Exception:
                pass

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)
        if self.on_save:
            self.on_save()

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

    def name_of(self, mac12):
        """
        الاسم الذي نعرفه لهذا الماك. سجلّ الأجهزة الموثوقة أولى لأنه الأدقّ،
        ثم مخزن الأسماء الحرّ الذي يسمّي جهازاً رأيناه في الشبكة بلا توثيق.
        """
        dev = self.data["devices"].get(mac12) or {}
        if dev.get("name"):
            return dev["name"]
        return (self.data["names"].get(mac12) or {}).get("name", "")

    def note_of(self, mac12):
        dev = self.data["devices"].get(mac12) or {}
        return dev.get("note") or (self.data["names"].get(mac12) or {}).get("note", "")

    def set_name(self, mac12, name, note=""):
        """
        تسمية جهاز رأيناه في الشبكة. لا تلمس الراوتر ولا تجعله موثوقاً؛
        اسم فارغ يحذف السجل كي لا يتضخّم الملف بأسماء ألغاها المستخدم.
        """
        if mac12 in self.data["devices"]:
            return self.set_device_meta(mac12, name, note)
        if not name and not note:
            self.data["names"].pop(mac12, None)
        else:
            rec = self.data["names"].setdefault(mac12, {})
            rec["name"] = name
            rec["note"] = note
            rec.setdefault("added", now_stamp())
            rec["seen"] = now_stamp()
        self.save()

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

    # -- أجهزة الإدارة -------------------------------------------------------

    def upsert_mgmt(self, ip, mac12, name, iface, acl):
        self.data["mgmt"][ip] = {"mac": mac12, "name": name, "iface": iface, "acl": acl,
                                 "added": now_stamp()}
        self.save()

    def drop_mgmt(self, ip):
        self.data["mgmt"].pop(ip, None)
        self.save()


# ----------------------------------------------------------------------------
# خدمات العمليات المشتركة بين الواجهات
# ----------------------------------------------------------------------------

class ActionResult(object):
    """نتيجة عملية لا تعتمد على Tkinter أو Qt.

    ``code`` ثابت تستطيع كل واجهة ترجمته بلغتها وعرضه بالشكل المناسب لها،
    فيما تبقى أوامر الراوتر والتحقق منها في موضع واحد.
    """
    def __init__(self, ok, code, users=None, states=None, online=None, data=None, error=""):
        self.ok = ok
        self.code = code
        self.users = users
        self.states = states
        self.online = online
        self.data = data
        self.error = error


class NetworkDeviceNameOperations(object):
    """الأسماء المحلية لأجهزة ظهرت في جدول الشبكات، بلا أثر على الراوتر.

    لا تستخدم ``set_device_meta`` هنا: ذلك ينشئ سجلاً في قائمة الأجهزة الموثوقة
    لجهاز لم نمنحه الثقة. ``set_name`` يحفظ الاسم الحر مقابل MAC فقط، وهو السلوك
    الأصلي لتبويب VLAN.
    """
    def __init__(self, db):
        self.db = db

    def update(self, mac12, name, note):
        mac12 = normalize_mac(mac12)
        if not mac12:
            return ActionResult(False, "bad_mac")
        name, note = (name or "").strip(), (note or "").strip()
        if name == self.db.name_of(mac12) and note == self.db.note_of(mac12):
            return ActionResult(True, "unchanged")
        self.db.set_name(mac12, name, note)
        self.db.log("name_device", mac12, name)
        return ActionResult(True, "updated")


class VlanOverlapOperations(object):
    """فحص مجمّعات VLAN المشترك بين واجهتي Tkinter وQt.

    لا يرسل هذا المسار إلا أوامر ``display ip pool`` الموثقة. وضع المقارنة
    والسجل المحلي هنا كي لا يختلف معنى «فحص التداخل» بين الواجهتين.
    """
    def __init__(self, router, db):
        self.router = router
        self.db = db

    def scan(self, networks):
        if not networks:
            return ActionResult(False, "missing_networks")
        try:
            scans = self.router.scan_pools(networks)
        except Exception as exc:
            return ActionResult(False, "router_error", error=str(exc))
        report = overlap_report(scans)
        self.db.log("scan_overlap", "", "%d/%d" % (len(report["dups"]), len(scans)))
        return ActionResult(True, "scanned", data={"report": report, "scans": scans})


class VlanSessionOperations(object):
    """قطع جلسات عملاء شبكة محددة، مشترك بين واجهتي Tkinter وQt.

    العملية لا تحذف حساب AAA ولا تغير إعداد VLAN. تظل حدودها جلسات access-user
    فقط، وتبقى حماية الشبكة بلا مصادقة في موضع واحد.
    """
    def __init__(self, router, db):
        self.router = router
        self.db = db

    def disconnect(self, vlan_state, macs):
        state = vlan_state or {}
        selected = []
        for mac in macs or []:
            mac12 = normalize_mac(mac)
            if mac12 and mac12 not in selected:
                selected.append(mac12)
        if not selected:
            return ActionResult(False, "missing_selection")
        if not state.get("nac"):
            return ActionResult(False, "no_authentication")
        try:
            replies = self.router.cut_users(selected)
        except Exception as exc:
            return ActionResult(False, "router_error", error=str(exc))
        bad = [mac for mac, reply in replies.items() if first_error(reply)]
        for mac12 in selected:
            self.db.log("cut_user", mac12, state.get("iface", ""))
        code = "disconnected" if not bad else "partial"
        return ActionResult(not bad, code, data={"bad": bad, "replies": replies,
                                                  "selected": selected})


class TrustedDeviceOperations(object):
    """عمليات حسابات MAC/802.1x بلا أي عنصر واجهة.

    هذه أول خدمة انتقالية: تستعملها Tkinter الآن، وستستدعيها Qt عند اكتمال
    حوارها واختبارات تكافؤها. لا تُخفى أخطاء الراوتر ولا يُفترض النجاح قبل
    إعادة قراءة AAA.
    """
    def __init__(self, router, db, router_users, shared_password, autosave):
        self.router = router
        self.db = db
        self.router_users = router_users or {}
        self.shared_password = shared_password
        self.autosave = bool(autosave)

    def create(self, mac12, name, group, note):
        if mac12 in self.router_users:
            return ActionResult(False, "duplicate")
        group = (group or "").strip()
        if not group:
            return ActionResult(False, "missing_group")
        password = (self.shared_password or "").strip()
        if not password or password == MAC_PW_PLACEHOLDER:
            return ActionResult(False, "placeholder_password")
        if password.lower() == mac12:
            return ActionResult(False, "password_is_mac")

        try:
            # موثق على AR730: لا يقبل الحساب كلمة المرور قبل service-type.
            self.router.send_many([
                "system-view",
                "aaa",
                "local-user %s service-type 8021x" % mac12,
                "local-user %s password cipher %s" % (mac12, password),
                "local-user %s user-group %s" % (mac12, group),
                "quit",
                "quit",
            ])
            users = parse_local_users(self.router.read_aaa())
            record = users.get(mac12)
            if not record or "8021x" not in record["service_types"] \
                    or record.get("group") != group:
                return ActionResult(False, "not_confirmed", users=users)
            if self.autosave:
                self.router.save_config()
            states = self.router.read_local_user_states()
        except Exception as exc:
            return ActionResult(False, "router_error", error=str(exc))

        self.db.upsert_device(mac12, name, group, note)
        self.db.log("add_device", mac12, "%s / %s" % (name, group))
        return ActionResult(True, "added", users=users, states=states)

    def update_metadata(self, mac12, name, note):
        """يحدّث الوصف المحلي فقط، حتى لو كان الحساب مُلغى على الراوتر."""
        local = self.db.device(mac12) or {}
        if name == local.get("name", "") and note == local.get("note", ""):
            return ActionResult(True, "unchanged")
        self.db.set_device_meta(mac12, name, note)
        self.db.log("edit_device_meta", mac12, name)
        return ActionResult(True, "updated")

    def change_group(self, mac12, group):
        """يغيّر مجموعة MAC ثم يفصل جلسته لتعيد المصادقة بالصلاحيات الجديدة."""
        group = (group or "").strip()
        if not group:
            return ActionResult(False, "missing_group")
        try:
            # ``cut access-user`` موثق ومقبول في AAA فقط على AR730.
            self.router.send_many([
                "system-view",
                "aaa",
                "local-user %s user-group %s" % (mac12, group),
                "cut access-user mac-address %s" % mac_dashed(mac12),
                "quit",
                "quit",
            ])
            users = parse_local_users(self.router.read_aaa())
            record = users.get(mac12)
            if not record or record.get("group") != group:
                return ActionResult(False, "not_confirmed", users=users)
            if self.autosave:
                self.router.save_config()
        except Exception as exc:
            return ActionResult(False, "router_error", error=str(exc))

        device = self.db.device(mac12)
        if device:
            device["group"] = group
            self.db.save()
        self.db.log("change_group", mac12, group)
        return ActionResult(True, "group_changed", users=users)

    def revoke(self, mac12, reason):
        """يلغي حساب MAC ويثبت اختفاءه قبل أرشفة السجل المحلي."""
        try:
            self.router.send_many([
                "system-view",
                "aaa",
                "undo local-user %s" % mac12,
                "cut access-user mac-address %s" % mac_dashed(mac12),
                "quit",
                "quit",
            ])
            if self.autosave:
                self.router.save_config()
            users = parse_local_users(self.router.read_aaa())
            if mac12 in users:
                return ActionResult(False, "not_confirmed", users=users)
        except Exception as exc:
            return ActionResult(False, "router_error", error=str(exc))

        self.db.revoke_device(mac12, reason)
        self.db.log("revoke_device", mac12, reason)
        return ActionResult(True, "revoked", users=users)


class PortalAccountOperations(object):
    """عمليات حسابات البوابة المشتركة بين Tkinter وQt."""
    def __init__(self, db, router=None, router_users=None, autosave=False):
        self.db = db
        self.router = router
        self.router_users = router_users or {}
        self.autosave = bool(autosave)

    def create(self, username, password, name, group, note):
        username = (username or "").strip()
        group = (group or "").strip()
        if not re.match(r"^[A-Za-z0-9_.\-]{1,64}$", username):
            return ActionResult(False, "bad_username")
        if len(password or "") < 8:
            return ActionResult(False, "short_password")
        if password.lower() in (username.lower(), username.lower()[::-1]):
            return ActionResult(False, "password_is_username")
        if not group:
            return ActionResult(False, "missing_group")
        if username in self.router_users:
            return ActionResult(False, "duplicate")
        try:
            self.router.send_many([
                "system-view",
                "aaa",
                "local-user %s service-type web" % username,
                "local-user %s password cipher %s" % (username, password),
                "local-user %s user-group %s" % (username, group),
                "quit",
                "quit",
            ])
            users = parse_local_users(self.router.read_aaa())
            record = users.get(username)
            if not record or "web" not in record["service_types"] \
                    or record.get("group") != group:
                return ActionResult(False, "not_confirmed", users=users)
            if self.autosave:
                self.router.save_config()
        except Exception as exc:
            return ActionResult(False, "router_error", error=str(exc))

        self.db.upsert_portal(username, name, group, note)
        self.db.log("add_portal", username, "%s / %s" % (name, group))
        return ActionResult(True, "added", users=users)

    def change_password(self, username, password):
        """يغيّر كلمة المرور بنفس أمر AAA الموجود في واجهة Tkinter."""
        username = (username or "").strip()
        if len(password or "") < 8:
            return ActionResult(False, "short_password")
        if password.lower() == username.lower():
            return ActionResult(False, "password_is_username")
        try:
            self.router.send_many([
                "system-view", "aaa",
                "local-user %s password cipher %s" % (username, password),
                "quit", "quit",
            ])
            if self.autosave:
                self.router.save_config()
        except Exception as exc:
            return ActionResult(False, "router_error", error=str(exc))
        # لا تسجل كلمة المرور في LocalDB أو في سجل النشاط.
        self.db.log("reset_password", username, "")
        return ActionResult(True, "password_changed")

    def change_group(self, username, group, portal_domain=""):
        """يغيّر مجموعة حساب البوابة ويفصل جلسته بالتسلسل القديم نفسه."""
        username = (username or "").strip()
        group = (group or "").strip()
        if not group:
            return ActionResult(False, "missing_group")
        try:
            self.router.send_many([
                "system-view", "aaa",
                "local-user %s user-group %s" % (username, group),
            ])
            self._cut_session(username, portal_domain)
            self.router.send_many(["quit", "quit"])
            users = parse_local_users(self.router.read_aaa())
            record = users.get(username)
            if not record or record.get("group") != group:
                return ActionResult(False, "not_confirmed", users=users)
            if self.autosave:
                self.router.save_config()
        except Exception as exc:
            return ActionResult(False, "router_error", error=str(exc))

        portal = self.db.portal(username)
        if portal:
            portal["group"] = group
            self.db.save()
        self.db.log("change_group", username, group)
        return ActionResult(True, "group_changed", users=users)

    def _cut_session(self, username, portal_domain):
        """يفصل الحساب داخل AAA، مع إعادة المحاولة بالاسم المؤهل عند الحاجة."""
        out = self.router.send("cut access-user username %s" % username)
        if re.search(r"Error|Wrong|Invalid|not exist|does not exist", out, re.I):
            domain = (portal_domain or "").strip()
            if domain:
                self.router.send("cut access-user username %s@%s" % (username, domain))

    def revoke(self, username, reason, portal_domain=""):
        """يحذف حساب البوابة ولا يؤرشفه محلياً قبل تأكيد اختفائه من AAA."""
        username = (username or "").strip()
        try:
            self.router.send_many([
                "system-view", "aaa",
                "undo local-user %s" % username,
            ])
            self._cut_session(username, portal_domain)
            self.router.send_many(["quit", "quit"])
            users = parse_local_users(self.router.read_aaa())
            if username in users:
                return ActionResult(False, "not_confirmed", users=users)
            if self.autosave:
                self.router.save_config()
        except Exception as exc:
            return ActionResult(False, "router_error", error=str(exc))

        self.db.revoke_portal(username, reason)
        self.db.log("delete_portal", username, reason)
        return ActionResult(True, "revoked", users=users)

    def update_metadata(self, username, name, note):
        """يحدّث الوصف المحلي فقط، حتى لو لم يعد الحساب موجوداً على الراوتر."""
        local = self.db.portal(username) or {}
        if name == local.get("name", "") and note == local.get("note", ""):
            return ActionResult(True, "unchanged")
        self.db.set_portal_meta(username, name, note)
        self.db.log("edit_portal_meta", username, name)
        return ActionResult(True, "updated")


class OnlineSessionOperations(object):
    """عمليات جلسات access-user المشتركة؛ لا تعدّل حسابات AAA."""
    def __init__(self, router):
        self.router = router

    def disconnect(self, user_id):
        user_id = str(user_id or "").strip()
        if not user_id:
            return ActionResult(False, "missing_session")
        try:
            # تسلسل on_cut_user القديم نفسه؛ cut لا يقبل إلا من عرض AAA.
            self.router.send_many([
                "system-view", "aaa",
                "cut access-user user-id %s" % user_id,
                "quit", "quit",
            ])
            online = parse_online(self.router.read_online())
            if any(row.get("id") == user_id for row in online):
                return ActionResult(False, "not_confirmed", online=online)
        except Exception as exc:
            return ActionResult(False, "router_error", error=str(exc))
        return ActionResult(True, "disconnected", online=online)


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


def write_utf8_csv(path, headers, rows):
    """يكتب CSV متوافقاً مع Excel ويحافظ على النص العربي."""
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)


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

        first_editable = next((i for i, f in enumerate(fields)
                               if f.get("kind") != "readonly"), 0)
        for r, f in enumerate(fields):
            key, label, kind = f["key"], f["label"], f.get("kind", "text")
            ttk.Label(frm, text=label, style="Card.TLabel", justify=justify).grid(
                row=r, column=c_lab, sticky=s_lab, padx=pad_lab, pady=8)
            var = tk.StringVar(value=f.get("default", ""))
            if kind == "combo":
                w = ttk.Combobox(frm, textvariable=var, values=f.get("values", []),
                                 width=32, state="readonly", justify=justify)
            elif kind == "readonly":
                w = ttk.Entry(frm, textvariable=var, width=34, state="readonly",
                              justify=justify)
            elif kind == "password":
                w = ttk.Entry(frm, textvariable=var, width=34, show="•", justify=justify)
            else:
                w = ttk.Entry(frm, textvariable=var, width=34, justify=justify)
            w.grid(row=r, column=c_fld, sticky=s_fld, pady=8)
            self._vars[key] = var
            if r == first_editable:
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
        make_text_readonly(self.txt)

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
        self.firebase = FirebaseSync(self.settings)
        self._firebase_state = None
        if self.firebase.configured():
            try:
                self._firebase_state = self.firebase.pull()
                if self._firebase_state:
                    remote_settings = self._firebase_state.get("settings", {})
                    if isinstance(remote_settings, dict):
                        self.settings.update(remote_settings)
            except Exception:
                # التطبيق لا يتوقف إن كان الإنترنت أو Firebase غير متاحين.
                self.settings["firebase_pending_sync"] = True
        self.lang = self.settings.get("ui_lang", "ar")
        self.T = TXT.get(self.lang, TXT["ar"])

        self.title("%s  v%s" % (self.T["title"], APP_VERSION))
        # المقاس يُحسب بعد البناء في _fit_window — الشريط العلوي هو الذي
        # يفرض أدنى عرض، وعدد حقوله يتغيّر بتغيّر اللغة والإصدار

        self.db = LocalDB(on_save=self._on_db_saved)
        if self._firebase_state and isinstance(self._firebase_state.get("db"), dict):
            self.db.data = self._firebase_state["db"]
            saved = self.db.on_save
            self.db.on_save = None
            self.db.save()
            self.db.on_save = saved
            self.settings["firebase_last_sync"] = self._firebase_state.get("saved_at", "")
            save_settings(self.settings)
        self.demo_mode = False
        self._busy = False
        # سجل الأوامر يُملأ من الخيط الجانبي، وTk لا تحتمل ذلك.
        # فنصفّ النص هنا ولا نكتبه في الويدجت إلا من الخيط الرئيسي.
        self._log_queue = []
        self._log_lock = threading.Lock()
        self.router = UiRouter(self, RouterSession(log_fn=self._log))
        self.router_users = {}
        self.router_groups = {}
        self.router_states = {}
        self.online_rows = []
        self._busy = False
        # نداء في الخلفية (المراقبة التلقائية) لا يفتح نافذة الانتظار كل دقيقة
        self._quiet = False
        self.wan_lines = []
        self.mgmt_state = None
        self.mgmt_rows = []
        self.vlans = []
        self.vlan_state = None
        self.vlan_vid = ""
        self._vlan_warn = ""
        self._wan_after = None
        self._wan_streak = {}
        self._wan_bw_streak = {}       # تتابع قرارات السعة وحدها، فهي تُقاس أندر
        self.settings["withdrawn_lines"] = dict(self.settings.get("withdrawn_lines") or {})

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
        self._firebase_after = self.after(60000, self._firebase_poll)
        # Network I/O stays off the GUI thread. Failure (including offline use)
        # is silent and must never delay opening the management interface.
        self.after(1500, self._start_update_check)

    # -- تحديث التطبيق ------------------------------------------------------

    def _start_update_check(self):
        def worker():
            update = check_for_update(APP_VERSION)
            if update:
                self.after(0, lambda: self._show_update_available(update))
        threading.Thread(target=worker, name="ar730-update-check", daemon=True).start()

    def _show_update_available(self, update):
        if self.lang == "ar":
            message = ("يتوفر إصدار جديد: %s\nالإصدار المثبت: %s\n\n"
                       "يحتوي الإصدار على ملف مناسب لجهازك. يتحقق مُثبّت الأمر "
                       "الواحد من SHA-256 قبل التثبيت، وبياناتك المحلية تبقى "
                       "خارج مجلد التطبيق." % (update["version"], APP_VERSION))
            question = "هل تريد فتح صفحة التنزيل الآن؟"
        else:
            message = ("Version %s is available (installed: %s).\n\n"
                       "The release includes the correct installer for this computer. "
                       "The one-command installer verifies SHA-256 before installing, "
                       "and local data stays outside the app folder."
                       % (update["version"], APP_VERSION))
            question = "Open the download page now?"
        if messagebox.askyesno("AR730 Manager update", message + "\n\n" + question, parent=self):
            webbrowser.open(update["release_url"])

    # -- مزامنة Firebase ----------------------------------------------------

    def _save_settings(self):
        save_settings(self.settings)
        self._sync_firebase(quiet=True)

    def _on_db_saved(self):
        self._sync_firebase(quiet=True)

    def _sync_firebase(self, quiet=False):
        if not self.firebase.configured():
            return False

    def _apply_firebase_state(self, state):
        """يكتب الحالة المشتركة محلياً دون إعادة رفعها فوراً."""
        remote_settings = state.get("settings", {})
        if isinstance(remote_settings, dict):
            self.settings.update(remote_settings)
        if isinstance(state.get("db"), dict):
            saved = self.db.on_save
            self.db.on_save = None
            self.db.data = state["db"]
            self.db.save()
            self.db.on_save = saved
        self.settings["firebase_last_sync"] = state.get("saved_at", "")
        self.settings["firebase_pending_sync"] = False
        save_settings(self.settings)
        self._refresh_device_table()
        self._refresh_portal_table()

    def _firebase_first_sync(self):
        """جهاز جديد يجلب النسخة السحابية قبل أن يفكر في رفع ملفه الفارغ."""
        try:
            state = self.firebase.pull()
            if state:
                self._apply_firebase_state(state)
                self._status(self.T["firebase_ok"])
                return True
        except Exception:
            pass
        return self._sync_firebase(quiet=False)
        try:
            self.settings["firebase_last_sync"] = self.firebase.push(self.db.data)
            self.settings["firebase_pending_sync"] = False
            save_settings(self.settings)
            if not quiet:
                self._status(self.T["firebase_ok"])
            return True
        except Exception:
            self.settings["firebase_pending_sync"] = True
            save_settings(self.settings)
            if not quiet:
                self._status(self.T["firebase_offline"], ok=False)
            return False

    def _firebase_poll(self):
        try:
            if self.firebase.configured():
                # إن وُجد تعديل لم يصل بعد، تكون الأولوية لنسختنا المحلية.
                if self.settings.get("firebase_pending_sync"):
                    self._sync_firebase(quiet=True)
                else:
                    state = self.firebase.pull()
                    if state and state.get("saved_at", "") > self.settings.get("firebase_last_sync", ""):
                        self._apply_firebase_state(state)
        except Exception:
            pass
        self._firebase_after = self.after(60000, self._firebase_poll)

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

        builders = [self._tab_devices, self._tab_portal, self._tab_online, self._tab_vlans,
                    self._tab_mgmt, self._tab_wan, self._tab_groups, self._tab_settings, self._tab_log]
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
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _on_tab_changed(self, _ev=None):
        """تبويب الشبكات يقرأ قائمته عند أول فتح فقط — كي لا يبطئ الاتصال."""
        try:
            cur = self.nb.nametowidget(self.nb.select())
        except Exception:
            return
        if cur is getattr(self, "_vlan_tab", None) and not self.vlans \
                and self.router.connected:
            self.on_refresh_vlans()

    # ---- تبويب الأجهزة الموثوقة -------------------------------------------

    def _make_tree(self, parent, cols, heads, widths, height=None, multi=False):
        """
        جدول بمظهر موحّد. في العربية نعكس ترتيب العرض عبر displaycolumns
        لا عبر قلب الأعمدة نفسها — فتبقى قيم الصفوف على ترتيبها المنطقي
        ولا يحتاج أي نداء insert إلى تغيير.
        """
        wrap = ttk.Frame(parent, style="Card.TFrame")
        wrap.pack(fill="both", expand=True)

        kw = {"columns": cols, "show": "headings",
              "selectmode": "extended" if multi else "browse"}
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
        tv.tag_configure("blocked", foreground=C["danger"])
        self._enable_copy(tv, cols)
        return tv

    # -- النسخ من الجداول ----------------------------------------------------

    def _enable_copy(self, tv, cols):
        """
        Treeview لا يسمح بتحرير الخلايا أصلاً، لكنه لا يسمح بتحديد نصها
        أيضاً. فنقدّم النسخ بطريقتين: قائمة بالزر الأيمن للخلية أو الصف،
        واختصار النسخ المعتاد للصف المحدَّد.
        """
        tv._copy_cols = tuple(cols)
        menu_events = ["<Button-3>"]
        copy_keys = ["<Control-c>", "<Control-C>"]
        if sys.platform == "darwin":
            # زر الفأرة الأيمن في Tk على macOS هو Button-2، وCtrl+نقرة مثله
            menu_events += ["<Button-2>", "<Control-Button-1>"]
            copy_keys += ["<Command-c>", "<Command-C>"]
        for seq in menu_events:
            tv.bind(seq, lambda e, t=tv: self._tree_menu(t, e), add="+")
        for seq in copy_keys:
            tv.bind(seq, lambda e, t=tv: (self._copy_rows(t), "break")[1], add="+")

    def _tree_cell(self, tv, event):
        """يعيد (معرّف الصف، اسم العمود) تحت المؤشر، مع مراعاة عكس الأعمدة."""
        iid = tv.identify_row(event.y)
        col_ref = tv.identify_column(event.x)            # "#1" بترتيب العرض
        shown = tv.cget("displaycolumns")
        if isinstance(shown, str):
            shown = shown.split()
        shown = tuple(shown or ())
        if not shown or shown == ("#all",):
            shown = tv._copy_cols
        try:
            col = shown[int(col_ref.lstrip("#")) - 1]
        except (ValueError, IndexError):
            col = None
        return iid, col

    def _tree_menu(self, tv, event):
        iid, col = self._tree_cell(tv, event)
        if not iid:
            return
        tv.selection_set(iid)
        tv.focus(iid)
        values = [str(v) for v in tv.item(iid, "values")]
        cols = tv._copy_cols

        menu = tk.Menu(self, tearoff=0)
        actions = getattr(tv, "_menu_actions", [])
        for label, command in actions:
            menu.add_command(label=label, command=command)
        if actions:
            menu.add_separator()
        if col in cols:
            value = values[cols.index(col)] if cols.index(col) < len(values) else ""
            if value:
                short = value if len(value) <= 40 else value[:39] + "…"
                menu.add_command(label=self.T["copy_cell"] % short,
                                 command=lambda v=value: self._copy_text(v))
                mac12 = normalize_mac(value) if col == "mac" else None
                if mac12:
                    # صيغة الأوامر على الراوتر: local-user و cut access-user
                    for plain in (mac12, mac_dashed(mac12)):
                        menu.add_command(label=self.T["copy_mac_plain"] % plain,
                                         command=lambda v=plain: self._copy_text(v))
        menu.add_command(label=self.T["copy_row"],
                         command=lambda: self._copy_text("\t".join(values)))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _copy_rows(self, tv):
        rows = ["\t".join(str(v) for v in tv.item(i, "values")) for i in tv.selection()]
        if rows:
            self._copy_text("\n".join(rows))

    def _copy_text(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)
        # على بعض الأنظمة تضيع الحافظة إن لم تُعالج الأحداث قبل مغادرة النافذة
        self.update_idletasks()
        first = text.split("\n")[0]
        self._status(self.T["copied"] % (first if len(first) <= 60 else first[:59] + "…"))

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
        ttk.Button(bar, text=self.T["add_online"],
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
        self.tv_on.bind("<Double-1>", lambda e: self.on_trust_online())
        self.tv_on._menu_actions = [(self.T["add_online"], self.on_trust_online)]

    # ---- تبويب المتّصلين حسب الشبكة -----------------------------------------

    def _tab_vlans(self):
        f = self._tab_frame(self.T["tab_vlans"])
        self._vlan_tab = f

        lbl_hint = ttk.Label(f, text=self.T["vlan_hint"], style="Card.TLabel",
                             justify=self._justify())
        lbl_hint.pack(anchor=self._anchor(), fill="x", pady=(0, 10))
        self._wrap(lbl_hint, f)

        bar = ttk.Frame(f, style="Card.TFrame")
        bar.pack(fill="x", pady=(0, 8))
        p = self._side()
        q = self._side(False)
        ttk.Label(bar, text=self.T["vlan_pick"], style="Card.TLabel").pack(side=p, padx=(0, 6))
        self.v_vlan = tk.StringVar(value="")
        self.cb_vlan = ttk.Combobox(bar, textvariable=self.v_vlan, state="readonly",
                                    width=26, values=[])
        self.cb_vlan.pack(side=p)
        self.cb_vlan.bind("<<ComboboxSelected>>", lambda e: self.on_pick_vlan())
        ttk.Button(bar, text=self.T["refresh"], style="Accent.TButton",
                   command=self.on_refresh_vlans).pack(side=p, padx=6)
        ttk.Button(bar, text=self.T["vlan_name_dev"],
                   command=self.on_name_vlan_device).pack(side=p)
        ttk.Button(bar, text=self.T["vlan_cut"], style="Danger.TButton",
                   command=self.on_cut_vlan_devices).pack(side=p, padx=6)
        ttk.Button(bar, text=self.T["vlan_scan"],
                   command=self.on_scan_overlap).pack(side=p)
        ttk.Button(bar, text=self.T["export"],
                   command=lambda: self.on_export("vlans")).pack(side=q)

        self.lbl_vlan_sum = ttk.Label(f, text="", style="Muted.TLabel",
                                      background=C["surface"], justify=self._justify())
        self.lbl_vlan_sum.pack(anchor=self._anchor(), fill="x", pady=(0, 10))
        self._wrap(self.lbl_vlan_sum, f)

        self.v_find_vlan = tk.StringVar(value="")
        self.lbl_count_vlan = self._search_bar(f, self.v_find_vlan, self._refresh_vlan_table)

        self.tv_vlan = self._make_tree(
            f, ("ip", "mac", "name", "vendor", "port", "kind", "presence", "auth", "other"),
            [self.T["col_ip"], self.T["col_mac"], self.T["col_name"], self.T["col_vendor"],
             self.T["col_port"], self.T["col_addr_kind"], self.T["col_presence"],
             self.T["col_auth"], self.T["col_other_nets"]],
            [120, 150, 170, 130, 160, 100, 130, 120, 150], multi=True)
        self.tv_vlan.tag_configure("ok", foreground=C["ok"])
        self.tv_vlan.tag_configure("bad", foreground=C["danger"])
        self.tv_vlan.tag_configure("muted", foreground=C["muted"])
        # نقرتان على خانة العنوان تفتحه في المتصفح، وعلى غيرها تسمّي الجهاز
        self.tv_vlan.bind("<Double-1>", self._on_vlan_dclick)
        self.tv_vlan._menu_actions = [(self.T["vlan_name_dev"], self.on_name_vlan_device),
                                      (self.T["vlan_cut"], self.on_cut_vlan_devices),
                                      (self.T["vlan_scan"], self.on_scan_overlap)]

    # ---- تبويب أجهزة الإدارة -----------------------------------------------

    def _tab_mgmt(self):
        f = self._tab_frame(self.T["tab_mgmt"])

        lbl_hint = ttk.Label(f, text=self.T["mgmt_hint"], style="Card.TLabel",
                             justify=self._justify())
        lbl_hint.pack(anchor=self._anchor(), fill="x", pady=(0, 10))
        self._wrap(lbl_hint, f)

        bar = ttk.Frame(f, style="Card.TFrame")
        bar.pack(fill="x", pady=(0, 8))
        p = self._side()
        q = self._side(False)
        ttk.Button(bar, text=self.T["mgmt_add"], style="Accent.TButton",
                   command=self.on_add_mgmt).pack(side=p)
        ttk.Button(bar, text=self.T["mgmt_remove"], style="Danger.TButton",
                   command=self.on_remove_mgmt).pack(side=p, padx=6)
        ttk.Button(bar, text=self.T["refresh"], command=self.on_refresh_mgmt).pack(side=q)

        self.lbl_mgmt_access = ttk.Label(f, text="", style="Muted.TLabel",
                                         background=C["surface"], justify=self._justify())
        self.lbl_mgmt_access.pack(anchor=self._anchor(), fill="x", pady=(0, 10))
        self._wrap(self.lbl_mgmt_access, f)

        self.tv_mgmt = self._make_tree(
            f, ("ip", "mac", "name", "net", "rule", "dhcp", "arp", "online", "state"),
            [self.T["col_ip"], self.T["col_mac"], self.T["col_name"], self.T["col_net"],
             self.T["col_rule"], self.T["col_dhcp"], self.T["col_arp"],
             self.T["col_status"], self.T["col_state"]],
            [110, 150, 170, 90, 110, 80, 80, 200, 100])
        self.tv_mgmt.tag_configure("ok", foreground=C["ok"])
        self.tv_mgmt._menu_actions = [(self.T["mgmt_remove"], self.on_remove_mgmt)]

    # ---- تبويب خطوط الإنترنت -----------------------------------------------

    def _tab_wan(self):
        f = self._tab_frame(self.T["tab_wan"])

        lbl_hint = ttk.Label(f, text=self.T["wan_hint"], style="Card.TLabel",
                             justify=self._justify())
        lbl_hint.pack(anchor=self._anchor(), fill="x", pady=(0, 10))
        self._wrap(lbl_hint, f)

        bar = ttk.Frame(f, style="Card.TFrame")
        bar.pack(fill="x", pady=(0, 8))
        p = self._side()
        q = self._side(False)
        ttk.Button(bar, text=self.T["wan_check"], style="Accent.TButton",
                   command=self.on_check_lines).pack(side=p)
        ttk.Button(bar, text=self.T["wan_withdraw"], style="Danger.TButton",
                   command=self.on_withdraw_line).pack(side=p, padx=6)
        ttk.Button(bar, text=self.T["wan_restore"],
                   command=self.on_restore_line).pack(side=p)
        ttk.Button(bar, text=self.T["wan_copy"],
                   command=self.on_copy_wan_report).pack(side=q)

        auto = ttk.Frame(f, style="Card.TFrame")
        auto.pack(fill="x", pady=(0, 10))
        self.v_wan_auto = tk.BooleanVar(value=bool(self.settings.get("wan_auto")))
        self.v_wan_auto_withdraw = tk.BooleanVar(
            value=bool(self.settings.get("wan_auto_withdraw")))
        ttk.Checkbutton(auto, text=self.T["wan_auto"], variable=self.v_wan_auto,
                        command=self._on_wan_auto_toggle).pack(side=p)
        ttk.Checkbutton(auto, text=self.T["wan_auto_withdraw"],
                        variable=self.v_wan_auto_withdraw,
                        command=self._on_wan_auto_toggle).pack(side=p, padx=12)
        self.lbl_wan_last = ttk.Label(auto, text="", style="Muted.TLabel",
                                      background=C["surface"])
        self.lbl_wan_last.pack(side=q)

        self.tv_wan = self._make_tree(
            f, ("line", "iface", "gw", "route", "icmp", "https", "rtt", "port", "verdict"),
            [self.T["col_line"], self.T["col_iface"], self.T["col_gw"], self.T["col_route"],
             self.T["col_icmp"], self.T["col_https"], self.T["col_rtt"], self.T["col_bw"],
             self.T["col_port"], self.T["col_verdict"]],
            [70, 190, 100, 140, 70, 70, 100, 170, 170], height=5)
        # الجدول بعدد صفوف ثابت، والمساحة الباقية للتقرير المفصّل تحته
        self.tv_wan.master.pack(fill="x", expand=False)
        self.tv_wan.tag_configure("ok", foreground=C["ok"])
        self.tv_wan.tag_configure("warn", foreground=C["warn"])
        self.tv_wan.tag_configure("bad", foreground=C["danger"])
        self.tv_wan.tag_configure("out", foreground=C["muted"])
        self.tv_wan._menu_actions = [(self.T["wan_withdraw"], self.on_withdraw_line),
                                     (self.T["wan_restore"], self.on_restore_line)]

        # التقرير المفصّل تحت الجدول: قابل للتحديد والنسخ، لا للكتابة
        self.txt_wan = tk.Text(f, wrap="word", height=10, relief="flat",
                               bg=C["surface"], fg=C["text"], font=self.font_base,
                               padx=10, pady=8)
        make_text_readonly(self.txt_wan)
        sb = ttk.Scrollbar(f, orient="vertical", command=self.txt_wan.yview)
        self.txt_wan.configure(yscrollcommand=sb.set)
        sb.pack(side=self._side(False), fill="y", pady=(10, 0))
        self.txt_wan.pack(side=self._side(), fill="both", expand=True, pady=(10, 0))

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
        # حقول Firebase تجعل التبويب أطول من النوافذ الصغيرة، لذلك يبقى
        # شريط التمرير داخل هذا التبويب وحده بدلاً من تمديد النافذة كلها.
        shell = self._tab_frame(self.T["tab_settings"])
        canvas = tk.Canvas(shell, bg=C["surface"], highlightthickness=0, borderwidth=0)
        bar = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side=self._side(False), fill="y")
        canvas.pack(side=self._side(), fill="both", expand=True)
        f = ttk.Frame(canvas, padding=(0, 0), style="Card.TFrame")
        window = canvas.create_window((0, 0), window=f, anchor="nw")

        def content_resized(ev):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def canvas_resized(ev):
            canvas.itemconfigure(window, width=ev.width)

        f.bind("<Configure>", content_resized)
        canvas.bind("<Configure>", canvas_resized)
        # يعمل العجل فوق مساحة التبويب، وشريط التمرير متاح دائماً بجانب الحقول.
        canvas.bind("<MouseWheel>", lambda ev: canvas.yview_scroll(
            -1 * int(getattr(ev, "delta", 0) / 120) if getattr(ev, "delta", 0) else 0,
            "units"))
        self.settings_canvas = canvas

        self.v_macpw = tk.StringVar(value=self.settings["mac_shared_password"])
        self.v_autosave = tk.BooleanVar(value=self.settings.get("auto_save_config", True))
        self.v_lang = tk.StringVar(value=self.settings.get("ui_lang", "ar"))
        self.v_firebase_key = tk.StringVar(value=self.settings.get("firebase_api_key", ""))
        self.v_firebase_project = tk.StringVar(value=self.settings.get("firebase_project_id", ""))
        self.v_firebase_email = tk.StringVar(value=self.settings.get("firebase_email", ""))
        self.v_firebase_password = tk.StringVar(value=self.settings.get("firebase_password", ""))

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

        ttk.Button(f, text=self.T["rotate_pw"], command=self.on_rotate_mac_password).grid(
            row=2, column=c_fld, sticky=s_fld)
        hint(3, self.T["rotate_hint"], style="Muted.TLabel")

        ttk.Checkbutton(f, text=self.T["autosave"], variable=self.v_autosave).grid(
            row=4, column=c_fld, sticky=s_fld, pady=8)

        label(5, self.T["lang_label"])
        ttk.Combobox(f, textvariable=self.v_lang, values=["ar", "en"], width=8,
                     state="readonly", justify=self._justify()).grid(
            row=5, column=c_fld, sticky=s_fld)
        hint(6, self.T["lang_note"])

        ttk.Button(f, text=self.T["save_settings"], style="Accent.TButton",
                   command=self.on_save_settings).grid(
            row=7, column=c_fld, sticky=s_fld, pady=14)

        ttk.Separator(f, orient="horizontal").grid(
            row=8, column=0, columnspan=2, sticky="ew", pady=(22, 14))
        lbl_sync = ttk.Label(f, text=self.T["sync_note"], style="Muted.TLabel",
                             justify=self._justify())
        lbl_sync.grid(row=9, column=0, columnspan=2, sticky="ew")
        self._wrap(lbl_sync, f)

        lbl_file = ttk.Label(f, text="%s  %s" % (self.T["data_file"], DB_FILE),
                             style="Muted.TLabel", justify=self._justify())
        lbl_file.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self._wrap(lbl_file, f)

        ttk.Separator(f, orient="horizontal").grid(
            row=11, column=0, columnspan=2, sticky="ew", pady=(22, 10))
        ttk.Label(f, text=self.T["firebase_title"], style="H1.TLabel",
                  justify=self._justify()).grid(row=12, column=0, columnspan=2,
                                                sticky=self._anchor())
        label(13, self.T["firebase_key"])
        ttk.Entry(f, textvariable=self.v_firebase_key, width=36,
                  justify=self._justify()).grid(row=13, column=c_fld, sticky="ew")
        label(14, self.T["firebase_project"])
        ttk.Entry(f, textvariable=self.v_firebase_project, width=36,
                  justify=self._justify()).grid(row=14, column=c_fld, sticky="ew")
        label(15, self.T["firebase_email"])
        ttk.Entry(f, textvariable=self.v_firebase_email, width=36,
                  justify=self._justify()).grid(row=15, column=c_fld, sticky="ew")
        label(16, self.T["firebase_password"])
        ttk.Entry(f, textvariable=self.v_firebase_password, width=36, show="•",
                  justify=self._justify()).grid(row=16, column=c_fld, sticky="ew")
        hint(17, self.T["firebase_hint"], style="Muted.TLabel")
        ttk.Button(f, text=self.T["firebase_sync_now"],
                   command=self.on_firebase_sync_now).grid(
                       row=18, column=c_fld, sticky=s_fld, pady=(0, 14))

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
        make_text_readonly(self.txt_log)
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
        box = None
        if not self._quiet:
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
        self._save_settings()

        self._set_state("● " + self.T["status_on"] + "  " + self.router.hostname,
                        "Ok.TLabel")
        self.btn_conn.configure(text=self.T["disconnect"])
        self.v_pass.set("")
        self.on_refresh_all()
        self._wan_schedule()

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
            self.router_states = self.router.read_local_user_states()
        except Exception as e:
            self._status("خطأ في القراءة / Read error: %s" % e, ok=False)
            return

        self._refresh_device_table()
        self._refresh_portal_table()
        self._refresh_groups_table()
        self.on_refresh_online()
        self._load_mgmt()
        blocked = self._blocked_macs()
        if blocked:
            self._status(self.T["warn_blocked_refresh"] % len(blocked), ok=False)
        else:
            self._status("تم التحديث من الراوتر / Refreshed from router")

    def _blocked_macs(self):
        macs, _, _ = split_user_kinds(self.router_users) if self.router_users else ({}, {}, {})
        return sorted(m for m in macs if self.router_states.get(m) == "B")

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
            if self.router_states.get(mac12) == "B":
                state, tag = self.T["state_blocked"], "blocked"
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

    # -- المتّصلون حسب الشبكة -------------------------------------------------

    def _vlan_item(self, v):
        """نص الشبكة في القائمة المنسدلة: مع عنوانها إن كان لها عنوان."""
        if v.get("ip"):
            return self.T["vlan_item_ip"] % {"vid": v["vid"], "ip": v["ip"], "len": v["len"]}
        return self.T["vlan_item"] % {"vid": v["vid"]}

    def on_refresh_vlans(self):
        """يقرأ قائمة الشبكات، ويبقي المختارة مختارة إن كانت ما تزال موجودة."""
        if not self._need_conn():
            return
        self._status(self.T["working"])
        try:
            self.vlans = self.router.read_vlans()
        except Exception as e:
            self._status("خطأ / Error: %s" % e, ok=False)
            return
        items = [self._vlan_item(v) for v in self.vlans]
        self.cb_vlan.configure(values=items)
        want = getattr(self, "vlan_vid", "")
        idx = next((i for i, v in enumerate(self.vlans) if v["vid"] == want), None)
        if idx is None:
            # الافتراضي أول شبكة لها عنوان: هي وحدها التي تُظهر صورة كاملة
            idx = next((i for i, v in enumerate(self.vlans) if v["iface"]), 0 if items else None)
        if idx is None:
            self.v_vlan.set("")
            self.vlan_state = None
            self._refresh_vlan_table()
            self._status("")
            return
        self.v_vlan.set(items[idx])
        self.on_pick_vlan()

    def on_pick_vlan(self):
        """يقرأ من على الشبكة المختارة. تُستدعى من القائمة المنسدلة ومن التحديث."""
        if not self._need_conn():
            return
        items = list(self.cb_vlan["values"])
        cur = self.v_vlan.get()
        if cur not in items:
            return
        v = self.vlans[items.index(cur)]
        self.vlan_vid = v["vid"]
        self._status(self.T["working"])
        try:
            self.vlan_state = self.router.read_vlan_clients(v["vid"], v.get("iface", ""))
        except Exception as e:
            self._status("خطأ / Error: %s" % e, ok=False)
            return
        self.vlan_state["net"] = v
        self._refresh_vlan_table()
        # التحذير أولى بالشريط من خبر التحديث
        self._status(self._vlan_warn or "تم التحديث من الراوتر / Refreshed from router",
                     ok=not self._vlan_warn)

    def _refresh_vlan_table(self):
        """يبني الجدول من self.vlan_state وحدها؛ البحث لا يستعلم الراوتر."""
        # نحفظ ما اختاره المستخدم: إعادة البناء تمسح التحديد، وبقاء المعرّف
        # (الماك) يتيح إعادته بعد التحديث
        keep = self.tv_vlan.selection()
        for i in self.tv_vlan.get_children():
            self.tv_vlan.delete(i)
        st = getattr(self, "vlan_state", None)
        self._vlan_warn = ""
        if not st:
            self.lbl_vlan_sum.configure(text="")
            self._apply_count(getattr(self, "lbl_count_vlan", None), 0, 0)
            return

        ports = ", ".join(st["ports"]) or self.T["vlan_ports_none"]
        if st.get("iface"):
            pool = st.get("pool")
            args = {"iface": st["iface"],
                    "desc": (" (%s)" % st["desc"]) if st.get("desc") else "",
                    "ports": ports,
                    "pool": self.T["vlan_pool_fmt"] % pool if pool else self.T["vlan_pool_none"]}
            if "." in st["iface"]:
                # واجهة فرعية: لا منافذ لها، والمنفذ الحامل هو الأصل
                args["parent"] = st["iface"].split(".")[0]
                self.lbl_vlan_sum.configure(text=self.T["vlan_summary_sub"] % args)
            else:
                self.lbl_vlan_sum.configure(text=self.T["vlan_summary"] % args)
        else:
            self.lbl_vlan_sum.configure(
                text=self.T["vlan_summary_l2"] % {"ports": ports} + "\n" + self.T["vlan_no_iface"])

        # جدول فارغ يحتاج تفسيراً: أهي شبكة لا يحملها منفذ، أم لا تعبره حركتها؟
        if not st["rows"]:
            if st.get("iface"):
                why = self.T["vlan_empty_quiet"]
            elif not st["ports"]:
                why = self.T["vlan_empty_noport"]
            else:
                why = self.T["vlan_empty_noswitch"] % {"ports": ports}
            self.lbl_vlan_sum.configure(text=self.lbl_vlan_sum.cget("text") + "\n" + why)

        kinds = {"dhcp": "vlan_kind_dhcp", "bind": "vlan_kind_bind",
                 "static": "vlan_kind_static", "none": "vlan_kind_none"}
        pres = {"active": "pres_active", "seen": "pres_seen", "lease": "pres_lease"}
        q = self.v_find_vlan.get() if hasattr(self, "v_find_vlan") else ""
        dups = (getattr(self, "overlap", None) or {}).get("dups") or {}
        shown = total = noaddr = held = crossed = 0
        for r in st["rows"]:
            name = self.db.name_of(r["mac"])
            # عقود الجهاز في شبكات غير هذه — لا تُملأ إلا بعد فحص التداخل
            other = [e for e in dups.get(r["mac"], []) if e["vid"] != str(st["vid"])]
            vals = (r["ip"], mac_pretty(r["mac"]), name,
                    self._vendor_text(r),
                    r["port"] or "—", self.T[kinds[r["kind"]]],
                    self.T[pres[r["presence"]]], r["auth"] or "—",
                    " · ".join("VLAN %s (%s)" % (e["vid"], e["ip"]) for e in other) or "—")
            total += 1
            if r["kind"] == "none":
                noaddr += 1
            if r["presence"] == "lease":
                held += 1
            if other:
                crossed += 1
            if not row_matches(q, vals, r["mac"]):
                continue
            shown += 1
            if other:
                tag = "bad"                         # يحمل عنواناً في شبكة أخرى
            elif r["presence"] == "lease":
                tag = "muted"                       # محجوز لا حاضر
            elif r["kind"] == "none":
                tag = "bad"                         # حاضر بلا عنوان
            else:
                tag = "ok" if r["presence"] == "active" else "muted"
            self.tv_vlan.insert("", "end", iid=r["mac"], values=vals, tags=(tag,))

        back = [i for i in keep if self.tv_vlan.exists(i)]
        if back:
            self.tv_vlan.selection_set(*back)

        self._apply_count(getattr(self, "lbl_count_vlan", None), shown, total)
        # الأجهزة بلا عنوان علامة عطل في العنونة أو المصادقة، لا تفصيلة جدول
        self._vlan_warn = (self.T["vlan_noaddr_warn"] % {"n": noaddr, "total": total}
                           if noaddr and st.get("iface") else "")
        if held:
            self.lbl_vlan_sum.configure(text=self.lbl_vlan_sum.cget("text") + "\n"
                                        + self.T["vlan_lease_note"] % {"n": held})
        if crossed:
            self.lbl_vlan_sum.configure(text=self.lbl_vlan_sum.cget("text") + "\n"
                                        + self.T["vlan_scan_here"] % {"n": crossed})

    def on_scan_overlap(self):
        """
        يقرأ مجمَّعات كل الشبكات مرّة واحدة ويقارنها: الماك الذي يحمل عنواناً
        في شبكتين هو الدليل على تسرّب شبكة إلى أخرى. قراءة محضة، لا أمر تغيير.
        النتيجة تبقى محفوظة فتظهر في خانة «شبكات أخرى» لكل شبكة تُختار بعدها.
        """
        if not self._need_conn():
            return
        if not getattr(self, "vlans", None):
            messagebox.showinfo(APP_NAME, self.T["vlan_scan_first"])
            return
        self._status(self.T["working"])
        result = VlanOverlapOperations(self.router, self.db).scan(self.vlans)
        if not result.ok:
            self._status("خطأ / Error: %s" % (result.error or result.code), ok=False)
            return
        self.overlap = result.data["report"]
        scans = result.data["scans"]
        self._refresh_vlan_table()
        dups, tight = self.overlap["dups"], self.overlap["tight"]
        if dups:
            msg = self.T["vlan_scan_done"] % {"n": len(dups), "nets": len(scans)}
        else:
            msg = self.T["vlan_scan_none"] % {"nets": len(scans)}
        if tight:
            msg += "  " + self.T["vlan_scan_tight"] % " · ".join(
                self.T["vlan_scan_tight_one"] % e for e in tight)
        self._status(msg, ok=not dups and not tight)

    def _vendor_text(self, row):
        """نص خانة المُصنِّع: عشوائي، أو اسم، أو غير معلن، أو الرمز وحده."""
        if row["random"]:
            return self.T["vendor_random"]
        name = mac_vendor(row["mac"])
        if name == "\x00":
            return self.T["vendor_private"]
        return name or mac_oui(row["mac"])

    def _on_vlan_dclick(self, event):
        iid, col = self._tree_cell(self.tv_vlan, event)
        if not iid:
            return
        if col == "ip":
            ip = self.tv_vlan.item(iid, "values")[0]
            if ip:
                self._open_url("http://%s" % ip)
                return
        self.tv_vlan.selection_set(iid)
        self.on_name_vlan_device()

    def _open_url(self, url):
        """يفتح عنواناً في متصفح النظام. فشل الفتح لا يُسقط البرنامج."""
        try:
            webbrowser.open(url)
        except Exception as e:
            self._status("خطأ / Error: %s" % e, ok=False)
            return
        self._status(self.T["vlan_open_ip"] % url)

    def on_name_vlan_device(self):
        """
        تسمية جهاز من جدول الشبكة. محلّية بالكامل: لا أمر يُرسل إلى الراوتر،
        والاسم يُحفظ بالماك فيتبع الجهاز مهما تغيّر عنوانه أو شبكته.
        """
        sel = self.tv_vlan.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, self.T["vlan_pick_row"])
            return
        vals = self.tv_vlan.item(sel[0], "values")
        mac12 = normalize_mac(vals[1])
        if not mac12:
            return
        dlg = FieldDialog(self, self.T["vlan_name_dev"], [
            {"key": "name", "label": self.T["ask_name"], "default": self.db.name_of(mac12)},
            {"key": "note", "label": self.T["ask_note"], "default": self.db.note_of(mac12)},
        ])
        if not dlg.result:
            return
        result = NetworkDeviceNameOperations(self.db).update(
            mac12, dlg.result.get("name"), dlg.result.get("note"))
        self._refresh_vlan_table()
        self._status(self.T["vlan_named"] % {
            "mac": mac_pretty(mac12), "name": self.db.name_of(mac12) or "—"})

    def on_cut_vlan_devices(self):
        """
        يقطع جلسات الأجهزة المحدَّدة. القطع يخصّ المصادَق عليهم وحدهم، فإن كانت
        الشبكة بلا مصادقة قلنا ذلك بدل إرسال أمر لا أثر له.
        """
        if not self._need_conn():
            return
        st = getattr(self, "vlan_state", None) or {}
        sel = [i for i in self.tv_vlan.selection() if self.tv_vlan.exists(i)]
        if not sel:
            messagebox.showinfo(APP_NAME, self.T["vlan_pick_row"])
            return
        if not st.get("nac"):
            messagebox.showinfo(APP_NAME, self.T["vlan_cut_no_nac"])
            return
        names = []
        for mac12 in sel:
            vals = self.tv_vlan.item(mac12, "values")
            names.append("• %s  %s  %s" % (vals[0] or "—", vals[1], vals[2] or ""))
        if not messagebox.askyesno(APP_NAME, self.T["vlan_cut_ask"] % {"n": len(sel)}
                                   + "\n\n" + "\n".join(names)):
            return

        self._status(self.T["working"])
        result = VlanSessionOperations(self.router, self.db).disconnect(st, sel)
        if result.code == "router_error":
            self._status("خطأ / Error: %s" % result.error, ok=False)
            messagebox.showerror(APP_NAME, result.error)
            return
        bad = result.data["bad"]
        self.on_pick_vlan()
        if bad:
            messagebox.showerror(APP_NAME, self.T["vlan_cut_failed"]
                                 % ", ".join(mac_pretty(m) for m in bad))
        self._status(self.T["vlan_cut_done"] % {"ok": len(sel) - len(bad), "n": len(sel)})

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
        self._create_device(mac12, dlg.result["name"], dlg.result["group"],
                            dlg.result["note"])

    def _create_device(self, mac12, name, group, note):
        """ينشئ حساب الماك على الراوتر ويتحقق منه ويسجّله محلياً. يعيد True عند النجاح."""
        service = TrustedDeviceOperations(
            self.router, self.db, self.router_users,
            self.v_macpw.get().strip() or self.settings["mac_shared_password"],
            self.v_autosave.get())
        result = service.create(mac12, name, group, note)
        if result.code == "duplicate":
            messagebox.showerror(APP_NAME, self.T["err_dup"])
            return False
        if result.code == "missing_group":
            messagebox.showwarning(APP_NAME, self.T["warn_no_group"])
            return False
        if result.code == "placeholder_password":
            messagebox.showerror(APP_NAME, self.T["err_placeholder_pw"])
            return False
        if result.code == "password_is_mac":
            messagebox.showerror(
                APP_NAME,
                "كلمة مرور حسابات الماك لا يجوز أن تساوي عنوان الماك.\n"
                "غيّرها من تبويب الإعدادات ومن mac-access-profile على الراوتر.")
            return False
        self._status(self.T["working"])
        if result.users is not None:
            self.router_users = result.users
        if result.code == "not_confirmed":
            self._status("لم يثبت الحساب على الراوتر / Not confirmed on router", ok=False)
            messagebox.showerror(APP_NAME,
                                 "نُفّذت الأوامر لكن الحساب لم يظهر في إعداد الراوتر.\n"
                                 "راجع تبويب سجل الأوامر.")
            return False
        if not result.ok:
            self._status("خطأ / Error: %s" % result.error, ok=False)
            messagebox.showerror(APP_NAME, result.error)
            return False
        self.router_states = result.states or {}
        self._refresh_device_table()
        if self.router_states.get(mac12) == "B":
            self._status(self.T["state_blocked"], ok=False)
            messagebox.showwarning(APP_NAME, self.T["warn_blocked_after_add"])
            return True
        self._status(self.T["ok_added"])
        return True

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
        result = TrustedDeviceOperations(
            self.router, self.db, self.router_users,
            self.settings.get("mac_shared_password", ""), self.v_autosave.get()).revoke(mac12, reason)
        if result.users is not None:
            self.router_users = result.users
        if not result.ok:
            message = ("لم يثبت حذف الحساب من الراوتر / Device removal was not confirmed"
                       if result.code == "not_confirmed" else "خطأ / Error: %s" % result.error)
            self._status(message, ok=False)
            if result.code == "router_error":
                messagebox.showerror(APP_NAME, result.error)
            return

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
        sel = self.tv_dev.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, self.T["no_selection"])
            return
        mac12 = sel[0]
        local = self.db.device(mac12) or {}
        dlg = FieldDialog(self, self.T["edit_meta"], [
            {"key": "name", "label": self.T["ask_name"], "default": local.get("name", "")},
            {"key": "note", "label": self.T["ask_note"], "default": local.get("note", "")},
        ])
        if dlg.result is None:
            return
        result = TrustedDeviceOperations(None, self.db, {}, "", False).update_metadata(
            mac12, dlg.result["name"], dlg.result["note"])
        if result.code == "unchanged":
            return
        self._refresh_device_table()
        if self.tv_dev.exists(mac12):
            self.tv_dev.selection_set(mac12)
            self.tv_dev.see(mac12)
        self._status(self.T["ok_edit"])

    def on_edit_portal_meta(self):
        sel = self.tv_por.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, self.T["no_selection"])
            return
        user = sel[0]
        local = self.db.portal(user) or {}
        dlg = FieldDialog(self, self.T["edit_meta"], [
            {"key": "name", "label": self.T["ask_name"], "default": local.get("name", "")},
            {"key": "note", "label": self.T["ask_note"], "default": local.get("note", "")},
        ])
        if dlg.result is None:
            return
        result = PortalAccountOperations(self.db).update_metadata(
            user, dlg.result["name"], dlg.result["note"])
        if result.code == "unchanged":
            return
        self._refresh_portal_table()
        if self.tv_por.exists(user):
            self.tv_por.selection_set(user)
            self.tv_por.see(user)
        self._status(self.T["ok_edit"])

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
        result = TrustedDeviceOperations(
            self.router, self.db, self.router_users,
            self.settings.get("mac_shared_password", ""), self.v_autosave.get()).change_group(mac12, group)
        if result.users is not None:
            self.router_users = result.users
        if not result.ok:
            message = ("لم يثبت تغيير المجموعة على الراوتر / Group change was not confirmed"
                       if result.code == "not_confirmed" else "خطأ / Error: %s" % result.error)
            self._status(message, ok=False)
            return
        self._refresh_device_table()
        self._status(self.T["ok_group"] + "  —  قد يحتاج الجهاز دقيقة لإعادة الاتصال")

    def on_trust_online(self):
        """
        يضيف الجهاز المحدد في جدول المتصلين إلى القائمة الموثوقة. الماك والـIP
        والحساب تُنقل من الصف للقراءة فقط — لا يُكتب الماك يدوياً فلا يُخطأ فيه.
        """
        if not self._need_conn():
            return
        sel = self.tv_on.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, self.T["no_selection"])
            return
        uid, user, ip, mac = [str(v) for v in self.tv_on.item(sel[0], "values")[:4]]
        mac12 = normalize_mac(mac)
        if not mac12:
            messagebox.showinfo(APP_NAME, "هذا السطر بلا عنوان ماك / This row has no MAC")
            return

        local = self.db.device(mac12) or {}
        if mac12 in self.router_users:
            messagebox.showinfo(APP_NAME, self.T["info_already_trusted"] % {
                "mac": mac_pretty(mac12), "name": local.get("name") or "—",
                "group": self.router_users[mac12].get("group") or "—"})
            return

        dlg = FieldDialog(self, self.T["add_online_title"], [
            {"key": "mac", "label": self.T["col_mac"], "kind": "readonly",
             "default": mac_pretty(mac12)},
            {"key": "ip", "label": self.T["col_ip"], "kind": "readonly", "default": ip},
            {"key": "account", "label": self.T["ask_account"], "kind": "readonly",
             "default": user},
            # سجل محلي قديم (جهاز أُلغي ثم عاد) يحمل اسمه — نقترحه بدل خانة فارغة
            {"key": "name", "label": self.T["ask_name"], "default": local.get("name", "")},
            {"key": "group", "label": self.T["ask_group"], "kind": "combo",
             "values": self._groups_list(),
             "default": local.get("group") or self.settings.get("default_mac_group", "grp_staff")},
            {"key": "note", "label": self.T["ask_note"], "default": local.get("note", "")},
        ])
        if not dlg.result:
            return
        name, group = dlg.result["name"], dlg.result["group"]
        if not name:
            messagebox.showwarning(APP_NAME, self.T["err_need_name"])
            return
        if not self._create_device(mac12, name, group, dlg.result["note"]):
            return

        # جلسة قائمة بحساب آخر (بوابة أو ما قبل المصادقة) لا تتغيّر صلاحياتها
        # حتى يعيد الجهاز المصادقة. نعرض فصلها ولا نفرضه.
        if user.lower() != mac12 and messagebox.askyesno(
                APP_NAME, self.T["ask_cut_after_trust"] % {"user": user, "group": group}):
            try:
                self.router.send_many(["system-view", "aaa",
                                       "cut access-user user-id %s" % uid,
                                       "quit", "quit"])
            except Exception as e:
                messagebox.showerror(APP_NAME, str(e))
                return
        self.on_refresh_online()

    def on_cut_user(self):
        if not self._need_conn():
            return
        sel = self.tv_on.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, self.T["no_selection"])
            return
        vals = self.tv_on.item(sel[0], "values")
        uid = vals[0]
        result = OnlineSessionOperations(self.router).disconnect(uid)
        if result.online is not None:
            self.online_rows = result.online
        if not result.ok:
            message = ("لم يثبت فصل الجلسة على الراوتر / Session disconnect was not confirmed"
                       if result.code == "not_confirmed" else result.error)
            messagebox.showerror(APP_NAME, message or "تعذر فصل المستخدم.")
            return
        self._refresh_online_table()
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

        self._status(self.T["working"])
        result = PortalAccountOperations(
            self.db, self.router, self.router_users, self.v_autosave.get()).create(
                dlg.result["user"], dlg.result["pw"], dlg.result["name"],
                dlg.result["group"], dlg.result["note"])
        if result.users is not None:
            self.router_users = result.users
        if not result.ok:
            messages = {
                "bad_username": self.T["err_bad_user"],
                "short_password": self.T["err_short_pw"],
                "password_is_username": self.T["err_pw_eq_user"],
                "missing_group": self.T["warn_no_group"],
                "duplicate": "هذا الحساب موجود مسبقاً / Account already exists",
                "not_confirmed": "نُفّذت الأوامر لكن الحساب لم يظهر في إعداد الراوتر.\nراجع تبويب سجل الأوامر.",
                "router_error": result.error,
            }
            if result.code == "router_error":
                self._status("خطأ / Error: %s" % result.error, ok=False)
            messagebox.showerror(APP_NAME, messages.get(result.code, "تعذر إتمام العملية."))
            return
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
        result = PortalAccountOperations(
            self.db, self.router, self.router_users, self.v_autosave.get()).change_password(
                user, dlg.result["pw"])
        if not result.ok:
            messages = {
                "short_password": self.T["err_short_pw"],
                "password_is_username": self.T["err_pw_eq_user"],
                "router_error": result.error,
            }
            messagebox.showerror(APP_NAME, messages.get(result.code, "تعذر تغيير كلمة المرور."))
            return
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
        result = PortalAccountOperations(
            self.db, self.router, self.router_users, self.v_autosave.get()).change_group(
                user, group, self.settings.get("portal_domain", ""))
        if result.users is not None:
            self.router_users = result.users
        if not result.ok:
            message = ("لم يثبت تغيير المجموعة على الراوتر / Group change was not confirmed"
                       if result.code == "not_confirmed" else result.error)
            messagebox.showerror(APP_NAME, message or "تعذر تغيير المجموعة.")
            return
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
        result = PortalAccountOperations(
            self.db, self.router, self.router_users, self.v_autosave.get()).revoke(
                user, reason, self.settings.get("portal_domain", ""))
        if result.users is not None:
            self.router_users = result.users
        if not result.ok:
            message = ("لم يثبت حذف الحساب على الراوتر / Account deletion was not confirmed"
                       if result.code == "not_confirmed" else result.error)
            messagebox.showerror(APP_NAME, message or "تعذر حذف الحساب.")
            return
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

    def on_rotate_mac_password(self):
        """
        يغيّر كلمة سر الماك المشتركة في mac-access-profile وفي كل حسابات الماك
        معاً، ويفكّ حظر المحظور منها. تغيير أحدهما دون الآخر يجعل الراوتر يرفض
        كل جهاز عند إعادة مصادقته ثم يحظره.
        """
        if not self._need_conn():
            return
        self._status(self.T["working"])
        try:
            profiles = self.router.read_mac_profiles()
            self.router_users = parse_local_users(self.router.read_aaa())
            self.router_states = self.router.read_local_user_states()
        except Exception as e:
            self._status("خطأ / Error: %s" % e, ok=False)
            messagebox.showerror(APP_NAME, str(e))
            return
        self._status("")
        if not profiles:
            messagebox.showerror(APP_NAME, self.T["err_no_profile"])
            return

        names = sorted(profiles)
        preferred = self.settings.get("mac_access_profile")
        dlg = FieldDialog(self, self.T["rotate_pw"], [
            {"key": "profile", "label": self.T["ask_profile"], "kind": "combo",
             "values": names, "default": preferred if preferred in profiles else names[0]},
            {"key": "pw", "label": self.T["ask_new_pw"], "kind": "password"},
            {"key": "pw2", "label": self.T["ask_new_pw2"], "kind": "password"},
        ])
        if not dlg.result:
            return
        profile, pw = dlg.result["profile"], dlg.result["pw"]
        if pw != dlg.result["pw2"]:
            messagebox.showerror(APP_NAME, self.T["err_pw_mismatch"])
            return
        problem = mac_password_problem(pw)
        if problem:
            messagebox.showerror(APP_NAME, self.T[problem])
            return

        macs = sorted(split_user_kinds(self.router_users)[0])
        blocked = self._blocked_macs()
        if not messagebox.askyesno(APP_NAME, self.T["confirm_rotate"] % {
                "profile": profile, "count": len(macs), "blocked": len(blocked)}):
            return

        self._status(self.T["working"])
        try:
            res = self.router.rotate_mac_password(profile, pw, macs, unblock=blocked)
            if res["profile_ok"]:
                self._maybe_save()
                self.router_states = self.router.read_local_user_states()
        except Exception as e:
            self._status("خطأ / Error: %s" % e, ok=False)
            messagebox.showerror(APP_NAME, str(e))
            return

        if not res["profile_ok"]:
            self._status(self.T["err_rotate_profile"].split("\n")[0], ok=False)
            messagebox.showerror(APP_NAME, self.T["err_rotate_profile"] % res["profile_error"])
            return

        # الملف تغيّر على الراوتر، فالإعدادات يجب أن تتبعه حتى لو فشل بعض الحسابات
        self.v_macpw.set(pw)
        self.settings["mac_shared_password"] = pw
        self.settings["mac_access_profile"] = profile
        self._save_settings()
        self.db.log("rotate_mac_password", profile, "%d accounts, %d unblocked, %d failed"
                    % (len(macs), len(res["unblocked"]), len(res["failed"])))
        self._refresh_device_table()

        if res["failed"]:
            detail = "\n".join("%s  —  %s" % (mac_pretty(m), err)
                               for m, err in sorted(res["failed"].items()))
            self._status(self.T["err_rotate_partial"].split("\n")[0], ok=False)
            messagebox.showerror(APP_NAME, self.T["err_rotate_partial"] % detail)
            return
        self._status(self.T["ok_rotated"] % len(macs))

    # -- أجهزة الإدارة -------------------------------------------------------

    def _load_mgmt(self):
        """يقرأ صورة أجهزة الإدارة ويبني الجدول. يعيد False عند الخطأ."""
        try:
            self.mgmt_state = self.router.read_mgmt_state()
        except Exception as e:
            self._status("خطأ / Error: %s" % e, ok=False)
            return False
        self._refresh_mgmt_table()
        warn = self._mgmt_http_warning()
        if warn:
            self._status(warn, ok=False)
        return True

    def on_refresh_mgmt(self):
        if not self._need_conn():
            return
        if self._load_mgmt() and not self._mgmt_http_warning():
            self._status("تم التحديث من الراوتر / Refreshed from router")

    def _mgmt_http_warning(self):
        """نص التنبيه إن كان http acl مضبوطاً والبوابة المدمجة مفعّلة، وإلا فارغ."""
        st = self.mgmt_state or {}
        acl = (st.get("bindings") or {}).get("http")
        if acl and st.get("portal"):
            return self.T["mgmt_warn_http_acl"] % {"acl": acl}
        return ""

    def _refresh_mgmt_table(self):
        for i in self.tv_mgmt.get_children():
            self.tv_mgmt.delete(i)
        st = self.mgmt_state
        if not st:
            return
        b = st["bindings"]
        if st["http_permit"] is None:
            ifaces = self.T["mgmt_http_any"]
        else:
            ifaces = " ".join(st["http_permit"])
        self.lbl_mgmt_access.configure(text=self.T["mgmt_access"] % {
            "vty": ", ".join(sorted(b["vty"])) or "—",
            "http": self.T["mgmt_http_fmt"] % {"acl": b["http"] or self.T["mgmt_http_noacl"],
                                               "ifaces": ifaces}}
            + ("\n" + self._mgmt_http_warning() if self._mgmt_http_warning() else ""))

        online = {}
        for r in self.online_rows:
            m = normalize_mac(r["mac"]) if r["mac"] else None
            if m:
                online[m] = r["ip"]
        self.mgmt_rows = mgmt_entries(st)
        for e in self.mgmt_rows:
            local = self.db.data["mgmt"].get(e["ip"]) or {}
            dev = self.db.device(e["mac"]) if e["mac"] else None
            name = local.get("name") or (dev or {}).get("name") or e["desc"]
            now = online.get(e["mac"])
            if now is None:
                on = self.T["mgmt_offline"]
            elif now == e["ip"]:
                on = self.T["mgmt_on_ip"]
            else:
                on = self.T["mgmt_on_other"] % now
            rules = ", ".join("%s/%d" % r for r in e["rules"]) or "✗"
            vals = (e["ip"], mac_pretty(e["mac"]) if e["mac"] else "", name, e["iface"], rules,
                    "✓" if e["bind"] else "✗", "✓" if e["arp"] else "✗", on,
                    self.T["mgmt_ready"] if e["complete"] else self.T["mgmt_incomplete"])
            self.tv_mgmt.insert("", "end", iid=e["ip"], values=vals,
                                tags=("ok" if e["complete"] else "orphan",))

    def _mgmt_msg(self, items):
        return "\n".join("• " + self.T[k] % args for k, args in items)

    def on_add_mgmt(self):
        if not self._need_conn():
            return
        self._status(self.T["working"])
        if not self._load_mgmt():
            return
        self._status("")
        st = self.mgmt_state
        if not st["networks"]:
            messagebox.showerror(APP_NAME, self.T["mgmt_err_net"] % {"net": "Vlanif"})
            return
        if not st["acls"]:
            messagebox.showerror(APP_NAME, self.T["mgmt_err_acl"] % {"acl": "2000-2999"})
            return

        preset = ""
        sel = self.tv_dev.selection()
        if sel and normalize_mac(sel[0]):
            preset = mac_pretty(sel[0])
        nets = {"%s  ·  %s/%d" % (n["iface"], n["ip"], n["len"]): n["iface"] for n in st["networks"]}
        acls = {}
        for no in sorted(st["acls"]):
            tags = []
            if no in st["bindings"]["vty"]:
                tags.append(self.T["acl_tag_vty"])
            if no == st["bindings"]["http"]:
                tags.append(self.T["acl_tag_http"])
            label = no + ("  ·  " + st["acls"][no]["desc"] if st["acls"][no]["desc"] else "")
            acls[label + ("  (%s)" % ", ".join(tags) if tags else "")] = no
        want_net = self.settings.get("mgmt_iface")
        want_acl = self.settings.get("mgmt_acl")
        dlg = FieldDialog(self, self.T["mgmt_add"], [
            {"key": "mac", "label": self.T["ask_mac"], "default": preset},
            {"key": "name", "label": self.T["ask_name"]},
            {"key": "net", "label": self.T["ask_net"], "kind": "combo", "values": list(nets),
             "default": next((k for k, v in nets.items() if v == want_net), list(nets)[0])},
            {"key": "ip", "label": self.T["ask_ip"]},
            {"key": "acl", "label": self.T["ask_acl"], "kind": "combo", "values": list(acls),
             "default": next((k for k, v in acls.items() if v == want_acl), list(acls)[0])},
        ])
        if not dlg.result:
            return
        r = dlg.result
        mac12 = normalize_mac(r["mac"])
        if not mac12:
            messagebox.showerror(APP_NAME, self.T["err_bad_mac"])
            return
        if not r["name"]:
            messagebox.showerror(APP_NAME, self.T["err_need_name"])
            return
        # القيمة قد تكون التسمية المعروضة أو الاسم المجرد (إن كُتب يدوياً)
        iface = nets.get(r["net"], r["net"].split()[0] if r["net"] else "")
        acl_no = acls.get(r["acl"], r["acl"].split()[0] if r["acl"] else "")

        self._status(self.T["working"])
        try:
            st = self.router.read_mgmt_state(iface, mac12)
        except Exception as e:
            self._status("خطأ / Error: %s" % e, ok=False)
            messagebox.showerror(APP_NAME, str(e))
            return
        self._status("")
        trusted = mac12 in self.router_users
        plan, errors, warns = plan_mgmt_device(st, mac12, iface, r["ip"], acl_no, trusted)
        if errors:
            self._status(self.T["mgmt_err_title"], ok=False)
            messagebox.showerror(APP_NAME, self.T["mgmt_err_title"] + "\n\n" + self._mgmt_msg(errors)
                                 + ("\n\n" + self.T["mgmt_warn_head"] + "\n" + self._mgmt_msg(warns)
                                    if warns else ""))
            return

        desc = mgmt_description(r["name"])
        cmds = "\n".join(c for step in mgmt_steps(plan, desc) for c in step["do"])
        text = self.T["mgmt_confirm"] % {"cmds": cmds}
        if warns:
            text = self.T["mgmt_warn_head"] + "\n" + self._mgmt_msg(warns) + "\n\n" + text
        if not messagebox.askyesno(APP_NAME, text):
            return

        self.settings["mgmt_iface"], self.settings["mgmt_acl"] = iface, acl_no
        self._save_settings()
        self._status(self.T["working"])
        try:
            res = self.router.apply_mgmt_device(plan, desc)
            if res["ok"]:
                self._maybe_save()
        except Exception as e:
            self._status("خطأ / Error: %s" % e, ok=False)
            messagebox.showerror(APP_NAME, str(e))
            self._load_mgmt()
            return

        step_name = lambda k: self.T.get("mgmt_step_" + k, k)
        if res.get("state"):
            self.mgmt_state = res["state"]
        if res["failed_step"]:
            rollback = (self.T["mgmt_rolled_back"] % "، ".join(step_name(k) for k in res["rolled_back"])
                        if res["rolled_back"] else self.T["mgmt_nothing_applied"])
            self.db.log("mgmt_add_failed", plan["ip"], "%s: %s" % (res["failed_step"], res["error"]))
            self._load_mgmt()
            self._status(res["error"], ok=False)
            messagebox.showerror(APP_NAME, self.T["mgmt_fail"] % {
                "step": step_name(res["failed_step"]), "error": res["error"], "rollback": rollback})
            return

        self.db.upsert_mgmt(plan["ip"], mac12, r["name"], iface, acl_no)
        self.db.log("mgmt_add", plan["ip"], "%s / %s / acl %s rule %d"
                    % (mac_pretty(mac12), iface, acl_no, plan["rule"]))
        self._refresh_mgmt_table()
        if res["missing"]:
            self._status(self.T["mgmt_incomplete"], ok=False)
            messagebox.showerror(APP_NAME, self.T["mgmt_missing"]
                                 % "، ".join(step_name(k) for k in res["missing"]))
            return
        gw = next(n["ip"] for n in st["networks"] if n["iface"] == iface)
        msg = self.T["mgmt_ok"] % {"mac": mac_pretty(mac12), "ip": plan["ip"], "net": iface,
                                   "user": self.settings.get("username", "admin"), "gw": gw}
        if res.get("desc_dropped"):
            msg += "\n" + self.T["mgmt_desc_dropped"]
        if any(k == "mgmt_warn_reconnect" for k, _ in warns):
            msg += "\n\n" + self._mgmt_msg([w for w in warns if w[0] == "mgmt_warn_reconnect"])
        self._status(self.T["mgmt_ok_status"] % plan["ip"])
        messagebox.showinfo(APP_NAME, msg)

    def on_remove_mgmt(self):
        if not self._need_conn():
            return
        sel = self.tv_mgmt.selection()
        entry = next((e for e in self.mgmt_rows if sel and e["ip"] == sel[0]), None)
        if entry is None:
            messagebox.showinfo(APP_NAME, self.T["mgmt_select"])
            return
        if entry["ip"] == self.router.local_address():
            messagebox.showerror(APP_NAME, self.T["mgmt_err_self"] % entry["ip"])
            return
        parts = ["ACL %s rule %d" % r for r in entry["rules"]]
        if entry["arp"]:
            parts.append("ARP")
        if entry["bind"]:
            parts.append("DHCP static-bind")
        if not messagebox.askyesno(APP_NAME, self.T["mgmt_confirm_remove"] % {
                "ip": entry["ip"], "mac": mac_pretty(entry["mac"]) if entry["mac"] else "—",
                "parts": "، ".join(parts)}):
            return
        self._status(self.T["working"])
        try:
            res = self.router.remove_mgmt_device(entry)
        except Exception as e:
            self._status("خطأ / Error: %s" % e, ok=False)
            messagebox.showerror(APP_NAME, str(e))
            self._load_mgmt()
            return
        self.mgmt_state = res["state"]
        self._refresh_mgmt_table()
        left = res["left"]
        if res["errors"] or left:
            detail = "\n".join("%s  —  %s" % kv for kv in sorted(res["errors"].items()))
            if left:
                still = ["ACL %s rule %d" % r for r in left["rules"]]
                still += ["ARP"] if left["arp"] else []
                still += ["DHCP static-bind"] if left["bind"] else []
                detail = (detail + "\n\n" if detail else "") + "، ".join(still)
            self.db.log("mgmt_remove_partial", entry["ip"], detail)
            self._status(self.T["mgmt_remove_partial"].split(":")[0], ok=False)
            messagebox.showerror(APP_NAME, self.T["mgmt_remove_partial"] % {
                "ip": entry["ip"], "detail": detail})
            return
        self._maybe_save()
        self.db.drop_mgmt(entry["ip"])
        self.db.log("mgmt_remove", entry["ip"], mac_pretty(entry["mac"]) if entry["mac"] else "")
        self._status(self.T["mgmt_removed"] % entry["ip"])

    # -- خطوط الإنترنت -------------------------------------------------------

    def _wan_name(self, ln):
        if ln.get("desc"):
            return ln["desc"]
        if ln.get("track"):
            return ln["track"][1]
        return ln["gw"]

    def _wan_notes(self, ln):
        """ملاحظات الإعداد من التحليل + ملاحظات المنفذ، بنص الواجهة."""
        notes = [self.T[n] for n in ln.get("notes", [])]
        if ln.get("health") == "blocked":
            notes.insert(0, self.T["note_blocked"])
        if ln.get("health") == "throttled":
            notes.insert(0, self.T["note_throttled"] % ("%g" % round(ln["kbps"] / 1000.0, 1)))
        if ln.get("kbps") is None and ln.get("ping"):
            notes.append(self.T["note_no_bw"])
        port = ln.get("port") or {}
        if port.get("speed") and port["speed"] < 1000:
            notes.append(self.T["note_speed"] % port["speed"])
        if port.get("crc"):
            notes.append(self.T["note_crc"] % port["crc"])
        down, now = _vrp_time(port.get("last_down")), _vrp_time(port.get("now"))
        if down and now and datetime.timedelta(0) <= now - down <= datetime.timedelta(days=1):
            notes.append(self.T["note_recent_down"] % down.strftime("%Y-%m-%d %H:%M"))
        return notes

    @staticmethod
    def _wan_mbps(ln):
        """السعة رقماً بالميغابت للرسائل — بلا وحدة ولا سقف."""
        kbps = ln.get("kbps")
        return "—" if kbps is None else "%g" % round(kbps / 1000.0, 1)

    def _wan_bw_text(self, ln):
        """السعة بالميغابت، أو «> السقف» حين يكون الفارق أصغر من دقة القياس."""
        kbps = ln.get("kbps")
        if kbps is None:
            return self.T["res_none"]
        mbps = "%g" % round(kbps / 1000.0, 1)
        if kbps >= WAN_BW_CAP_KBPS:
            return self.T["bw_over"] % ("%g" % (WAN_BW_CAP_KBPS / 1000.0))
        return self.T["bw_fmt"] % mbps

    def _wan_route_text(self, ln):
        if ln.get("withdrawn"):
            reason = ln["withdrawn"].get("reason")
            return self.T["route_auto" if reason == "auto" else "route_manual"]
        if ln.get("route_state") == "Active":
            return self.T["route_active"]
        if ln.get("route_state"):
            return self.T["route_invalid"]
        return self.T["res_none"]

    def _wan_res_text(self, res):
        if res is None:
            return self.T["res_none"]
        return self.T["res_ok" if res["ok"] else "res_fail"]

    @staticmethod
    def _fmt_bps(bps):
        if bps is None:
            return "—"
        for unit, div in (("Mbps", 1e6), ("kbps", 1e3)):
            if bps >= div:
                return "%.1f %s" % (bps / div, unit)
        return "%d bps" % bps

    def _refresh_wan_table(self):
        for i in self.tv_wan.get_children():
            self.tv_wan.delete(i)
        tags = {"ok": "ok", "slow": "warn", "unknown": "warn", "blocked": "bad",
                "throttled": "bad", "down": "bad", "port_down": "out", "withdrawn": "out"}
        for ln in self.wan_lines:
            ping = ln.get("ping")
            rtt = (self.T["rtt_fmt"] % {"avg": ping["avg"] if ping["avg"] is not None else "—",
                                        "loss": ("%g" % ping["loss"]) if ping["loss"] is not None
                                        else "—"}) if ping else self.T["res_none"]
            port = ln.get("port") or {}
            port_txt = "—"
            if port.get("speed"):
                port_txt = "%sM %s · CRC %s" % (port["speed"], port.get("duplex") or "",
                                                 port.get("crc") if port.get("crc") is not None
                                                 else "—")
            iface = ln.get("iface") or "—"
            if ln.get("phys") and ln["phys"] != ln.get("iface"):
                iface = "%s → %s" % (iface, ln["phys"])
            verdict = self.T["verdict_" + ln["verdict"]]
            if ln["verdict"] == "withdrawn" and ln.get("health") not in (None, "withdrawn"):
                verdict = "%s · %s" % (verdict, self.T["verdict_" + ln["health"]])
            if self._wan_notes(ln) and ln["verdict"] == "ok":
                verdict += " ⚠"
            # منفذ مفصول: مسار /32 للفحص غير صالح فيخرج الفحص من خط آخر وينجح،
            # فنتائجه لا تخص هذا الخط ولا نعرضها كي لا توهم أنه يعمل
            probes = ln.get("health") != "port_down"
            vals = (self._wan_name(ln), iface, ln["gw"], self._wan_route_text(ln),
                    self._wan_res_text(ln.get("icmp_result") if probes else None),
                    self._wan_res_text(ln.get("tcp_result") if probes else None),
                    rtt, self._wan_bw_text(ln) if probes else self.T["res_none"],
                    port_txt, verdict)
            self.tv_wan.insert("", "end", iid=ln["gw"], values=vals,
                               tags=(tags.get(ln["verdict"], ""),))
        self._render_wan_report()

    def _wan_report_text(self):
        T = self.T
        out = [T["rep_title"] % now_stamp(), ""]
        for ln in self.wan_lines:
            out.append("%s  (%s, %s %s)" % (self._wan_name(ln), ln.get("iface") or "—",
                                             T["rep_gw"], ln["gw"]))
            verdict = T["verdict_" + ln["verdict"]]
            if ln["verdict"] == "withdrawn":
                verdict += " · " + T["verdict_" + ln["health"]]
            out.append("  %s: %s" % (T["rep_verdict"], verdict))
            route = self._wan_route_text(ln)
            if ln.get("route_age") and ln.get("route_state"):
                route += "  (%s)" % ln["route_age"]
            out.append("  %s: %s" % (T["rep_route"], route))
            for slot, label, res_key in (("icmp", T["rep_icmp"], "icmp_result"),
                                         ("tcp", T["rep_https"], "tcp_result")):
                t = ln.get(slot)
                if not t or ln.get("health") == "port_down":
                    continue
                where = t["dest"] + (":" + t["port"] if t.get("port") else "")
                out.append("  %s (%s → %s): %s" % (label, t["name"], where,
                                                   self._wan_res_text(ln.get(res_key))))
            ping = ln.get("ping")
            if ping:
                out.append("  %s: %s" % (T["rep_live"], T["rep_live_fmt"] % {
                    k: ("%g" % v if isinstance(v, float) else (v if v is not None else "—"))
                    for k, v in ping.items()}))
            if ln.get("kbps") is not None:
                out.append("  %s: %s" % (T["rep_bw"], T["rep_bw_fmt"] % {
                    "bw": self._wan_bw_text(ln), "small": WAN_SMALL_BYTES, "big": WAN_BIG_BYTES,
                    "rtt_small": (ln.get("ping") or {}).get("min", "—"),
                    "rtt_big": (ln.get("ping_big") or {}).get("min", "—")}))
            port = ln.get("port") or {}
            if port.get("speed") or port.get("in_bps") is not None:
                bits = []
                if ln.get("phys") and ln["phys"] != ln.get("iface"):
                    bits.append(ln["phys"])
                if port.get("speed"):
                    bits.append("%sM %s" % (port["speed"], port.get("duplex") or ""))
                if port.get("crc") is not None:
                    bits.append("CRC %s" % port["crc"])
                if port.get("in_bps") is not None:
                    bits.append(T["rep_rate"] % (self._fmt_bps(port["in_bps"]),
                                                 self._fmt_bps(port.get("out_bps"))))
                out.append("  %s: %s" % (T["rep_port"], "، ".join(bits) if self.rtl
                                          else ", ".join(bits)))
            for note in self._wan_notes(ln):
                out.append("  ⚠ " + note)
            out.append("")
        return "\n".join(out)

    def _render_wan_report(self):
        try:
            self.txt_wan.delete("1.0", "end")
            if self.wan_lines:
                self.txt_wan.insert("end", self._wan_report_text(), ("dir",))
                self.txt_wan.tag_configure("dir", justify="right" if self.rtl else "left")
        except Exception:
            pass

    def on_check_lines(self, live=True):
        """يفحص الخطوط ويعيد القائمة، أو None إن تعذّر."""
        if not self._quiet and not self._need_conn():
            return None
        if not self._quiet:
            self._status(self.T["working"])
        withdrawn = self.settings["withdrawn_lines"]
        try:
            lines = self.router.read_wan_lines(withdrawn, live_ping=live)
        except Exception as e:
            if self._quiet:
                self._status(self.T["auto_error"] % e, ok=False)
            else:
                self._status("خطأ / Error: %s" % e, ok=False)
                messagebox.showerror(APP_NAME, str(e))
            return None

        # مسار أُعيد يدوياً على الراوتر لم يعد «خارج التوزيع»
        stale = [gw for gw in withdrawn if any(l["gw"] == gw and l["in_config"] for l in lines)]
        if stale:
            for gw in stale:
                withdrawn.pop(gw, None)
            self._save_settings()
            for ln in lines:
                if ln["gw"] in stale:
                    ln["withdrawn"] = None
                    classify_line(ln)

        self.wan_lines = lines
        self._refresh_wan_table()
        try:
            self.lbl_wan_last.configure(text=self.T["wan_last"] % now_stamp())
        except Exception:
            pass
        blocked = [self._wan_name(l) for l in lines
                   if l["verdict"] in ("blocked", "throttled")
                   and l.get("route_state") == "Active"]
        if blocked:
            self._status(self.T["warn_blocked_lines"] % "، ".join(blocked), ok=False)
        else:
            good = sum(1 for l in lines if l["verdict"] == "ok")
            self._status(self.T["ok_checked"] % {
                "n": len(lines), "ok": good,
                "bad": sum(1 for l in lines if l["verdict"] not in ("ok", "port_down"))})
        return lines

    def _selected_wan_line(self):
        if not self.wan_lines:
            messagebox.showwarning(APP_NAME, self.T["err_not_checked"])
            return None
        sel = self.tv_wan.selection()
        ln = next((l for l in self.wan_lines if sel and l["gw"] == sel[0]), None)
        if ln is None:
            messagebox.showwarning(APP_NAME, self.T["err_no_line"])
        return ln

    def _other_working_lines(self, gw):
        return [l for l in self.wan_lines
                if l["gw"] != gw and not l.get("withdrawn") and l.get("route_state") == "Active"
                and l.get("health") in ("ok", "slow")]

    def _withdraw(self, ln, reason):
        """ينفّذ الإخراج ويحفظ المسار محلياً قبل أي شيء آخر."""
        removed = self.router.withdraw_wan_line(ln["gw"])
        self.settings["withdrawn_lines"][ln["gw"]] = {
            "track": list(removed["track"]) if removed["track"] else None,
            "reason": reason, "at": now_stamp(), "line": removed["line"],
            "health": ln.get("health"), "name": self._wan_name(ln)}
        self._save_settings()
        self.db.log("wan_withdraw", ln["gw"], "%s (%s)" % (self._wan_name(ln), reason))

    def _restore(self, ln):
        rec = self.settings["withdrawn_lines"].get(ln["gw"]) or {}
        self.router.restore_wan_line(ln["gw"], rec.get("track"))
        self.settings["withdrawn_lines"].pop(ln["gw"], None)
        self._save_settings()
        self.db.log("wan_restore", ln["gw"], self._wan_name(ln))

    def on_withdraw_line(self):
        if not self._need_conn():
            return
        ln = self._selected_wan_line()
        if ln is None:
            return
        if ln.get("withdrawn") or not ln.get("in_config"):
            messagebox.showinfo(APP_NAME, self.T["err_already_out"])
            return
        if not self._other_working_lines(ln["gw"]):
            messagebox.showerror(APP_NAME, self.T["err_last_line"])
            return
        name = self._wan_name(ln)
        if not messagebox.askyesno(APP_NAME, self.T["confirm_withdraw"] % {
                "line": name, "gw": ln["gw"]}):
            return
        self._status(self.T["working"])
        try:
            self._withdraw(ln, "manual")
            self._maybe_save()
        except Exception as e:
            self._status("خطأ / Error: %s" % e, ok=False)
            messagebox.showerror(APP_NAME, str(e))
            return
        self.on_check_lines(live=False)
        self._status(self.T["ok_withdrawn"] % name)

    def on_restore_line(self):
        if not self._need_conn():
            return
        ln = self._selected_wan_line()
        if ln is None:
            return
        rec = self.settings["withdrawn_lines"].get(ln["gw"])
        if not ln.get("withdrawn") or not rec:
            messagebox.showinfo(APP_NAME, self.T["err_not_out"])
            return
        name = self._wan_name(ln)
        cmd = "ip route-static 0.0.0.0 0.0.0.0 %s" % ln["gw"]
        if rec.get("track"):
            cmd += " track nqa %s %s" % tuple(rec["track"])
        if not messagebox.askyesno(APP_NAME, self.T["confirm_restore"] % {
                "line": name, "gw": ln["gw"], "cmd": cmd}):
            return
        self._status(self.T["working"])
        try:
            self._restore(ln)
            self._maybe_save()
        except Exception as e:
            self._status("خطأ / Error: %s" % e, ok=False)
            messagebox.showerror(APP_NAME, str(e))
            return
        self._wan_streak.pop(ln["gw"], None)
        self.on_check_lines(live=False)
        self._status(self.T["ok_restored"] % name)

    def on_copy_wan_report(self):
        if not self.wan_lines:
            messagebox.showwarning(APP_NAME, self.T["err_not_checked"])
            return
        self._copy_text(self._wan_report_text())

    # -- المراقبة التلقائية ----------------------------------------------------

    WAN_AUTO_MS = 60000
    WAN_STREAK = 2          # فحصان متتاليان قبل أي تصرف، كي لا تُسقط رزمة ضائعة خطاً
    WAN_BW_EVERY = 5        # قياس السعة كل خمس دورات: يكلّف ping ين لكل خط

    def _on_wan_auto_toggle(self):
        self.settings["wan_auto"] = bool(self.v_wan_auto.get())
        self.settings["wan_auto_withdraw"] = bool(self.v_wan_auto_withdraw.get())
        self._save_settings()
        self._wan_schedule()

    def _wan_schedule(self):
        if self._wan_after is not None:
            try:
                self.after_cancel(self._wan_after)
            except Exception:
                pass
        if getattr(self, "_firebase_after", None) is not None:
            try:
                self.after_cancel(self._firebase_after)
            except Exception:
                pass
            self._wan_after = None
        if self.v_wan_auto.get():
            self._wan_after = self.after(self.WAN_AUTO_MS, self._wan_tick)

    def _wan_tick(self):
        self._wan_after = None
        try:
            if self.router.connected and not self._busy:
                self._wan_monitor_once()
        finally:
            self._wan_schedule()

    def _wan_monitor_once(self):
        """
        دورة مراقبة واحدة بلا نوافذ.

        الفحوص وحدها كل دقيقة، أمّا قياس السعة فكل WAN_BW_EVERY دورات لأنه
        يكلّف ping ين لكل خط. ودورة بلا قياس لا تُسقط تتابع الخط المخنوق
        ولا تعيده، فالقرار يُبنى على قياسات فعلية لا على غيابها.
        """
        self._quiet = True
        try:
            self._wan_ticks = getattr(self, "_wan_ticks", 0) + 1
            measured = self._wan_ticks % self.WAN_BW_EVERY == 0
            lines = self.on_check_lines(live=measured)
            if lines is None or not self.v_wan_auto_withdraw.get():
                return
            acted = []
            for ln in lines:
                gw = ln["gw"]
                rec = ln.get("withdrawn")
                # قرارات السعة لها دفتر تتابع منفصل: الفحوص تُقرأ كل دقيقة
                # والسعة كل خمس، فخلطهما في دفتر واحد يمحو تتابع السعة
                bw_case = bool(rec) and rec.get("health") == "throttled"
                kind, book = None, self._wan_streak
                if not rec and ln.get("route_state") == "Active":
                    if ln["health"] == "blocked":
                        kind = "bad"
                    elif ln["health"] == "throttled":
                        kind, book = "bad", self._wan_bw_streak
                elif rec and rec.get("reason") == "auto" and ln["health"] in ("ok", "slow"):
                    if not bw_case:
                        kind = "good"
                    elif measured and (ln.get("kbps") or 0) >= WAN_OK_KBPS:
                        # المخنوق لا يعود إلا بقياس يثبت تعافيه، لا بغياب القياس
                        kind, book = "good", self._wan_bw_streak
                if kind is None:
                    if measured or not (bw_case or self._wan_bw_streak.get(gw)):
                        self._wan_streak.pop(gw, None)
                        self._wan_bw_streak.pop(gw, None)
                    continue
                prev = book.get(gw, (kind, 0))
                count = prev[1] + 1 if prev[0] == kind else 1
                book[gw] = (kind, count)
                if count < self.WAN_STREAK:
                    continue
                try:
                    if kind == "bad":
                        if not self._other_working_lines(gw):
                            continue
                        throttled = ln["health"] == "throttled"
                        self._withdraw(ln, "auto")
                        acted.append(
                            (self.T["auto_withdrew_bw"] % {"line": self._wan_name(ln),
                                                           "bw": self._wan_mbps(ln)})
                            if throttled else self.T["auto_withdrew"] % self._wan_name(ln))
                    else:
                        restored_bw = bw_case
                        self._restore(ln)
                        acted.append(
                            (self.T["auto_restored_bw"] % {"line": self._wan_name(ln),
                                                           "bw": self._wan_mbps(ln)})
                            if restored_bw else self.T["auto_restored"] % self._wan_name(ln))
                except Exception as e:
                    self._status(self.T["auto_error"] % e, ok=False)
                    continue
                book.pop(gw, None)
                # الحالة تغيّرت؛ الخط التالي يُقيَّم على الصورة الجديدة
                ln["withdrawn"] = self.settings["withdrawn_lines"].get(gw)
                ln["route_state"] = "" if ln["withdrawn"] else "Active"
                classify_line(ln)
            if acted:
                self.on_check_lines(live=False)
                self._status("  ".join(acted), ok=False)
        finally:
            self._quiet = False

    def on_save_settings(self):
        firebase_was_configured = self.firebase.configured()
        self.settings["mac_shared_password"] = self.v_macpw.get().strip()
        self.settings["auto_save_config"] = bool(self.v_autosave.get())
        self.settings["ui_lang"] = self.v_lang.get()
        self.settings["firebase_api_key"] = self.v_firebase_key.get().strip()
        self.settings["firebase_project_id"] = self.v_firebase_project.get().strip()
        self.settings["firebase_email"] = self.v_firebase_email.get().strip()
        self.settings["firebase_password"] = self.v_firebase_password.get()
        if any(self.settings.get(k) for k in ("firebase_api_key", "firebase_project_id",
                                              "firebase_email", "firebase_password")) and not self.firebase.configured():
            save_settings(self.settings)
            messagebox.showwarning(APP_NAME, self.T["firebase_bad_config"])
            return
        if not firebase_was_configured and self.firebase.configured():
            save_settings(self.settings)
            self._firebase_first_sync()
            return
        self._save_settings()
        self._status("حُفظت الإعدادات / Settings saved")

    def on_firebase_sync_now(self):
        firebase_was_configured = self.firebase.configured()
        self.settings["firebase_api_key"] = self.v_firebase_key.get().strip()
        self.settings["firebase_project_id"] = self.v_firebase_project.get().strip()
        self.settings["firebase_email"] = self.v_firebase_email.get().strip()
        self.settings["firebase_password"] = self.v_firebase_password.get()
        if not self.firebase.configured():
            messagebox.showwarning(APP_NAME, self.T["firebase_bad_config"])
            return
        save_settings(self.settings)
        if not firebase_was_configured:
            self._firebase_first_sync()
        else:
            self._sync_firebase(quiet=False)

    # -- التصدير -------------------------------------------------------------

    def on_export(self, which):
        tv = {"devices": self.tv_dev, "portal": self.tv_por,
              "vlans": getattr(self, "tv_vlan", None)}.get(which, self.tv_por)
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile="ar730_%s_%s.csv" % (which, datetime.date.today()))
        if not path:
            return
        cols = tv["columns"]
        write_utf8_csv(path, [tv.heading(c)["text"] for c in cols],
                       [tv.item(iid, "values") for iid in tv.get_children()])
        self._status("صُدّر إلى / Exported to: %s" % path)

    def _on_close(self):
        if self._busy:
            messagebox.showinfo(APP_NAME, self.T["busy"])
            return
        if self._wan_after is not None:
            try:
                self.after_cancel(self._wan_after)
            except Exception:
                pass
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

class _DemoWan(object):
    """
    خطوط إنترنت وهمية بمخرجات منسوخة عن الجهاز الحقيقي حرفاً بحرف تقريباً.
    يحاكي ما ثبت عليه: المسار يُسحب عند فشل فحص ICMP المربوط فقط، وفحص TCP
    المربوط يُتجاهل. تستخدمه وضع التجربة ومجموعة الاختبار معاً.
    """

    def __init__(self, blocked_wan1=False, throttled_wan3=False):
        self.hostname = "AR730"
        # بوابة -> حالة الخط. kbps سعة الخط: منها يُحسب زمن الرزمة الكبيرة
        self.lines = {
            "192.168.1.1": {"iface": "GigabitEthernet0/0/9", "ip": "192.168.1.250",
                            "desc": "WAN1", "up": True, "icmp_ok": True,
                            "tcp_ok": not blocked_wan1, "rtt": 52, "loss": 0,
                            "speed": 100, "crc": 115, "probe": "149.112.112.112",
                            "kbps": 20000, "n": 1},
            "192.168.2.1": {"iface": "GigabitEthernet0/0/8", "ip": "192.168.2.250",
                            "desc": "WAN2", "up": False, "icmp_ok": True, "tcp_ok": True,
                            "rtt": 40, "loss": 0, "speed": 1000, "crc": 0,
                            "probe": "94.140.14.14", "kbps": 20000, "n": 2},
            # الخط المخنوق: كل فحوصه تنجح وزمنه الصغير ممتاز، ولا تفضحه إلا
            # الرزمة الكبيرة — كما على wan2 الحقيقي يوم 2026-09-16
            "192.168.3.1": {"iface": "GigabitEthernet0/0/10", "ip": "192.168.3.250",
                            "desc": "WAN3", "up": True, "icmp_ok": True, "tcp_ok": True,
                            "rtt": 56, "loss": 0, "speed": 1000, "crc": 0,
                            "probe": "9.9.9.9", "kbps": 180 if throttled_wan3 else 22000,
                            "n": 3},
            "192.168.4.1": {"iface": "Vlanif103", "phys": "GigabitEthernet0/0/3",
                            "ip": "192.168.4.250", "desc": "WAN4", "up": True,
                            "icmp_ok": True, "tcp_ok": True, "rtt": 44, "loss": 0,
                            "speed": 1000, "crc": 0, "probe": "8.8.4.4",
                            "kbps": 20000, "n": 4},
        }
        self.routes = []
        for gw, ln in sorted(self.lines.items()):
            self.routes.append("ip route-static 0.0.0.0 0.0.0.0 %s track nqa admin w%dicmp"
                               % (gw, ln["n"]))
        for gw, ln in sorted(self.lines.items()):
            self.routes.append("ip route-static %s 255.255.255.255 %s" % (ln["probe"], gw))
        self.routes.append("ip route-static vpn-instance OPENSSHLINKVPORT 0.0.0.0 0.0.0.0 "
                           "192.168.4.1 public")
        self.test_no = 40
        self.commands = []

    # -- أدوات ----------------------------------------------------------------
    def _line_by_test(self, name):
        m = re.match(r"w(\d+)(icmp|tcp)$", name)
        if not m:
            return None, None
        for gw, ln in self.lines.items():
            if ln["n"] == int(m.group(1)):
                return gw, dict(ln, kind=m.group(2))
        return None, None

    def _default_routes(self):
        out = {}
        for r in self.routes:
            m = re.match(r"ip route-static 0\.0\.0\.0 0\.0\.0\.0 (\S+)(?: track nqa (\S+) (\S+))?$", r)
            if m:
                out[m.group(1)] = (m.group(2), m.group(3)) if m.group(2) else None
        return out

    def _route_active(self, gw, track):
        ln = self.lines.get(gw)
        if not ln or not ln["up"]:
            return False
        if track and track[1].endswith("icmp"):
            return ln["icmp_ok"]
        return True           # فحص TCP المربوط يُتجاهل كما على الجهاز

    # -- الأوامر ---------------------------------------------------------------
    def run(self, cmd, view):
        """يعيد المخرجات، أو None إن لم يكن الأمر من اختصاص الخطوط."""
        self.commands.append((view, cmd))
        if cmd.startswith("ip route-static ") or cmd.startswith("undo ip route-static "):
            if view != "system":
                return "Error: Unrecognized command found at '^' position."
            if cmd.startswith("undo "):
                gw = cmd.split()[-1]
                before = len(self.routes)
                self.routes = [r for r in self.routes
                               if not r.startswith("ip route-static 0.0.0.0 0.0.0.0 %s" % gw)]
                return "" if len(self.routes) < before else \
                    "Error: The static route does not exist."
            gw = cmd.split()[4]
            self.routes = [r for r in self.routes
                           if not r.startswith("ip route-static 0.0.0.0 0.0.0.0 %s" % gw)]
            self.routes.insert(0, cmd)
            return ""
        if cmd.startswith("ping ") and "-nexthop" in cmd:
            return self._ping(cmd)
        if cmd == "display current-configuration | include ip route-static":
            return "\n".join(self.routes)
        if cmd == "display ip routing-table 0.0.0.0 0 verbose":
            return self._routing_table()
        if cmd == "display current-configuration configuration nqa":
            return self._nqa_config()
        if cmd == "display ip interface brief":
            return self._ip_brief()
        if cmd.startswith("display nqa results test-instance "):
            return self._nqa_results(cmd.split()[-1])
        if cmd.startswith("display interface "):
            return self._interface(cmd.split()[-1])
        if cmd.startswith("display vlan "):
            return self._vlan(cmd.split()[-1])
        return None

    def _routing_table(self):
        routes = self._default_routes()
        out = ["Route Flags: R - relay, D - download to fib, T - to vpn-instance",
               "-" * 78, "Routing Table : Public", "Summary Count : %d" % len(routes), ""]
        for gw, track in routes.items():
            ln = self.lines.get(gw, {})
            active = self._route_active(gw, track)
            out += ["Destination: 0.0.0.0/0",
                    "     Protocol: Static           Process ID: 0",
                    "   Preference: 60                     Cost: 0",
                    "      NextHop: %-15s Neighbour: 0.0.0.0" % gw,
                    "        State: %-22s Age: 00h10m01s" % ("Active Adv Relied" if active
                                                             else "Invalid Adv"),
                    "          Tag: 0                  Priority: medium",
                    " RelayNextHop: 0.0.0.0           Interface: %s"
                    % (ln.get("iface") if ln.get("up") else "Unknown"),
                    "     TunnelID: 0x0                   Flags: %s" % ("RD" if active else ""),
                    ""]
        return "\n".join(out)

    def _nqa_config(self):
        out = ["[V300R024C00SPC100]", "#"]
        for gw, ln in sorted(self.lines.items(), key=lambda x: x[1]["n"]):
            for kind in ("icmp", "tcp"):
                out += ["nqa test-instance admin w%d%s" % (ln["n"], kind),
                        " test-type %s" % kind,
                        " destination-address ipv4 %s" % ln["probe"]]
                if kind == "tcp":
                    out.append(" destination-port 443")
                out += [" frequency %d" % (15 if kind == "icmp" else 10), " timeout 2",
                        " start now"]
        return "\n".join(out + ["#", "return"])

    def _ip_brief(self):
        out = ["*down: administratively down", "",
               "Interface                         IP Address/Mask      Physical   Protocol  "]
        for gw, ln in sorted(self.lines.items()):
            st = "up" if ln["up"] else "down"
            out.append("%-33s %-20s %-10s %-10s" % (ln["iface"], ln["ip"] + "/24", st, st))
        out.append("Vlanif1                           10.0.1.1/24          up         up        ")
        out.append("Vlanif10                          10.0.10.1/24         up         up        ")
        out.append("Vlanif20                          10.0.20.1/23         up         up        ")
        out.append("XGigabitEthernet0/0/0             unassigned           up         down      ")
        out.append("XGigabitEthernet0/0/0.70          10.0.70.1/24         up         up        ")
        return "\n".join(out)

    def _nqa_results(self, name):
        gw, ln = self._line_by_test(name)
        if ln is None:
            return "Error: The test instance does not exist."
        # منفذ مفصول: مسار /32 غير صالح، فيخرج الفحص من خط آخر وينجح — كما رأينا
        ok = (ln["icmp_ok"] if ln["kind"] == "icmp" else ln["tcp_ok"]) if ln["up"] else True
        out = ["", " NQA entry(admin, %s) :testflag is active ,testtype is %s " % (name, ln["kind"])]
        for i in range(3):
            self.test_no += 1
            recv = 3 if ok else 0
            t = ln["rtt"] if ok else 0
            out += ["  %d . Test %d result   The test is finished" % (i + 1, self.test_no),
                    "   Send operation times: 3              Receive response times: %d" % recv,
                    "   Completion:%-25s RTD OverThresholds number: 0"
                    % ("success" if ok else "failed"),
                    "   Destination ip address:%s" % ln["probe"],
                    "   Min/Max/Average Completion Time: %d/%d/%d" % (t, t, t),
                    "   Last Good Probe Time: 2026-09-14 17:25:03.6",
                    "   Lost packet ratio: %d %%" % (0 if ok else 100)]
        return "\n".join(out)

    def _interface(self, name):
        for gw, ln in self.lines.items():
            if name == ln["iface"] and ln.get("phys"):
                return "\n".join([
                    "%s current state : %s" % (name, "UP" if ln["up"] else "DOWN"),
                    "Line protocol current state : %s" % ("UP" if ln["up"] else "DOWN"),
                    "Description:%s" % ln["desc"],
                    "Route Port,The Maximum Transmit Unit is 1500",
                    "Internet Address is %s/24" % ln["ip"],
                    "    Input bandwidth utilization  : --"])
            if name in (ln["iface"], ln.get("phys")):
                up = "UP" if ln["up"] else "DOWN"
                return "\n".join([
                    "%s current state : %s" % (name, up),
                    "Line protocol current state : %s" % up,
                    "Description:%s" % (ln["desc"] + ("-PORT" if ln.get("phys") else "")),
                    "Last physical up time   : 2026-09-14 16:13:08 UTC+02:00",
                    "Last physical down time : 2026-09-14 16:12:39 UTC+02:00",
                    "Current system time: 2026-09-14 16:21:39+02:00",
                    "Port Mode: AUTO COPPER",
                    "Speed :  %d,  Loopback: NONE" % ln["speed"],
                    "Duplex: FULL,  Negotiation: ENABLE",
                    "Last 300 seconds input rate 180240 bits/sec, 44 packets/sec",
                    "Last 300 seconds output rate 77312 bits/sec, 40 packets/sec",
                    "", "Input:  2065856 packets, 262452113 bytes",
                    "  Discard:                  0,  Total Error:               %d" % (ln["crc"] * 2),
                    "", "  CRC:                    %d,  Giants:                      0" % ln["crc"],
                    "", "Output:  4755263 packets, 2067708560 bytes",
                    "  Discard:                  0,  Total Error:                 0"])
        return "Error: Wrong parameter found at '^' position."

    def _vlan(self, vid):
        for gw, ln in self.lines.items():
            if ln["iface"] == "Vlanif" + vid and ln.get("phys"):
                return "\n".join([
                    "VLAN ID Type         Status   MAC Learning Broadcast/Multicast/Unicast Property ",
                    "%-7s common       enable   enable       forward   forward   forward default  " % vid,
                    "-------------------",
                    "Untagged      Port: %s        " % ln["phys"],
                    "-------------------",
                    "Active Untag  Port: %s        " % ln["phys"]])
        return "Error: The VLAN does not exist."

    def _ping(self, cmd):
        parts = cmd.split()
        gw = parts[parts.index("-nexthop") + 1]
        dest = parts[-1]
        count = int(parts[parts.index("-c") + 1]) if "-c" in parts else 5
        size = int(parts[parts.index("-s") + 1]) if "-s" in parts else 56
        ln = self.lines.get(gw)
        ok = bool(ln and ln["up"] and ln["icmp_ok"])
        recv = int(round(count * (100 - ln["loss"]) / 100.0)) if ok else 0
        # زمن دفع البايتات الزائدة ذهاباً وإياباً: bits ÷ kbps = ms
        rtt = ln["rtt"] + int(2.0 * (size - 56) * 8 / ln["kbps"]) if ok else 0
        out = ["  PING %s: %d  data bytes, press CTRL_C to break" % (dest, size)]
        for i in range(count):
            out.append("    Reply from %s: bytes=%d Sequence=%d ttl=116 time=%d ms"
                       % (dest, size, i + 1, rtt) if i < recv else "    Request time out")
        out += ["", "  --- %s ping statistics ---" % dest,
                "    %d packet(s) transmitted" % count,
                "    %d packet(s) received" % recv,
                "    %.2f%% packet loss" % (100.0 * (count - recv) / count)]
        if recv:
            out.append("    round-trip min/avg/max = %d/%d/%d ms"
                       % (rtt - 4, rtt, rtt + 2))
        return "\n".join(out)


class _Vid(object):
    """بديل نتيجة مطابقة قديمة: group(1) هو رقم الشبكة مهما كان اسم واجهتها."""

    def __init__(self, vid):
        self._vid = vid

    def group(self, _n):
        return self._vid


class _DemoMgmt(object):
    """
    ما يخص أجهزة الإدارة على راوتر وهمي: قوائم ACL الأساسية، وربط DHCP،
    وARP الثابت، وقيود الويب. المخرجات منسوخة عن الجهاز الحقيقي
    (V300R024C00SPC100). يتشاركه وضع التجربة ومجموعة الاختبار.
    """

    def __init__(self):
        # vid -> (عنوان، طول، مصادقة، منافذ)
        self.nets = {"1": ("10.0.1.1", 24, False, ["GigabitEthernet0/0/1"]),
                     "10": ("10.0.10.1", 24, True, ["GigabitEthernet0/0/2"]),
                     "20": ("10.0.20.1", 23, True, ["GigabitEthernet0/0/2"])}
        self.acls = {
            "2999": {"desc": "MGMT-ACCESS",
                     "rules": {5: "permit source 10.0.1.0 0.0.0.255",
                               10: "permit source 10.0.10.0 0.0.0.255", 3000: "deny"}},
            "2001": {"desc": "", "rules": {5: "permit source 10.0.30.0 0.0.0.255"}},
        }
        self.vty_acl = "2999"
        self.http_acl = None
        self.http_permit = ["Vlanif1"]
        self.binds = {}             # vid -> {عنوان: (ماك مفصول، وصف)}
        self.arp = {}               # عنوان -> (ماك، vid، منفذ)
        self.leases = {"20": {"10.0.20.166": "0000-5e00-5302", "10.0.21.254": "0000-5e00-5362"}}
        # شبكة الإدارة مثل الجهاز الحقيقي: مجمّعها ضيّق بعد استبعاد أكثره،
        # وفيها جهاز يحمل عنواناً في شبكته الأصلية أيضاً — أثر تسرّبها
        # غير موسومة عبر وصلة التبديل (docs/router/lessons-learned.md#L16)
        self.excluded = {"1": 232}
        self.leases["1"] = dict(("10.0.1.%d" % n, "0000-5e00-53%02d" % (n + 10))
                                for n in range(10, 31))
        self.leases["1"]["10.0.1.10"] = "0000-5e00-5302"
        self.dyn_arp = {"20": {"0000-5e00-5302": ("10.0.20.166", "GE0/0/2")}}
        # شبكات موجودة بلا واجهة عنونة — الجهاز الحقيقي فيه ثمان منها
        self.l2_vlans = {"30": ["GigabitEthernet0/0/4"], "40": [],
                         "50": ["GigabitEthernet0/0/5"]}
        # شبكة موجَّهة: تصل موسومة وتُنهى على واجهة فرعية، فلا منفذ لها ولا
        # أثر في جدول العناوين الفيزيائية — أجهزتها تُعرف من ARP وحده
        self.subifs = {"70": "XGigabitEthernet0/0/0.70"}
        self.nets["70"] = ("10.0.70.1", 24, False, [])
        self.leases["70"] = {"10.0.70.100": "0000-5e00-5375",
                             "10.0.70.101": "0000-5e00-5376"}
        self.dyn_arp["70"] = {"0000-5e00-5375": ("10.0.70.100", "XGE0/0/0.70"),
                              "0000-5e00-5377": ("10.0.70.130", "XGE0/0/0.70")}
        # جدول العناوين الفيزيائية: (ماك، vid، منفذ). هو وحده يرى جهازاً بلا عنوان
        self.mac_table = [("0000-5e00-5302", "20", "GigabitEthernet0/0/2"),
                          ("0000-5e00-5362", "20", "GigabitEthernet0/0/2"),
                          ("0000-5e00-5371", "20", "GigabitEthernet0/0/2"),
                          ("0000-5e00-5372", "20", "GigabitEthernet0/0/2"),
                          ("0000-5e00-5373", "1", "GigabitEthernet0/0/1"),
                          ("0000-5e00-5374", "30", "GigabitEthernet0/0/4")]
        self.fail_on = {}           # بداية أمر -> رسالة خطأ، لمحاكاة رفض الراوتر
        self.commands = []

    def _vid_of(self, iface):
        """رقم الشبكة من اسم واجهتها: Vlanif20 أو واجهة فرعية بـ dot1q."""
        for vid, name in self.subifs.items():
            if name == iface:
                return vid
        m = re.match(r"^Vlanif(\d+)$", iface or "")
        if m and m.group(1) in self.nets and m.group(1) not in self.subifs:
            return m.group(1)
        return None

    @staticmethod
    def _vid(iface):
        m = re.match(r"^Vlanif(\d+)$", iface or "")
        return m.group(1) if m else None

    def run(self, cmd, dev):
        """يعيد المخرجات، أو None إن لم يكن الأمر من اختصاصه."""
        view, sub = dev.view, getattr(dev, "sub", "")
        for prefix, err in self.fail_on.items():
            if cmd.startswith(prefix):
                self.commands.append((view, cmd))
                return err
        if cmd.startswith("interface ") and view in ("system", "sub"):
            vid = self._vid(cmd.split()[1])
            if vid not in self.nets:
                return None
            dev.view, dev.sub = "sub", cmd.split()[1]
            return ""
        if cmd.startswith("acl number ") and view in ("system", "sub"):
            no = cmd.split()[2]
            self.acls.setdefault(no, {"desc": "", "rules": {}})
            dev.view, dev.sub = "sub", "acl-basic-" + no
            return ""
        m = re.match(r"^reset ip pool interface Vlanif(\d+) (\S+)$", cmd)
        if m:
            self.commands.append((view, cmd))
            if view != "user":
                return "Error: Unrecognized command found at '^' position."
            if not self.leases.get(m.group(1), {}).pop(m.group(2), None):
                return "Error: The IP address is not used."
            return ""
        if re.match(r"^(undo )?(dhcp server static-bind|rule |arp static|http (acl|server permit))", cmd):
            self.commands.append((view, cmd))
            return self._config(cmd, view, sub)
        if cmd.startswith("display "):
            return self._display(cmd)
        return None

    def _config(self, cmd, view, sub):
        bad = "Error: Unrecognized command found at '^' position."
        undo = cmd.startswith("undo ")
        body = cmd[5:] if undo else cmd
        if body.startswith("dhcp server static-bind"):
            vid = self._vid(sub) if view == "sub" else None
            if vid is None:
                return bad
            binds = self.binds.setdefault(vid, {})
            if undo:
                m = re.match(r"dhcp server static-bind ip-address (\S+)$", body)
                if not m:
                    # كما على الجهاز الحقيقي: الحذف بالعنوان وحده
                    return "Error:Too many parameters found at '^' position."
                if m.group(1) not in binds:
                    return "Error: The static bind does not exist."
                del binds[m.group(1)]
                return ""
            m = re.match(r"dhcp server static-bind ip-address (\S+) mac-address (\S+)(?: description (\S+))?$", body)
            if not m:
                return "Error: Incomplete command found at '^' position."
            ip, mac, desc = m.groups()
            gw, length, _, _ = self.nets[vid]
            if not ip_in_subnet(ip, gw, length):
                return "Error: The IP address is not in the address pool."
            holder = self.leases.get(vid, {}).get(ip)
            if any(lmac == mac and lip != ip for lip, lmac in self.leases.get(vid, {}).items()):
                return "Error: This MAC address uses another IP address in the ip pool."
            if holder and holder != mac or ip in binds:
                return "Error: The IP address has been used."
            binds[ip] = (mac, desc or "")
            return ""
        if body.startswith("rule ") or body.startswith("rule"):
            if view != "sub" or not sub.startswith("acl-basic-"):
                return bad
            acl = self.acls[sub[len("acl-basic-"):]]
            parts = body.split()
            if len(parts) < 2 or not parts[1].isdigit():
                return "Error: Incomplete command found at '^' position."
            rid = int(parts[1])
            if undo:
                if rid not in acl["rules"]:
                    return "Error: The rule does not exist."
                del acl["rules"][rid]
                return ""
            acl["rules"][rid] = " ".join(parts[2:])
            return ""
        if body.startswith("arp static"):
            if view != "system":
                return bad
            parts = body.split()
            if undo:
                if len(parts) < 3 or parts[2] not in self.arp:
                    return "Error: The ARP entry does not exist."
                del self.arp[parts[2]]
                return ""
            m = re.match(r"arp static (\S+) (\S+)(?: vid (\d+)(?: interface (\S+))?)?$", body)
            if not m:
                return "Error: Incomplete command found at '^' position."
            ip, mac, vid, port = m.groups()
            if vid and not port:
                return "Error: Incomplete command found at '^' position."
            self.arp[ip] = (mac, vid or "", port or "")
            return ""
        if body.startswith("http acl"):
            if view != "system":
                return bad
            self.http_acl = None if undo else body.split()[2]
            return ""
        if body.startswith("http server permit interface"):
            if view != "system":
                return bad
            self.http_permit = None if undo else body.split()[4:]
            return ""
        return bad

    def _display(self, cmd):
        if cmd == "display acl all":
            out = []
            for no in sorted(self.acls):
                a = self.acls[no]
                out.append("Basic ACL %s, %d rules" % (no, len(a["rules"])))
                if a["desc"]:
                    out.append(a["desc"])
                out.append("Acl's step is 5")
                for rid in sorted(a["rules"]):
                    out.append(" rule %d %s (%d matches)" % (rid, a["rules"][rid], rid % 7))
                out.append("")
            out += ["Advanced ACL 3010, 2 rules", "MANAGERS", "Acl's step is 5",
                    " rule 3 permit ip destination 10.0.255.1 0 ", " rule 3000 permit ip ", ""]
            return "\n".join(out)
        if cmd == "display current-configuration | include acl":
            out = ["acl number %s" % no for no in sorted(self.acls)]
            out.append(" acl-id 3010")
            if self.http_acl:
                out.append(" http acl %s" % self.http_acl)
            out += [" acl %s inbound" % self.vty_acl, " acl %s inbound" % self.vty_acl]
            return "\n".join(out)
        if cmd == "display current-configuration | include http":
            out = ["portal local-server http port 8080",
                   " local-user admin service-type terminal ssh http",
                   " http secure-server ssl-policy default_policy",
                   " http server enable", " http secure-server enable"]
            if self.http_permit:
                out.append(" http server permit interface %s" % " ".join(self.http_permit))
            if self.http_acl:
                out.append(" http acl %s" % self.http_acl)
            return "\n".join(out)
        if cmd == "display current-configuration | include static-bind":
            return "\n".join(
                " dhcp server static-bind ip-address %s mac-address %s%s"
                % (ip, mac, " description %s" % desc if desc else "")
                for vid in sorted(self.binds) for ip, (mac, desc) in sorted(self.binds[vid].items()))
        if cmd == "display current-configuration | include arp static":
            return "\n".join("arp static %s %s%s" % (ip, mac, " vid %s interface %s" % (vid, port)
                                                     if vid else "")
                             for ip, (mac, vid, port) in sorted(self.arp.items()))
        m = re.match(r"^display current-configuration interface (\S+)$", cmd)
        vid = self._vid_of(m.group(1)) if m else None
        if vid:
            gw, length, nac, _ = self.nets[vid]
            mask = _int_ip((0xffffffff << (32 - length)) & 0xffffffff)
            out = ["[V300R024C00SPC100]", "#", "interface %s" % m.group(1)]
            if vid in self.subifs:
                out.append(" dot1q termination vid %s" % vid)
            out.append(" ip address %s %s" % (gw, mask))
            if nac:
                out.append(" authentication-profile p_nac")
            out.append(" dhcp select interface")
            for ip, (mac, desc) in sorted(self.binds.get(vid, {}).items()):
                out.append(" dhcp server static-bind ip-address %s mac-address %s" % (ip, mac))
            return "\n".join(out + ["#", "return"])
        m = re.match(r"^display ip pool interface (\S+) used$", cmd)
        vid = self._vid_of(m.group(1)) if m else None
        if vid:
            m = _Vid(vid)
            gw, length, _, _ = self.nets[vid]
            lo, hi = subnet_bounds(gw, length)
            leases = self.leases.get(m.group(1), {})
            total = hi - lo - 1
            # المستبعَد بـ excluded-ip-address يُعدّ Disabled ولا يُحسب متاحاً
            off = self.excluded.get(m.group(1), 0)
            out = ["  Pool-name        : Vlanif%s" % m.group(1),
                   "  Network          : %s" % _int_ip(lo),
                   "  Address Statistic: Total       :%-10d Used        :%-10d"
                   % (total, len(leases)),
                   "                     Idle        :%-10d Expired     :0         "
                   % (total - len(leases) - off),
                   "                     Conflict    :0          Disabled    :%-10d" % off, ""]
            # مجمّع بلا عقود لا يطبع الجدول أصلاً (docs/router/captures/05-vlan-clients.txt)
            if not leases:
                return "\n".join(out)
            out += [" " + "-" * 85, "  Network section ",
                   "         Start           End       Total    Used Idle(Expired) Conflict Disabled",
                   " " + "-" * 85,
                   "       %s     %s     %d      %d        %d(0)       0     0"
                   % (_int_ip(lo + 1), _int_ip(hi - 1), total, len(leases),
                      total - len(leases)),
                   " " + "-" * 85,
                   "  Index              IP             Client-ID    Type       Left   Status           ",
                   " " + "-" * 85]
            for i, (ip, mac) in enumerate(sorted(leases.items(),
                                                 key=lambda x: _ip_int(x[0]))):
                out.append("    %3d     %11s        %s    DHCP     527035   Used             "
                           % (_ip_int(ip) - lo - 1, ip, mac))
            return "\n".join(out + [" " + "-" * 85])
        m = re.match(r"^display arp interface (\S+)$", cmd)
        vid = self._vid_of(m.group(1)) if m else None
        if vid:
            iface = m.group(1)
            m = _Vid(vid)
            gw = self.nets[vid][0]
            out = ["IP ADDRESS      MAC ADDRESS     EXPIRE(M) TYPE        INTERFACE   VPN-INSTANCE ",
                   "                                    VLAN/CEVLAN(SIP/DIP)      PVC",
                   "-" * 78, "%-15s 0000-5e00-5300            I -         %-14s "
                   % (gw, iface)]
            for mac, (ip, port) in sorted(self.dyn_arp.get(m.group(1), {}).items()):
                out += ["%-15s %s  17        D-0         %s        " % (ip, mac, port),
                        "                                            %s/-      " % m.group(1)]
            return "\n".join(out + ["-" * 78])
        if cmd == "display vlan":
            out = ["* : management-vlan", "-" * 21,
                   "The total number of vlans is : %d" % (len(self.nets) + len(self.l2_vlans)),
                   "VLAN ID Type         Status   MAC Learning "
                   "Broadcast/Multicast/Unicast Property ", "-" * 80]
            for vid in sorted(list(self.nets) + list(self.l2_vlans), key=int):
                out.append("%-7s common       enable   enable       "
                           "forward   forward   forward default  " % vid)
            return "\n".join(out)
        if cmd == "display mac-address":
            out = ["-" * 110,
                   "MAC Address       VLAN/Bridge/VSI/BD      Learned-From"
                   "               Type      Vpn                            ", "-" * 110]
            for mac, vid, port in sorted(self.mac_table, key=lambda r: (int(r[1]), r[0])):
                out.append("%s   %8s              %-26s dynamic   public"
                           % (mac, vid + "/-/-/-", port))
            return "\n".join(out + ["", "-" * 110,
                                    "Total items displayed = %d" % len(self.mac_table), ""])
        m = re.match(r"^display vlan (\d+)$", cmd)
        if m and m.group(1) in self.l2_vlans:
            ports = self.l2_vlans[m.group(1)]
            head = ["VLAN ID Type         Status   MAC Learning "
                    "Broadcast/Multicast/Unicast Property ",
                    "%-7s common       enable   enable       "
                    "forward   forward   forward default  " % m.group(1)]
            if not ports:
                return "\n".join(head)
            return "\n".join(head + ["-" * 19, "Untagged      Port: %s" % " ".join(ports)])
        m = re.match(r"^display vlan (\d+)$", cmd)
        if m and m.group(1) in self.nets:
            ports = self.nets[m.group(1)][3]
            if not ports:
                return "\n".join([
                    "VLAN ID Type         Status   MAC Learning "
                    "Broadcast/Multicast/Unicast Property ",
                    "%-7s common       enable   enable       "
                    "forward   forward   forward default  " % m.group(1)])
            return "\n".join([
                "VLAN ID Type         Status   MAC Learning Broadcast/Multicast/Unicast Property ",
                "%-7s common       enable   enable       forward   forward   forward default  "
                % m.group(1), "-" * 19,
                "Tagged        Port: %s" % " ".join(ports), "-" * 19,
                "Active Tag    Port: %s" % " ".join(ports)])
        return None


class _DemoDevice(object):
    def __init__(self):
        self.hostname = "AR730-DEMO"
        self.view = "user"
        self.groups = {"grp_managers": "3010", "grp_staff": "3020", "grp_infra": "3030"}
        self.users = {
            "admin": {"types": {"ssh", "http", "terminal"}, "group": None, "pw": True, "priv": 15},
            "00005e005302": {"types": {"8021x"}, "group": "grp_managers", "pw": True},
            # محظور عمداً: كلمة سره لا تطابق الملف — للتدرّب على فكّ الحظر
            "00005e005303": {"types": {"8021x"}, "group": "grp_infra", "pw": True,
                             "state": "B"},
            "sara": {"types": {"web"}, "group": "grp_staff", "pw": True},
        }
        self.profiles = {"m_wl": "Demo-Shared-2026"}
        self.profile = None
        # WAN1 محجوب عمداً: ping يعمل وHTTPS لا — للتدرّب على كشف انتهاء الحصة
        self.wan = _DemoWan(blocked_wan1=True, throttled_wan3=True)
        self.wan.hostname = self.hostname
        self.mgmt = _DemoMgmt()
        self.sub = ""
        self.online = [
            {"id": "1032", "user": "00005e005302", "ip": "10.0.20.166",
             "mac": "0000-5e00-5302", "status": "Success"},
            {"id": "1027", "user": "00005e005301", "ip": "10.0.21.207",
             "mac": "0000-5e00-5301", "status": "Pre-authen"},
            {"id": "1035", "user": "sara", "ip": "10.0.20.88",
             "mac": "3e4b-91aa-02d1", "status": "Success"},
        ]

    def prompt(self):
        if self.view == "macprof":
            return "[%s-mac-access-profile-%s]" % (self.hostname, self.profile)
        if self.view == "sub":
            return "[%s-%s]" % (self.hostname, self.sub)
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
            self.view = {"aaa": "system", "macprof": "system", "sub": "system",
                         "system": "user", "user": "user"}[self.view]
            return ""
        if cmd == "return":
            self.view = "user"; return ""
        mg = self.mgmt.run(cmd, self)
        if mg is not None:
            return mg
        if cmd.startswith("mac-access-profile name ") and self.view == "system":
            self.profile = cmd.split()[2]
            self.profiles.setdefault(self.profile, None)
            self.view = "macprof"; return ""
        if cmd.startswith("mac-authen ") and self.view == "macprof":
            self.profiles[self.profile] = cmd.split()[-1]
            return "Info: The password should meet the complexity check requirement."
        if cmd.startswith("screen-length"):
            return ""
        if cmd == "save":
            return "__SAVE__"
        wan = self.wan.run(cmd, self.view)
        if wan is not None:
            return wan
        if cmd.startswith("display "):
            return self._display(cmd)
        if cmd.startswith("cut access-user"):
            if self.view != "aaa":
                return "Error: Unrecognized command found at '^' position."
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
        if rest and rest[0] == "state" and len(rest) > 1:
            u = self.users.get(name)
            if u is None:
                return "Error: The user does not exist."
            u["state"] = "B" if rest[1] == "block" else "A"; return ""
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
        if cmd.startswith("display current-configuration configuration mac-access-profile"):
            b = ["[V300R024C00SPC100]", "#"]
            for name in sorted(self.profiles):
                b.append("mac-access-profile name %s" % name)
                if self.profiles[name]:
                    b.append(" mac-authen username macaddress format without-hyphen "
                             "password cipher %%^%%#%08x%%^%%#"
                             % (zlib.crc32(self.profiles[name].encode()) & 0xffffffff))
            return "\n".join(b + ["#", "return"])
        if cmd.strip() == "display local-user":
            r = ["  " + "-" * 76,
                 "  User-name                      State  AuthMask  AdminLevel",
                 "  " + "-" * 76]
            for name in sorted(self.users):
                u = self.users[name]
                r.append("  %-30s %-6s %-9s %d" % (name, u.get("state", "A"), "X",
                                                   u.get("priv", 0)))
            r += ["  " + "-" * 76, "  Total %d user(s)" % len(self.users)]
            return "\n".join(r)
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
    """نقطة توافق للأوامر القديمة: تشغّل واجهة Qt الرسمية فقط."""
    from ar730_qt import main as qt_main
    qt_main()


if __name__ == "__main__":
    main()
