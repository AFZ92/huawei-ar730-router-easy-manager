# -*- coding: utf-8 -*-
"""اختبار شامل لواجهة Qt ومحاكي الراوتر، بلا عتاد أو اتصال شبكي."""
import copy
import os
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

WORK = tempfile.mkdtemp(prefix="ar730qt_")
APPDIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for filename in ("ar730_manager.py", "ar730_qt.py", "release_update.py"):
    shutil.copy(os.path.join(APPDIR, filename), WORK)
shutil.copytree(os.path.join(APPDIR, "data"), os.path.join(WORK, "data"))
shutil.copytree(os.path.join(APPDIR, "assets"), os.path.join(WORK, "assets"))
sys.path.insert(0, WORK)

from PySide6.QtGui import QColor, QFontMetrics  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QPushButton  # noqa: E402
import ar730_qt as qt  # noqa: E402


FAILS = []


def check(label, condition, detail=""):
    if not condition:
        FAILS.append(label + ((" — " + detail) if detail else ""))
    print(("  ✓ " if condition else "  ✗ ") + label + (("   [" + detail + "]") if detail else ""))


def snapshot(device):
    """لقطة من بيانات الراوتر للتحقق من عدم تغيّر عمليات القراءة لها."""
    return copy.deepcopy({
        "users": device.users,
        "profiles": device.profiles,
        "mgmt": device.mgmt.__dict__,
        "online": device.online,
    })


app = QApplication.instance() or QApplication([])

print("١ — واجهة Qt الرسمية")
controller = qt.ReadController(demo=True)
controller.connect("demo", 22, "admin", "anything")
before = snapshot(qt.legacy._DemoParamiko.device)
controller.refresh()
after = snapshot(qt.legacy._DemoParamiko.device)
check("التحديث لا يغير بيانات الراوتر التجريبي", before == after)
check("التحديث يجلب حالة الحساب المحظور", controller.states.get("00005e005303") == "B")

window = qt.MainWindow(controller, demo=True)
window.show()
app.processEvents()
check("الإنجليزية هي لغة Qt الافتراضية", window.lang == "en")
check("واجهة الإنجليزية LTR", window.layoutDirection() == qt.Qt.LeftToRight)
check("أيقونة AFZ محمّلة للتطبيق", not window.windowIcon().isNull())
afz_logo = window.findChild(QLabel, "afzLogo")
afz_credit = window.findChild(QLabel, "afzCredit")
check("شعار AFZ يحافظ على نسبة أبعاده", afz_logo is not None and afz_logo.pixmap() is not None
      and afz_logo.pixmap().width() == 70
      and abs((afz_logo.pixmap().width() / afz_logo.pixmap().height()) - (3900 / 2864)) < 0.02)
check("اسم AFZ بعرض الشعار وتحته", afz_logo is not None and afz_credit is not None
      and afz_credit.text() == "AFZ Systems" and afz_credit.width() >= afz_logo.width()
      and afz_credit.y() > afz_logo.y())
check("اسم AFZ تسمية هادئة أسفل الشعار", afz_credit is not None
      and afz_credit.font().pixelSize() == 9
      and QFontMetrics(afz_credit.font()).horizontalAdvance(afz_credit.text()) <= afz_credit.width())
check("حالة الاتصال تحت اسم AFZ", afz_credit is not None and window.connection.y() > afz_credit.y())
guide_text = [label.text() for label in window.findChildren(QLabel)]
check("دليل التطبيق يشرح أمر تثبيت Windows", any("install.ps1" in text for text in guide_text))
check("دليل التطبيق يشرح أمر تثبيت macOS", any("install.sh" in text for text in guide_text))
check("دليل التطبيق يعرض رقم الإصدار", any(qt.legacy.APP_VERSION in text for text in guide_text))
english_text = []
for widget_type in (QLabel, QPushButton, QCheckBox):
    for widget in window.findChildren(widget_type):
        if any("\u0600" <= char <= "\u06ff" for char in widget.text()):
            english_text.append(widget.text())
check("لا يبقى نص عربي مرئي في الواجهة الإنجليزية", not english_text, ", ".join(sorted(set(english_text))))
check("كل صفحات التطبيق والدليل مرئية في الشريط", len(window.nav) == len(qt.APP_PAGES) + 2)
check("جميع جداول الواجهة ظاهرة", set(window.tables) == {"devices", "portal", "online", "vlans", "management", "wan", "groups"})
window.stack.setCurrentIndex(1)
app.processEvents()
check("زر تحديث الأجهزة ظاهر", hasattr(window, "refresh_devices") and window.refresh_devices.isVisible())
window.stack.setCurrentIndex(2)
app.processEvents()
check("زر تعديل حسابات البوابة ظاهر", hasattr(window, "edit_portal") and window.edit_portal.isVisible())
check("زر تصدير حسابات البوابة ظاهر", hasattr(window, "export_portal") and window.export_portal.isVisible())
check("زر تحديث حسابات البوابة ظاهر", hasattr(window, "refresh_portal") and window.refresh_portal.isVisible())
check("زر إضافة حساب بوابة ظاهر", hasattr(window, "add_portal") and window.add_portal.isVisible())
check("زر تغيير كلمة مرور البوابة ظاهر", hasattr(window, "reset_portal_password")
      and window.reset_portal_password.isVisible())
check("زر تغيير مجموعة البوابة ظاهر", hasattr(window, "change_portal_group")
      and window.change_portal_group.isVisible())
check("زر حذف حساب البوابة ظاهر", hasattr(window, "revoke_portal") and window.revoke_portal.isVisible())
window.stack.setCurrentIndex(3)
app.processEvents()
check("زر تحديث المتصلين ظاهر", hasattr(window, "refresh_online") and window.refresh_online.isVisible())
check("زر فصل المتصل ظاهر", hasattr(window, "disconnect_online") and window.disconnect_online.isVisible())
check("زر إضافة المتصل للموثوقة ظاهر", hasattr(window, "trust_online") and window.trust_online.isVisible())
check("التحديث يجلب حساب البوابة من AAA", any(row[0] == "sara" for row in controller.portal_rows()))
controller.db.set_name("00005e005302", "Office AP", "")
window._render()
online_table = window.tables["online"]
check("المتصلون يعرضون الاسم الوصفي بجانب الحساب", online_table.item(0, 2).text() == "Office AP")
check("المتصلون يعرضون طريقة الاتصال والمجموعة", online_table.item(0, 3).text() == "802.1X"
      and online_table.item(0, 4).text() == "grp_managers")
check("حالة Active خضراء", online_table.item(0, 7).text() == "Active"
      and online_table.item(0, 7).foreground().color() == QColor("#067647"))
check("حالة Pre-authentication برتقالية", online_table.item(1, 7).text() == "Pre-authentication"
      and online_table.item(1, 7).foreground().color() == QColor("#B54708"))

controller.close()
window._connect()
app.processEvents()
check("نافذة الاتصال تظهر", window.connect_dialog is not None and window.connect_dialog.isVisible())
if window.connect_dialog is not None:
    check("نافذة الاتصال الإنجليزية LTR", window.connect_dialog.layoutDirection() == qt.Qt.LeftToRight)
    window.connect_dialog.reject()
window._toggle_language()
app.processEvents()
check("زر اللغة يبدّل إلى العربية RTL", window.lang == "ar" and window.layoutDirection() == qt.Qt.RightToLeft)
window._toggle_language()
app.processEvents()
check("زر اللغة يعيد الإنجليزية LTR", window.lang == "en" and window.layoutDirection() == qt.Qt.LeftToRight)
controller.connect("demo", 22, "admin", "anything")

print("٣ — تحديث المتصلين الآن")
controller.settings["mac_shared_password"] = "Qt-Shared-9"
controller.settings["auto_save_config"] = False
before_online = snapshot(qt.legacy._DemoParamiko.device)
online_result = controller.refresh_online()
after_online = snapshot(qt.legacy._DemoParamiko.device)
check("تحديث المتصلين لا يغير بيانات الراوتر", before_online == after_online)
check("تحديث المتصلين يعيد جلسات حية", bool(online_result) and controller.online == online_result)
session_id = controller.online[0]["id"]
before_disconnect = snapshot(qt.legacy._DemoParamiko.device)
disconnected = controller.disconnect_online(session_id)
after_disconnect = snapshot(qt.legacy._DemoParamiko.device)
check("فصل المتصل Qt نجح", disconnected.ok and disconnected.code == "disconnected")
check("فصل المتصل تحقق بإعادة قراءة الجلسات", all(row["id"] != session_id for row in controller.online))
check("فصل المتصل لا يغير حسابات AAA أو الإعدادات", before_disconnect["users"] == after_disconnect["users"]
      and before_disconnect["profiles"] == after_disconnect["profiles"]
      and before_disconnect["mgmt"] == after_disconnect["mgmt"])
check("رفض فصل جلسة فارغة قبل الراوتر", controller.disconnect_online("").code == "missing_session")
trust_session = next(row for row in controller.online if row["user"] == "00005e005301")
trusted_online = controller.trust_online(trust_session, "جهاز متصل Qt", "grp_staff", "من الجلسات")
trusted_mac = qt.legacy.normalize_mac(trust_session["mac"])
check("إضافة المتصل للموثوقة Qt نجحت", trusted_online.ok and trusted_online.code == "added")
check("إضافة المتصل تحققت بإعادة قراءة AAA", trusted_mac in controller.users)
check("إضافة المتصل حفظت الوصف محلياً", (controller.db.device(trusted_mac) or {}).get("name")
      == "جهاز متصل Qt")
check("إضافة المتصل لا تفصل الجلسة تلقائياً", any(row["id"] == trust_session["id"] for row in controller.online))
check("رفض إضافة متصل بلا اسم قبل الراوتر", controller.trust_online(
      trust_session, "", "grp_staff", "").code == "missing_name")
check("رفض إضافة متصل موثوق مسبقاً", controller.trust_online(
      trust_session, "جهاز متصل Qt", "grp_staff", "").code == "duplicate")

print("٤ — الشبكات والعملاء")
before_vlans = snapshot(qt.legacy._DemoParamiko.device)
vlan_state = controller.refresh_vlans()
after_vlans = snapshot(qt.legacy._DemoParamiko.device)
check("تحديث الشبكات لا يغير بيانات الراوتر", before_vlans == after_vlans)
check("تحديث الشبكات يقرأ قائمة VLAN كاملة", bool(controller.vlans)
      and any(item["vid"] == "20" for item in controller.vlans))
check("تحديث الشبكات يختار شبكة ويقرأ عملاءها", vlan_state is not None
      and vlan_state.get("vid") in {item["vid"] for item in controller.vlans})
staff = next(item for item in controller.vlans if item["vid"] == "20")
before_select = snapshot(qt.legacy._DemoParamiko.device)
staff_state = controller.select_vlan(staff["vid"])
after_select = snapshot(qt.legacy._DemoParamiko.device)
check("اختيار VLAN لا يغير بيانات الراوتر", before_select == after_select)
check("اختيار VLAN يحافظ على الواجهة والصفوف", staff_state is not None
      and staff_state.get("iface") == staff.get("iface") and isinstance(staff_state.get("rows"), list))
vlan_record = next(row for row in staff_state["rows"]
                   if row["mac"] not in controller.db.data["devices"])
vlan_mac = vlan_record["mac"]
vlan_name_text = "جهاز شبكة Qt %d" % len(controller.db.data["history"])
vlan_note_text = "محلي فقط %d" % len(controller.db.data["history"])
before_vlan_name = snapshot(qt.legacy._DemoParamiko.device)
vlan_name = controller.update_vlan_metadata(vlan_mac, vlan_name_text, vlan_note_text)
after_vlan_name = snapshot(qt.legacy._DemoParamiko.device)
check("تسمية جهاز الشبكة محلياً نجحت", vlan_name.ok and vlan_name.code == "updated")
check("تسمية جهاز الشبكة لا تغير الراوتر", before_vlan_name == after_vlan_name)
check("تسمية جهاز الشبكة لا تمنحه الثقة", vlan_mac not in controller.db.data["devices"]
      and controller.db.name_of(vlan_mac) == vlan_name_text
      and controller.db.note_of(vlan_mac) == vlan_note_text)
check("التسمية ذاتها لا تكتب مرة ثانية", controller.update_vlan_metadata(
      vlan_mac, vlan_name_text, vlan_note_text).code == "unchanged")
before_overlap = snapshot(qt.legacy._DemoParamiko.device)
overlap = controller.scan_vlan_overlap()
after_overlap = snapshot(qt.legacy._DemoParamiko.device)
check("فحص تداخل الشبكات Qt لا يغير بيانات الراوتر", before_overlap == after_overlap)
check("فحص تداخل الشبكات Qt يكشف الجهاز ذا العنوانين", overlap.ok
      and "00005e005302" in controller.vlan_overlap["dups"])
check("الفحص يوثق الشبكة الأخرى في نتيجة مشتركة", any(
      entry["vid"] == "1" for entry in controller.vlan_overlap["dups"]["00005e005302"]))
# فُصلت جلسة الجهاز التجريبي في قسم «المتصلون» أعلاه؛ نعيد جلسة موثقة لنختبر
# هنا مسار فصل VLAN نفسه، ثم يتأكد المسار من اختفائها بإعادة قراءة الشبكة.
qt.legacy._DemoParamiko.device.online.append({
    "id": "1099", "user": "00005e005302", "ip": "10.0.20.166",
    "mac": "0000-5e00-5302", "status": "Success",
})
staff_state = controller.select_vlan(staff["vid"])
cut_record = next(row for row in staff_state["rows"] if row.get("auth"))
cut_mac = cut_record["mac"]
before_vlan_cut = snapshot(qt.legacy._DemoParamiko.device)
vlan_cut = controller.disconnect_vlan_devices([cut_mac])
after_vlan_cut = snapshot(qt.legacy._DemoParamiko.device)
check("فصل جهاز الشبكة Qt نجح", vlan_cut.ok and vlan_cut.code == "disconnected")
check("فصل جهاز الشبكة لا يغير حسابات AAA أو الإعدادات", before_vlan_cut["users"] == after_vlan_cut["users"]
      and before_vlan_cut["profiles"] == after_vlan_cut["profiles"]
      and before_vlan_cut["mgmt"] == after_vlan_cut["mgmt"])
check("فصل جهاز الشبكة يعيد قراءة صفوف VLAN", controller.vlan_state is not None
      and all(row.get("mac") != cut_mac or not row.get("auth") for row in controller.vlan_state["rows"]))
check("رفض فصل VLAN بلا تحديد قبل الراوتر", controller.disconnect_vlan_devices([]).code == "missing_selection")
window._render()
window.stack.setCurrentIndex(4)
app.processEvents()
check("اختيار الشبكة Qt ظاهر", hasattr(window, "vlan_picker") and window.vlan_picker.isVisible())
check("زر تحديث الشبكات Qt ظاهر", hasattr(window, "refresh_vlans") and window.refresh_vlans.isVisible())
check("زر تسمية جهاز الشبكة Qt ظاهر", hasattr(window, "name_vlan_device")
      and window.name_vlan_device.isVisible())
check("زر فحص تداخل الشبكات Qt ظاهر", hasattr(window, "scan_vlan_overlap")
      and window.scan_vlan_overlap.isVisible())
check("زر فصل المحدد من الشبكة Qt ظاهر", hasattr(window, "cut_vlan_devices")
      and window.cut_vlan_devices.isVisible())
check("جدول عملاء الشبكة Qt ظاهر", "vlans" in window.tables and window.tables["vlans"].isVisible())
check("جدول الشبكة يعرض عنوان الشبكة الأخرى", any(
      window.tables["vlans"].item(row, 8) is not None
      and "VLAN 1" in window.tables["vlans"].item(row, 8).text()
      for row in range(window.tables["vlans"].rowCount())))

print("٥ — أول إجراء Qt: إضافة جهاز موثوق")
result = controller.create_device("00:00:5E:00:53:99", "Qt test", "grp_staff", "انتقال")
check("إضافة Qt نجحت", result.ok and result.code == "added")
check("الحساب تحقّق بإعادة قراءة AAA", "00005e005399" in controller.users)
check("سُجل الاسم محلياً", (controller.db.device("00005e005399") or {}).get("name") == "Qt test")
check("رفض Qt ماك غير صالح قبل الراوتر", controller.create_device("invalid", "", "grp_staff", "").code == "bad_mac")
before_meta = snapshot(qt.legacy._DemoParamiko.device)
meta = controller.update_device_metadata("00:00:5E:00:53:99", "Qt renamed", "لا راوتر")
after_meta = snapshot(qt.legacy._DemoParamiko.device)
check("تعديل Qt محلي ناجح", meta.ok and meta.code == "updated")
check("الاسم والملاحظة تغيّرا محلياً", (controller.db.device("00005e005399") or {}).get("name") == "Qt renamed"
      and (controller.db.device("00005e005399") or {}).get("note") == "لا راوتر")
check("تعديل Qt لا يرسل أمراً للراوتر", before_meta == after_meta)
check("التعديل ذاته لا يكتب مرة ثانية", controller.update_device_metadata(
      "00:00:5E:00:53:99", "Qt renamed", "لا راوتر").code == "unchanged")
group_change = controller.change_device_group("00:00:5E:00:53:99", "grp_managers")
check("تغيير مجموعة Qt نجح", group_change.ok and group_change.code == "group_changed")
check("تغيير المجموعة تحقق بإعادة قراءة AAA", (controller.users.get("00005e005399") or {}).get("group") == "grp_managers")
check("تغيير المجموعة حدّث السجل المحلي", (controller.db.device("00005e005399") or {}).get("group") == "grp_managers")
check("رفض Qt مجموعة فارغة قبل الراوتر", controller.change_device_group(
      "00:00:5E:00:53:99", "").code == "missing_group")
revoked = controller.revoke_device("00:00:5E:00:53:99", "اختبار سحب")
check("سحب ثقة Qt نجح", revoked.ok and revoked.code == "revoked")
check("سحب الثقة تحقق بحذف حساب AAA", "00005e005399" not in controller.users)
local = controller.db.device("00005e005399") or {}
check("سحب الثقة أبقى الأرشيف والسبب محلياً", local.get("state") == "revoked"
      and local.get("revoke_reason") == "اختبار سحب")
check("رفض Qt ماك غير صالح عند سحب الثقة", controller.revoke_device("invalid", "").code == "bad_mac")
export_path = os.path.join(WORK, "trusted-devices.csv")
controller.export_devices(export_path)
with open(export_path, encoding="utf-8-sig") as exported:
    export_text = exported.read()
check("تصدير Qt ينشئ CSV بترميز عربي", os.path.exists(export_path)
      and export_text.startswith("عنوان الماك,"))
check("تصدير Qt يحفظ الأرشيف المحلي", "00:00:5E:00:53:99" in export_text
      and "اختبار سحب" in export_text)

print("٦ — تعديل بيانات حساب البوابة")
before_portal = snapshot(qt.legacy._DemoParamiko.device)
portal_name = "بوابة Qt %d" % len(controller.db.data["history"])
portal_note = "محلي فقط %d" % len(controller.db.data["history"])
portal_meta = controller.update_portal_metadata("sara", portal_name, portal_note)
after_portal = snapshot(qt.legacy._DemoParamiko.device)
check("تعديل بيانات البوابة محلي ناجح", portal_meta.ok and portal_meta.code == "updated")
check("بيانات البوابة حُفظت محلياً", (controller.db.portal("sara") or {}).get("name") == portal_name
      and (controller.db.portal("sara") or {}).get("note") == portal_note)
check("تعديل بيانات البوابة لا يرسل أمراً للراوتر", before_portal == after_portal)
check("التعديل ذاته للبوابة لا يكتب مرة ثانية", controller.update_portal_metadata(
      "sara", portal_name, portal_note).code == "unchanged")
check("صف البوابة يعرض الاسم المعدل", any(row[0] == "sara" and row[1] == portal_name
      for row in controller.portal_rows()))
portal_export_path = os.path.join(WORK, "portal-accounts.csv")
controller.export_portal(portal_export_path)
with open(portal_export_path, encoding="utf-8-sig") as exported:
    portal_export_text = exported.read()
check("تصدير البوابة ينشئ CSV بترميز عربي", os.path.exists(portal_export_path)
      and portal_export_text.startswith("اسم الحساب,"))
check("تصدير البوابة يحفظ البيانات المعدلة", "sara" in portal_export_text
      and portal_name in portal_export_text and portal_note in portal_export_text)

print("٧ — إضافة حساب بوابة")
portal_user = "qtportal%d" % len(controller.db.data["history"])
portal_created = controller.create_portal(portal_user, "Qt-Portal-9", "حساب Qt", "grp_staff", "انتقال")
check("إضافة حساب بوابة Qt نجحت", portal_created.ok and portal_created.code == "added")
check("حساب البوابة تحقّق بإعادة قراءة AAA", portal_user in controller.users
      and "web" in controller.users[portal_user]["service_types"])
check("حساب البوابة سُجل محلياً", (controller.db.portal(portal_user) or {}).get("name") == "حساب Qt")
check("رفض Qt اسم حساب غير صالح قبل الراوتر", controller.create_portal(
      "invalid user", "Qt-Portal-9", "", "grp_staff", "").code == "bad_username")
check("رفض Qt كلمة مرور قصيرة قبل الراوتر", controller.create_portal(
      "shortportal", "short", "", "grp_staff", "").code == "short_password")
check("رفض Qt كلمة مرور تساوي الحساب قبل الراوتر", controller.create_portal(
      "sameportal", "sameportal", "", "grp_staff", "").code == "password_is_username")
check("رفض Qt حساب بوابة مكرر", controller.create_portal(
      portal_user, "Qt-Portal-9", "", "grp_staff", "").code == "duplicate")

print("٨ — تغيير كلمة مرور حساب البوابة")
password_changed = controller.change_portal_password(portal_user, "Qt-Changed-10")
check("تغيير كلمة مرور البوابة Qt نجح", password_changed.ok and password_changed.code == "password_changed")
check("تغيير كلمة المرور يسجل العملية للحساب الصحيح", (controller.db.data["history"] or [])[-1].get("action")
      == "reset_password" and (controller.db.data["history"] or [])[-1].get("target") == portal_user)
check("سجل كلمة المرور لا يحتوي القيمة السرية", all(
      "Qt-Changed-10" not in str(entry) for entry in controller.db.data["history"]))
check("رفض كلمة مرور بوابة قصيرة", controller.change_portal_password(
      portal_user, "short").code == "short_password")
check("رفض كلمة مرور بوابة تساوي الحساب", controller.change_portal_password(
      portal_user, portal_user).code == "password_is_username")

print("٩ — تغيير مجموعة حساب البوابة")
portal_group = controller.change_portal_group(portal_user, "grp_managers")
check("تغيير مجموعة البوابة Qt نجح", portal_group.ok and portal_group.code == "group_changed")
check("تغيير مجموعة البوابة تحقق بإعادة قراءة AAA", (controller.users.get(portal_user) or {}).get("group")
      == "grp_managers")
check("تغيير مجموعة البوابة حدّث السجل المحلي", (controller.db.portal(portal_user) or {}).get("group")
      == "grp_managers")
check("رفض تغيير مجموعة البوابة الفارغة قبل الراوتر", controller.change_portal_group(
      portal_user, "").code == "missing_group")

print("١٠ — حذف حساب البوابة")
portal_revoked = controller.revoke_portal(portal_user, "انتهى الاختبار")
check("حذف حساب البوابة Qt نجح", portal_revoked.ok and portal_revoked.code == "revoked")
check("حذف حساب البوابة تحقق بإعادة قراءة AAA", portal_user not in controller.users)
portal_archive = controller.db.portal(portal_user) or {}
check("حذف حساب البوابة أبقى الأرشيف والسبب محلياً", portal_archive.get("state") == "revoked"
      and portal_archive.get("revoke_reason") == "انتهى الاختبار")

print("١١ — صفحات الإدارة المساندة")
before_mgmt = snapshot(qt.legacy._DemoParamiko.device)
management = controller.refresh_management()
after_mgmt = snapshot(qt.legacy._DemoParamiko.device)
check("تحديث أجهزة الإدارة لا يغير الراوتر", before_mgmt == after_mgmt)
check("تحديث أجهزة الإدارة يبني الصفوف", isinstance(management, list))
suggested_mgmt_ip = controller.suggested_management_ip("Vlanif1")
check("اقتراح جهاز الإدارة يختار أعلى عنوان حر", suggested_mgmt_ip == "10.0.1.254")
controller._write_router_log("display access-user\npassword cipher secret-value\n")
window._render()
check("سجل الأوامر يعرض نشاط Qt ويخفي كلمة المرور", "display access-user" in window.log_text.toPlainText()
      and "secret-value" not in window.log_text.toPlainText()
      and "password cipher ******" in window.log_text.toPlainText())
check("سجل الأوامر عالي التباين", window.log_text.objectName() == "commandLog"
      and "color: #FFFFFF" in qt.STYLE and "background: #050A12" in qt.STYLE)
before_wan = snapshot(qt.legacy._DemoParamiko.device)
wan = controller.check_wan(live=False)
after_wan = snapshot(qt.legacy._DemoParamiko.device)
check("فحص خطوط الإنترنت لا يغير الراوتر", before_wan == after_wan)
check("فحص خطوط الإنترنت يعيد تقريراً", bool(wan) and bool(controller.wan_report()))
window._render()
wan_table = window.tables["wan"]
wan_rows = {wan_table.item(row, 0).text(): row for row in range(wan_table.rowCount())}
wan1 = wan_rows.get("WAN1")
wan2 = wan_rows.get("WAN2")
check("Ping وHTTPS يظهران كأيقونات ملوّنة", wan1 is not None
      and wan_table.item(wan1, 4).text().startswith("✓")
      and wan_table.item(wan1, 4).foreground().color() == QColor("#067647")
      and wan_table.item(wan1, 5).text().startswith("✗")
      and wan_table.item(wan1, 5).foreground().color() == QColor("#B42318"))
check("الخط المنفصل مميّز بالأحمر", wan2 is not None
      and wan_table.item(wan2, 9).foreground().color() == QColor("#B42318"))
window._set_busy(True)
check("قفل الواجهة يظهر تحميلًا ويمنع الأزرار", window.busy_overlay.isVisible()
      and window.busy_spinner.minimum() == 0 and window.busy_spinner.maximum() == 0
      and not window.check_wan.isEnabled() and not window.connect_button.isEnabled())
window._set_busy(False)
check("قفل الواجهة يعيد الأزرار بعد انتهاء العملية", window.check_wan.isEnabled()
      and window.connect_button.isEnabled())
saved = controller.save_preferences({"auto_save_config": False})
check("حفظ إعدادات Qt محلي ناجح", saved.ok and saved.code == "saved")
check("Firebase يرفض الإعداد الناقص بوضوح", controller.firebase_sync().code == "bad_config")
window._render()
for index, attribute in ((5, "refresh_management"), (6, "check_wan"), (7, "refresh_groups"),
                         (8, "save_settings"), (9, "copy_log")):
    window.stack.setCurrentIndex(index)
    app.processEvents()
    check("إجراء Qt ظاهر: %s" % attribute, hasattr(window, attribute) and getattr(window, attribute).isVisible())
window.stack.setCurrentIndex(8)
app.processEvents()
check("زر استيراد اعتماد Firebase ظاهر", hasattr(window, "import_firebase_credentials")
      and window.import_firebase_credentials.isVisible())
window.close()
controller.close()
shutil.rmtree(WORK, ignore_errors=True)

if FAILS:
    print("\nفشل %d: %s" % (len(FAILS), " | ".join(FAILS)))
    sys.exit(1)
print("\nنجحت اختبارات تطبيق Qt")
