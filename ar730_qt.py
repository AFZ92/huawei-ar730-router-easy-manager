#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تطبيق سطح المكتب الرسمي لإدارة الوصول على Huawei AR730."""
import argparse
import copy
import time
import datetime
import json
import os
import re
import shutil
import sys

from PySide6.QtCore import QThread, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout,
    QFileDialog, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QStackedWidget, QStyle, QStyleFactory, QStyledItemDelegate, QTableWidget, QTableWidgetItem, QVBoxLayout, QCheckBox, QTextEdit,
    QWidget,
)

import ar730_manager as legacy
import firebase_merge as cloud_merge


# سطح التطبيق الرسمي. يبقى هنا بجانب الواجهة الوحيدة بدلاً من عقد انتقال منفصل.
APP_PAGES = {
    "devices": {"title": "الأجهزة الموثوقة", "columns": ("عنوان الماك", "الاسم الوصفي", "المجموعة", "الحالة", "أُضيف", "ملاحظة")},
    "portal": {"title": "حسابات البوابة", "columns": ("اسم الحساب", "الاسم الوصفي", "المجموعة", "الحالة", "أُضيف", "ملاحظة")},
    "online": {"title": "المتصلون الآن", "columns": ("الرقم", "اسم الحساب", "الاسم الوصفي", "طريقة الاتصال", "المجموعة", "عنوان IP", "عنوان الماك", "الحالة")},
    "vlans": {"title": "المتّصلون حسب الشبكة", "columns": ("عنوان IP", "عنوان الماك", "الاسم الوصفي", "المُصنِّع", "المنفذ", "نوع العنوان", "الحضور", "المصادقة", "شبكات أخرى")},
    "management": {"title": "أجهزة الإدارة", "columns": ("عنوان IP", "عنوان الماك", "الاسم الوصفي", "الشبكة", "القاعدة", "ربط DHCP", "ARP ثابت", "الحالة", "الحالة المحلية")},
    "wan": {"title": "خطوط الإنترنت", "columns": ("الخط", "المنفذ", "البوابة", "التوزيع", "ping", "HTTPS", "الاستجابة", "السعة", "المنفذ الفيزيائي", "الحكم")},
    "groups": {"title": "مجموعات الصلاحيات", "columns": ("المجموعة", "القائمة", "الأعضاء")},
    "settings": {"title": "الإعدادات", "columns": ()},
    "log": {"title": "سجل الأوامر", "columns": ()},
    "nat": {"title": "تحويل المنافذ NAT", "columns": ("واجهة WAN", "عنوان WAN", "البروتوكول", "المنفذ الخارجي", "عنوان الجهاز", "المنفذ الداخلي")},
}


# Qt deliberately uses the same terminology as the established application.
# Keeping this small adapter here means dialogs, labels and buttons cannot drift
# into a partly translated UI as the migration grows.
ACTIVE_LANGUAGE = "en"
_QT_LABEL = QLabel
_QT_BUTTON = QPushButton
_QT_DIALOG = QDialog
_QT_FORM = QFormLayout
_QT_MESSAGE_BOX = QMessageBox
_QT_LINE_EDIT = QLineEdit

_TEXT_BY_ARABIC = {
    arabic: legacy.TXT["en"][key]
    for key, arabic in legacy.TXT["ar"].items()
    if key in legacy.TXT["en"]
}
_TEXT_BY_ARABIC.update({
    "AR730 Access Manager": "AR730 Access Manager",
    "مدير الوصول والشبكة": "Access & Network Manager",
    "نظرة عامة": "Overview",
    "الدليل والدعم": "Guide & Support",
    "جاهز": "Ready",
    "انتظر حتى ينتهي التواصل مع الراوتر.": "Please wait until communication with the router finishes.",
    "مسار غير صالح": "Invalid route",
    "بحث في النتائج…": "Search results…",
    "حدّد صفاً ثم اضغط Ctrl+C للنسخ. لا يمكن تعديل الجدول.": "Select a row and press Ctrl+C to copy. Tables are read-only.",
    "تحديث المتصلين": "Refresh online users",
    "الشبكة": "Network",
    "تحديث الشبكات": "Refresh networks",
    "استثناء نطاق DHCP": "Exclude DHCP range",
    "ربط IP بـ MAC": "Bind IP to MAC",
    "استثناء نطاق من DHCP": "Exclude a DHCP range",
    "ربط IP ثابت بـ MAC": "Bind a static IP to MAC",
    "أول عنوان": "First address",
    "آخر عنوان": "Last address",
    "عنوان النهاية": "End address",
    "عنوان البداية": "Start address",
    "فصل جلسات DHCP المطابقة بعد الاستثناء": "Disconnect matching DHCP sessions after exclusion",
    "لن يُوزع DHCP هذا النطاق بعد الحفظ. فصل الجلسات اختياري ويقتصر على الأجهزة التي يطابق MAC الخاص بها إيجار DHCP؛ لا تُفصل الأجهزة ذات العنوان الثابت اليدوي.": "DHCP will no longer distribute this range after saving. Disconnecting is optional and only applies where the MAC exactly matches a DHCP lease; manually static devices are not disconnected.",
    "استثناء والتحقق": "Exclude and verify",
    "عنوان الماك": "MAC address",
    "عنوان IP المطلوب": "Requested IP address",
    "وصف الراوتر": "Router description",
    "فصل الجلسة بعد الربط لتجديد العنوان": "Disconnect the session after binding to renew the address",
    "الربط يحجز عنوان DHCP لهذا MAC فقط. لا يضيف ARP ثابتاً أو صلاحية إدارة، ولا يمكن اختيار عنوان مستثنى من مجمّع DHCP.": "This binding reserves a DHCP address for this MAC only. It adds no static ARP or management access, and an excluded pool address cannot be chosen.",
    "ربط والتحقق": "Bind and verify",
    "اختياري، أحرف إنجليزية وأرقام": "Optional; English letters and numbers",
    "هذه الشبكة بلا واجهة عنوان على الراوتر، ولا تملك DHCP محلياً.": "This network has no routed interface on the router, so it has no local DHCP.",
    "هذه الشبكة لا تستخدم DHCP من واجهتها على الراوتر.": "This network does not use DHCP from its router interface.",
    "حدّث الشبكات واختر شبكة أولاً.": "Refresh the networks and choose one first.",
    "اختر جهازاً من جدول الشبكة أولاً.": "Choose a device from the network table first.",
    "تم استثناء النطاق والتحقق من إعداد الراوتر.": "The range was excluded and the router configuration was verified.",
    "هذا النطاق مستثنى بالفعل.": "This range is already excluded.",
    "الشبكة المحددة لا تملك DHCP محلياً.": "The selected network has no local DHCP.",
    "أدخل نطاق IP صحيحاً بترتيب البداية ثم النهاية.": "Enter a valid IP range with the start before the end.",
    "النطاق خارج شبكة الواجهة المحددة.": "The range is outside the selected interface network.",
    "النطاق يتداخل جزئياً مع نطاق DHCP مستثنى بالفعل.": "The range partially overlaps an already excluded DHCP range.",
    "يوجد ربط DHCP ثابت داخل النطاق المطلوب استثناؤه.": "A static DHCP binding exists inside the range to exclude.",
    "نُفذ الأمر لكن النطاق لم يظهر عند إعادة قراءة الإعداد.": "The command ran, but the range was absent when the configuration was reread.",
    "تعذر تعديل مجمّع DHCP.": "Could not modify the DHCP pool.",
    "تم الاستثناء، لكن تعذر فصل بعض الجلسات المطابقة.": "The range was excluded, but some matching sessions could not be disconnected.",
    "تم ربط IP بـ MAC والتحقق من إعداد DHCP.": "The IP was bound to the MAC and the DHCP configuration was verified.",
    "هذا الربط موجود بالفعل.": "This binding already exists.",
    "عنوان MAC المحدد غير صالح.": "The selected MAC address is invalid.",
    "عنوان IP خارج شبكة الواجهة المحددة.": "The IP address is outside the selected interface network.",
    "لا يمكن ربط عنوان مستثنى من مجمّع DHCP.": "An address excluded from the DHCP pool cannot be bound.",
    "العنوان مستخدم حالياً أو ظاهر لجهاز MAC آخر.": "The address is in use or is visible for another MAC address.",
    "هذا MAC مربوط بالفعل بعنوان DHCP آخر.": "This MAC is already bound to another DHCP address.",
    "نُفذ الأمر لكن الربط لم يظهر عند إعادة قراءة الإعداد.": "The command ran, but the binding was absent when the configuration was reread.",
    "تعذر إنشاء ربط DHCP.": "Could not create the DHCP binding.",
    "تم الربط، لكن تعذر فصل الجلسة المختارة لتجديد العنوان.": "The address was bound, but the selected session could not be disconnected to renew it.",
    "لم يُحفظ إعداد بدء التشغيل تلقائياً.": "The startup configuration was not saved automatically.",
    "إضافة جهاز إدارة": "Add management device",
    "إزالة جهاز إدارة": "Remove management device",
    "تغيير كلمة السر وتعميمها": "Change and apply password",
    "كلمة MAC المشتركة": "Shared MAC password",
    "تأكيد كلمة MAC": "Confirm MAC password",
    "إظهار كلمة السر": "Show password",
    "اكتب كلمة السر مرتين للتحقق.": "Enter the password twice to verify it.",
    "كلمتا السر متطابقتان.": "The passwords match.",
    "مراقبة تلقائية": "Automatic monitoring",
    "تحويل المنافذ NAT": "Port Forwarding",
    "واجهة WAN": "WAN interface",
    "عنوان WAN": "WAN address",
    "البروتوكول": "Protocol",
    "المنفذ الخارجي": "External port",
    "عنوان الجهاز": "Device address",
    "المنفذ الداخلي": "Internal port",
    "إضافة تحويل منفذ": "Add port forwarding",
    "تعديل التحويل المحدد": "Edit selected forwarding",
    "حذف التحويل المحدد": "Delete selected forwarding",
    "تحديث التحويلات": "Refresh rules",
    "أضف تحويل TCP من واجهة WAN إلى جهاز داخلي. يتحقق التطبيق من عدم تكرار المنفذ ومن وجود مسار للجهاز قبل الإضافة.": "Add a TCP forwarding rule from a WAN interface to an internal device. The app checks for port conflicts and a route to the device before applying it.",
    "أضف أو عدّل أو احذف تحويل TCP من واجهة WAN. يتحقق التطبيق من التعارض والمسار، ويعيد قراءة الراوتر بعد كل تغيير.": "Add, edit, or delete a TCP forwarding rule from a WAN interface. The app checks conflicts and routing, then rereads the router after every change.",
    "أضف قاعدة تحويل المنفذ": "Add port forwarding rule",
    "تعديل تحويل المنفذ": "Edit port forwarding rule",
    "حذف تحويل المنفذ": "Delete port forwarding rule",
    "واجهة الإنترنت": "Internet interface",
    "TCP فقط (تم التحقق على هذا الراوتر)": "TCP only (verified on this router)",
    "مثال: 65010": "Example: 65010",
    "مثال: 10.0.20.210": "Example: 10.0.20.210",
    "سيضيف التطبيق: TCP من منفذ WAN الخارجي إلى منفذ الجهاز الداخلي. لا تضع جهازاً داخلياً في شبكة WAN نفسها.": "The app will forward TCP from the WAN external port to the device internal port. Do not place the internal device on the same WAN network.",
    "سيستبدل التطبيق القاعدة بعد التحقق، ويعيد القديمة تلقائياً إن تعذر إنشاء البديل.": "The app will replace the rule after verification and automatically restore the old rule if the replacement cannot be created.",
    "حفظ والتحقق": "Save and verify",
    "اختر واجهة الإنترنت أولاً.": "Choose an internet interface first.",
    "رقم المنفذ يجب أن يكون بين 1 و65535.": "Port number must be between 1 and 65535.",
    "عنوان الجهاز الداخلي غير صالح.": "Internal device address is invalid.",
    "لا يمكن أن يكون الجهاز الداخلي في شبكة WAN نفسها.": "The internal device cannot be in the same WAN network.",
    "هذا المنفذ محجوز بالفعل للتحويل نفسه.": "This port forwarding rule already exists.",
    "المنفذ الخارجي مستخدم بالفعل لتحويل آخر: %s": "External port is already used by another rule: %s",
    "لا يوجد مسار معروف إلى الجهاز الداخلي.": "No known route to the internal device.",
    "نُفذت القاعدة لكن لم تظهر عند إعادة القراءة.": "The rule was sent but did not appear after rereading.",
    "أُضيف التحويل وتحقق التطبيق منه وحُفظ في الراوتر.": "Port forwarding was added, verified, and saved on the router.",
    "أُضيف التحويل وتحقق التطبيق منه، لكن تعذر حفظ إعداد بدء التشغيل.": "Port forwarding was added and verified, but saving the startup configuration failed.",
    "عُدّل التحويل وتحقق التطبيق منه وحُفظ في الراوتر.": "Port forwarding was edited, verified, and saved on the router.",
    "حُذف التحويل وتحقق التطبيق من اختفائه وحُفظ في الراوتر.": "Port forwarding was deleted, confirmed absent, and saved on the router.",
    "لم تتغير بيانات التحويل.": "The forwarding rule was unchanged.",
    "لم تعد القاعدة المحددة موجودة على الراوتر. حدّث التحويلات ثم حاول مجدداً.": "The selected rule no longer exists on the router. Refresh rules and try again.",
    "لم يتأكد التطبيق من حذف التحويل القديم؛ لم تُنشأ القاعدة البديلة.": "The app could not confirm removal of the old forwarding rule, so no replacement was created.",
    "تعذر إنشاء التحويل البديل؛ أعاد التطبيق التحويل القديم.": "The replacement forwarding rule could not be created; the old rule was restored.",
    "تعذر إنشاء التحويل البديل وتعذر استرجاع التحويل القديم. راجع سجل الأوامر فوراً.": "The replacement could not be created and the old rule could not be restored. Review the command log immediately.",
    "أجهزة موثوقة": "Trusted devices",
    "حسابات بوابة": "Portal accounts",
    "متصلون الآن": "Online users",
    "مجموعات صلاحيات": "Permission groups",
    "ملخص حالة الوصول وإدارة الراوتر الحالية.": "Current access and router management overview.",
    "إدارة موحّدة": "Unified management",
    "تُعرض البيانات الحية وتُنفّذ الإجراءات من هذه الواجهة، مع إعادة القراءة للتحقق من نتيجة التغيير.": "This interface shows live data and performs actions, then rereads the router to verify each change.",
    "إدارة مباشرة للبيانات والإجراءات المرتبطة بالراوتر.": "Direct management of router data and actions.",
    "دليل تشغيل مختصر يوضح مسار العمل الآمن وقنوات الدعم.": "A concise operating guide for a safe workflow and support channels.",
    "التثبيت والتحديث": "Installation & updates",
    "للتثبيت الأول أو التحديث على Windows، افتح PowerShell ونفّذ:": "For first installation or an update on Windows, open PowerShell and run:",
    "وعلى macOS، افتح Terminal ونفّذ:": "On macOS, open Terminal and run:",
    "الإصدار المثبّت: ": "Installed version: ",
    "يتحقق المثبّت من SHA-256، ولا يمسّ بياناتك المحلية عند التحديث.": "The installer verifies SHA-256 and preserves local data during updates.",
    "إدارة الوصول بثقة، لا بتخمين": "Manage access with confidence, not guesswork",
    "يحوّل التطبيق إجراءات Huawei AR730 المتكررة إلى خطوات واضحة: يراجع البيانات، ينفّذ التغيير، ثم يعيد القراءة للتأكد من ثبوته.": "The application turns repeated Huawei AR730 tasks into clear steps: review the data, apply the change, then read again to verify it persisted.",
    "1. ابدأ بوضع التجربة": "1. Start in demo mode",
    "تدرّب على الأزرار ونتائجها بلا أي اتصال بالشبكة.": "Practice the controls and their results without touching a network.",
    "2. اتصل ثم حدّث": "2. Connect, then refresh",
    "تحقق من حالة الاتصال بالأعلى، ثم حدّث الجداول قبل اتخاذ قرار.": "Check the connection status at the top, then refresh tables before making a decision.",
    "3. اختر طريقة الوصول": "3. Choose the access method",
    "الأجهزة الثابتة للطابعات والحواسيب؛ وحسابات البوابة للهواتف والضيوف.": "Use trusted devices for fixed equipment such as printers and PCs; use portal accounts for phones and guests.",
    "4. راجع الأثر قبل التأكيد": "4. Review the impact before confirming",
    "التغييرات الحساسة تعرض ما سيتغير. تغيير المجموعة يفصل الجلسة لتطبيق الصلاحيات الجديدة.": "Sensitive changes show what will change. A group change disconnects the session so new permissions take effect.",
    "5. راقب النتيجة": "5. Monitor the result",
    "تظهر حالة التنفيذ في أعلى النافذة. انسخ صفوف الجداول بـ Ctrl+C وراجع سجل الأوامر عند الحاجة.": "Execution status appears at the top of the window. Copy table rows with Ctrl+C and consult the command log when needed.",
    "تطوير ودعم حلول إدارة الشبكات والوصول.": "Network and access-management solutions — development and support.",
    "● متصل": "● Connected",
    "● غير متصل": "● Disconnected",
    "لا يوجد اتصال": "No connection",
    "● متصل بـ ": "● Connected to ",
    "جارٍ تنفيذ العملية…": "Working…",
    "اكتملت العملية": "Operation completed",
    "تعذرت العملية": "Operation failed",
    "تم نسخ %d صف": "Copied %d row(s)",
    "اتصال بالراوتر": "Connect to router",
    "إضافة جهاز موثوق": "Add trusted device",
    "إضافة والتحقق": "Add and verify",
    "مجموعة الصلاحيات": "Permission group",
    "تغيير كلمة مرور الحساب": "Change account password",
    "كلمة المرور الجديدة": "New password",
    "8 محارف على الأقل": "At least 8 characters",
    "حفظ التعديل": "Save changes",
    "تسمية جهاز على الشبكة": "Name network device",
    "مثال: طابعة الاستقبال": "Example: reception printer",
    "يُحفظ الاسم محلياً فقط، ولا يمنح الجهاز أي صلاحية أو ثقة على الراوتر.": "The name is stored locally only; it does not grant this device access or trust on the router.",
    "حفظ الاسم": "Save name",
    "تغيير مجموعة الجهاز": "Change device group",
    "مجموعة الصلاحيات الجديدة": "New permission group",
    "سيُفصل الجهاز من جلسته الحالية ثم يعيد المصادقة بمجموعة الصلاحيات الجديدة.": "The device will be disconnected from its current session and authenticate again with the new permission group.",
    "تغيير المجموعة وفصل الجلسة": "Change group and disconnect session",
    "تغيير مجموعة الحساب": "Change account group",
    "سيُفصل الحساب من جلسته الحالية لتطبيق مجموعة الصلاحيات الجديدة.": "The account will be disconnected from its current session to apply the new permission group.",
    "حذف حساب البوابة": "Delete portal account",
    "مثال: انتهت صلاحية الحساب": "Example: account expired",
    "سيُحذف الحساب من الراوتر وتُقطع جلسته الحالية. سيبقى سجل الإلغاء محلياً.": "The account will be deleted from the router and its current session disconnected. Its revocation record remains local.",
    "سبب الحذف (اختياري)": "Deletion reason (optional)",
    "حذف الحساب الآن": "Delete account now",
    "فصل متصل": "Disconnect user",
    "سيُفصل هذا الاتصال الآن. لا يُحذف الحساب أو سجل الجهاز.": "This session will be disconnected now. The account and device record are not deleted.",
    "فصل المتصل الآن": "Disconnect user now",
    "إضافة المتصل إلى الأجهزة الموثوقة": "Add online user to trusted devices",
    "الحساب الحالي": "Current account",
    "سحب الثقة من جهاز": "Revoke device trust",
    "مثال: انتهى عقد الجهاز": "Example: device contract ended",
    "سبب السحب (اختياري)": "Revocation reason (optional)",
    "سيُحذف حساب MAC من الراوتر وتُقطع جلسته الحالية. سيبقى سجل الجهاز محليًا كمُلغى.": "The MAC account will be deleted from the router and its current session disconnected. The local record remains marked as revoked.",
    "سحب الثقة الآن": "Revoke trust now",
    "فعّال": "Active",
    "نشط": "Active",
    "قبل المصادقة": "Pre-authentication",
    "محظور": "Blocked",
    "غير مسجّل محلياً": "Not in local records",
    "خارج التوزيع": "Out of routing",
    "حجز ثابت": "Static reservation",
    "عنوان ثابت": "Static address",
    "بلا عنوان": "No address",
    "حاضر": "Present",
    "مرئي بلا عنوان": "Seen without address",
    "حجز فقط": "Reserved only",
    "غير معروف": "Unknown",
    "عنوان عشوائي": "Random address",
    "ملغى": "Revoked",
    "مفقود من الراوتر": "Missing from router",
    "مكتمل": "Complete",
    "ناقص": "Incomplete",
    "محلي": "Local",
    "المنفذ يجب أن يكون رقماً.": "Port must be a number.",
    "أكمل عنوان الراوتر واسم المستخدم وكلمة المرور.": "Enter the router address, username, and password.",
    "اتصل بالراوتر أولاً.": "Connect to the router first.",
    "بلا واجهة عنوان": "No IP interface",
    "تسمية جهاز": "Name device",
    "اختر جهازاً من الجدول أولاً.": "Select a device from the table first.",
    "عنوان MAC المحدد غير صالح.": "The selected MAC address is invalid.",
    "فحص التداخل": "Check overlap",
    "حدّث قائمة الشبكات أولاً.": "Refresh the network list first.",
    "تعذر فحص مجمّعات الشبكات.": "Could not inspect network pools.",
    "اختر جهازاً واحداً أو أكثر من الجدول أولاً.": "Select one or more devices from the table first.",
    "لا توجد مصادقة على هذه الشبكة، لذلك لا توجد جلسة يمكن فصلها.": "This network has no authentication, so there is no session to disconnect.",
    "تم فصل الجلسات المحددة وإعادة قراءة الشبكة.": "Selected sessions were disconnected and the network was read again.",
    "لا توجد مصادقة على هذه الشبكة.": "This network has no authentication.",
    "تعذر فصل الجلسات المحددة.": "Could not disconnect the selected sessions.",
    "تعذر حفظ الاسم المحلي.": "Could not save the local name.",
    "اختر اتصالاً من الجدول أولاً.": "Select a session from the table first.",
    "هذا الاتصال لا يحمل عنوان MAC صالحاً.": "This session does not have a valid MAC address.",
    "حدّث مجموعات الصلاحيات أولاً.": "Refresh permission groups first.",
    "تمت إضافة الجهاز والتحقق منه على الراوتر.": "Device added and verified on the router.",
    "اكتب اسماً وصفياً للجهاز.": "Enter a description for the device.",
    "هذا الجهاز موثوق مسبقاً.": "This device is already trusted.",
    "اختر مجموعة صلاحيات للجهاز.": "Select a permission group for the device.",
    "اضبط كلمة مرور حسابات MAC من الإعدادات أولاً.": "Set the shared MAC password in Settings first.",
    "كلمة مرور حسابات MAC لا يجوز أن تساوي عنوان MAC.": "The MAC account password must not equal the MAC address.",
    "نُفذت الأوامر لكن الحساب لم يثبت في إعداد الراوتر.": "Commands ran, but the account was not confirmed in the router configuration.",
    "تعذر تنفيذ العملية على الراوتر.": "The operation could not be completed on the router.",
    "تعذر إتمام العملية.": "Could not complete the operation.",
    "فصل الاتصال الحالي": "Disconnect current session",
    "تم فصل الاتصال الحالي.": "Current session disconnected.",
    "رقم الجلسة غير صالح.": "Session ID is invalid.",
    "نُفذ الأمر لكن الجلسة ما زالت ظاهرة على الراوتر.": "The command ran, but the session is still visible on the router.",
    "تعذر فصل المتصل.": "Could not disconnect the user.",
    "أجهزة الإدارة": "Management devices",
    "تأكيد إضافة جهاز إدارة": "Confirm management device",
    "إخراج الخط": "Withdraw link",
    "إعادة الخط": "Restore link",
    "خطوط الإنترنت": "Internet links",
    "اختر خطاً أولاً.": "Select a link first.",
    "نسخ التقرير": "Copy report",
    "تم نسخ التقرير النصي.": "Text report copied.",
    "الإعدادات": "Settings",
    "تغيير كلمة السر": "Change password",
    "لا يوجد ملف MAC صالح.": "No valid MAC profile was found.",
    "تأكيد تغيير كلمة السر": "Confirm password change",
    "اكتملت العملية.": "Operation completed.",
    "إضافة جهاز": "Add device",
    "إضافة حساب": "Add account",
    "تمت إضافة الحساب والتحقق منه على الراوتر.": "Account added and verified on the router.",
    "أدخل اسم حساب صالحًا من أحرف وأرقام فقط.": "Enter a valid account name using letters and numbers only.",
    "كلمة المرور يجب أن تكون 8 محارف على الأقل.": "Password must be at least 8 characters.",
    "اختر مجموعة صلاحيات للحساب.": "Select a permission group for the account.",
    "اسم الحساب مسجل مسبقًا على الراوتر.": "This account already exists on the router.",
    "تغيير المجموعة": "Change group",
    "حذف الحساب": "Delete account",
    "تعديل الجهاز": "Edit device",
    "تعديل الحساب": "Edit account",
    "سحب الثقة": "Revoke trust",
    "تصدير الأجهزة الموثوقة": "Export trusted devices",
    "تصدير حسابات البوابة": "Export portal accounts",
    "تعذر حفظ التعديل.": "Could not save changes.",
    "البريد:": "E-mail:",
    "حدّث الشبكات لعرض الأجهزة المتصلة بها.": "Refresh networks to display their connected devices.",
    "حفظ إعداد الراوتر تلقائياً": "Save router configuration automatically",
    "فصل المحدد": "Disconnect selected",
    "مزامنة Firebase الآن": "Sync Firebase now",
    "تخزين محلي": "Local storage",
    "جارٍ مزامنة البيانات…": "Syncing data…",
    "المزامنة معلّقة؛ البيانات محفوظة محلياً": "Sync pending; data saved locally",
    "تمت المزامنة؛ حُفظت نسخ التعارض للاسترجاع": "Synced; conflict copies saved for recovery",
    "تغييرات محفوظة؛ بانتظار المزامنة": "Changes saved; sync pending",
    "البيانات متزامنة": "Data synchronized",
    "Firebase أساسي: مزامنة تلقائية بين الأجهزة مع حفظ محلي ونسخ للاسترجاع.": "Firebase primary: automatic device sync with local storage and recovery copies.",
    "استيراد بيانات اعتماد Firebase": "Import Firebase credentials",
    "ملف Firebase service account": "Firebase service account file",
    "لم يتم استيراد ملف Firebase بعد.": "No Firebase credential file has been imported.",
    "تم إعداد Firebase لمشروع: %s": "Firebase is configured for project: %s",
    "تم استيراد بيانات اعتماد Firebase. يمكنك المزامنة الآن.": "Firebase credentials imported. You can sync now.",
    "وضع التخزين": "Storage mode",
    "محلي فقط": "Local only",
    "Firebase أساسي": "Firebase primary",
    "محلي فقط: لا اتصال بـ Firebase.": "Local only: Firebase is not used.",
    "Firebase أساسي: البيانات السحابية هي المصدر الافتراضي، وتبقى نسخة محلية للعمل دون اتصال.": "Firebase primary: cloud data is the default source, with a local offline cache.",
    "تنزيل البيانات من Firebase": "Download data from Firebase",
    "رفع البيانات المحلية إلى Firebase": "Upload local data to Firebase",
    "اختيار بيانات Firebase أولاً": "Choose the initial Firebase data source",
    "استخدم بيانات Firebase": "Use Firebase data",
    "ارفع البيانات المحلية": "Upload local data",
    "إلغاء": "Cancel",
    "سيُنشأ ملف نسخة احتياطية محلية ثم ستستبدل بيانات Firebase بيانات هذا الجهاز. هل تريد المتابعة؟": "A local backup will be created, then Firebase data will replace this device's data. Continue?",
    "سيستبدل هذا الإجراء بيانات Firebase بالبيانات المحلية الحالية. هل تريد المتابعة؟": "This will replace Firebase data with this device's current local data. Continue?",
    "تم تنزيل بيانات Firebase مع نسخة احتياطية محلية.": "Firebase data was downloaded and a local backup was created.",
    "تم رفع البيانات المحلية إلى Firebase.": "Local data was uploaded to Firebase.",
    "ملف MAC": "MAC profile",
    "تأكيد كلمة السر": "Confirm password",
    "متابعة": "Continue",
    "كلمتا السر غير متطابقتين.": "The passwords do not match.",
    "أدخل كلمة سر جديدة بدلاً من القيمة الافتراضية.": "Enter a new password instead of the default value.",
    "كلمة السر غير صالحة.": "The password is invalid.",
    "لا يوجد ملف MAC صالح.": "No valid MAC profile was found.",
    "تغيير كلمة السر": "Change password",
    "تأكيد تغيير كلمة السر": "Confirm password change",
    "نسخ": "Copy",
})

# The application-policy reader is intentionally bilingual too.  Keeping these
# labels in the same translation adapter prevents a newly added safety screen
# from silently breaking the English-only UI contract.
_TEXT_BY_ARABIC.update({
    "راجع المجموعة وACL وسياسة التطبيقات المرتبطة بالواجهة قبل أن تغيّر أي قاعدة.":
        "Review the group, ACL and interface application policy before changing any rule.",
    "واجهة تطبيق السياسة": "Policy interface",
    "التطبيقات والتواقيع": "Applications & signatures",
    "ابحث عن تطبيق أو توقيع…": "Search applications or signatures…",
    "التطبيق / التوقيع": "Application / signature",
    "الفئة": "Category",
    "الحالة الفعلية": "Effective state",
    "مصدر القرار": "Decision source",
    "شرح المحدد": "Explain selection",
    "حظر المحدد": "Block selected",
    "السماح للمحدد": "Allow selected",
    "نسخ تقرير السياسة": "Copy policy report",
    "يعرض التطبيق ما يقرأه من الراوتر؛ لا يغيّر أي قاعدة من هذه الشاشة.":
        "Shows what the router reports; this screen does not change a rule.",
    "تم نسخ تقرير السياسة": "Policy report copied",
    "تفاصيل التطبيق": "Application details",
})


def tr(value):
    """Translate a visible Qt string; values from the router are never translated."""
    if ACTIVE_LANGUAGE != "en" or not isinstance(value, str):
        return value
    return _TEXT_BY_ARABIC.get(value, value)


def current_direction():
    return Qt.LeftToRight if ACTIVE_LANGUAGE == "en" else Qt.RightToLeft


class LocalizedLabel(_QT_LABEL):
    def __init__(self, *args, **kwargs):
        args = tuple(tr(arg) if isinstance(arg, str) else arg for arg in args)
        super().__init__(*args, **kwargs)

    def setText(self, value):
        super().setText(tr(value))


class LocalizedButton(_QT_BUTTON):
    def __init__(self, *args, **kwargs):
        args = tuple(tr(arg) if isinstance(arg, str) else arg for arg in args)
        super().__init__(*args, **kwargs)

    def setText(self, value):
        super().setText(tr(value))


class LocalizedLineEdit(_QT_LINE_EDIT):
    def setPlaceholderText(self, value):
        super().setPlaceholderText(tr(value))


class LocalizedFormLayout(_QT_FORM):
    def addRow(self, *args):
        if args and isinstance(args[0], str):
            args = (tr(args[0]),) + args[1:]
        return super().addRow(*args)


class LocalizedDialog(_QT_DIALOG):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        super().setLayoutDirection(current_direction())

    def setWindowTitle(self, title):
        super().setWindowTitle(tr(title))

    def setLayoutDirection(self, _direction):
        super().setLayoutDirection(current_direction())

    def _translate_children(self):
        for child in self.findChildren(_QT_BUTTON):
            child.setText(tr(child.text()))

    def exec(self):
        self._translate_children()
        return super().exec()

    def open(self):
        self._translate_children()
        return super().open()


class LocalizedMessageBox(_QT_MESSAGE_BOX):
    def setWindowTitle(self, title):
        super().setWindowTitle(tr(title))

    def setText(self, text):
        super().setText(tr(text))

    @staticmethod
    def information(parent, title, text, *args):
        return _QT_MESSAGE_BOX.information(parent, tr(title), tr(text), *args)

    @staticmethod
    def warning(parent, title, text, *args):
        return _QT_MESSAGE_BOX.warning(parent, tr(title), tr(text), *args)

    @staticmethod
    def critical(parent, title, text, *args):
        return _QT_MESSAGE_BOX.critical(parent, tr(title), tr(text), *args)

    @staticmethod
    def question(parent, title, text, *args):
        return _QT_MESSAGE_BOX.question(parent, tr(title), tr(text), *args)


# All following Qt construction uses the localised widgets above.
QLabel = LocalizedLabel
QPushButton = LocalizedButton
QLineEdit = LocalizedLineEdit
QFormLayout = LocalizedFormLayout
QDialog = LocalizedDialog
QMessageBox = LocalizedMessageBox


SURFACE_EN = {
    "devices": ("Trusted Devices", ("MAC Address", "Description", "Group", "State", "Added", "Note")),
    "portal": ("Portal Accounts", ("Account", "Description", "Group", "State", "Added", "Note")),
    "online": ("Online Users", ("ID", "Account", "Description", "Connection method", "Group", "IP Address", "MAC Address", "Status")),
    "vlans": ("Connected by Network", ("IP Address", "MAC Address", "Description", "Vendor", "Port", "Address type", "Presence", "Authentication", "Other networks")),
    "management": ("Management Devices", ("IP Address", "MAC Address", "Description", "Network", "Rule", "DHCP binding", "Static ARP", "State", "Local state")),
    "wan": ("Internet Links", ("Link", "Interface", "Gateway", "Routing", "Ping", "HTTPS", "Latency", "Bandwidth", "Physical port", "Verdict")),
    "groups": ("Permission Groups", ("Group", "ACL", "Members")),
    "settings": ("Settings", ()),
    "log": ("Command Log", ()),
    "nat": ("Port Forwarding", ("WAN interface", "WAN address", "Protocol", "External port", "Device address", "Internal port")),
}


def localized_surface(language):
    if language != "en":
        return APP_PAGES
    return {page_id: {**item, "title": SURFACE_EN[page_id][0], "columns": SURFACE_EN[page_id][1]}
            for page_id, item in APP_PAGES.items()}


STYLE = """
QWidget { font-family: "IBM Plex Sans Arabic", "Noto Sans Arabic", "Segoe UI"; color: #172033; }
QMainWindow, QWidget#canvas, QDialog, QMessageBox { background: #F5F7FB; }
QFrame#sidebar { background: #132238; }
QLabel#brand { color: white; font-size: 20px; font-weight: 700; }
QLabel#subtle { color: #667085; font-size: 12px; }
QLabel#sideSub { color: #A8BCD5; font-size: 12px; }
QLabel#sideVersion { color: #7E9BBC; font-size: 11px; font-weight: 600; }
QLabel#afzLogo { background: transparent; }
QLabel#afzCredit { color: #C6D3E2; font-weight: 700; }
QLabel#routerStatus[connected="true"], QLabel#connectionStatus[connected="true"] { color: #067647; font-weight: 700; }
QLabel#routerStatus[connected="false"], QLabel#connectionStatus[connected="false"] { color: #B42318; font-weight: 700; }
QLabel#operationStatus[state="working"] { color: #B54708; font-weight: 700; }
QLabel#operationStatus[state="ok"] { color: #067647; font-weight: 700; }
QLabel#operationStatus[state="error"] { color: #B42318; font-weight: 700; }
QFrame#busyOverlay { background: rgba(19, 34, 56, 190); }
QFrame#busyPanel { background: #FFFFFF; border: 1px solid #D0D5DD; border-radius: 12px; }
QLabel#busyTitle { color: #172033; font-size: 15px; font-weight: 700; }
QLabel#busyHint { color: #667085; font-size: 12px; }
QProgressBar#busySpinner { border: 0; background: #EAF2FF; border-radius: 4px; min-height: 8px; max-height: 8px; }
QProgressBar#busySpinner::chunk { background: #155EEF; border-radius: 4px; }
QLabel#title { font-size: 24px; font-weight: 700; }
QFrame#topbar, QFrame#panel, QFrame#metric { background: #FFFFFF; border: 1px solid #E4E7EC; border-radius: 12px; }
QTextEdit#commandLog { background: #050A12; color: #FFFFFF; border: 1px solid #26364D; border-radius: 8px; padding: 10px; font-family: "SF Mono", "Menlo", "Consolas", monospace; font-size: 12px; }
QPushButton { background: #FFFFFF; border: 1px solid #D0D5DD; border-radius: 7px; padding: 8px 13px; }
QPushButton:hover { background: #F9FAFB; border-color: #98A2B3; }
QPushButton#primary { background: #155EEF; color: white; border-color: #155EEF; font-weight: 700; }
QPushButton#danger { background: #B42318; color: white; border-color: #B42318; font-weight: 700; }
QPushButton#nav { color: #C6D3E2; background: transparent; border: 0; padding: 10px 13px; text-align: left; }
QPushButton#nav[rtl="true"] { text-align: right; }
QPushButton#nav:hover { background: #213752; color: white; }
QPushButton#nav:checked { background: #26496F; color: white; font-weight: 700; }
QLineEdit { background: white; color: #172033; border: 1px solid #D0D5DD; border-radius: 7px; padding: 8px; }
QLineEdit:focus { border: 2px solid #84ADFF; }
QLineEdit[readOnly="true"] { background: #F9FAFB; color: #344054; }
QLineEdit[readOnly="true"]:focus { border: 1px solid #D0D5DD; }
QComboBox { background: #FFFFFF; color: #172033; border: 1px solid #D0D5DD; border-radius: 7px; padding: 7px; }
QComboBox:focus { border: 1px solid #D0D5DD; }
QComboBox QAbstractItemView { background: #FFFFFF; color: #172033; selection-background-color: #EAF2FF; selection-color: #172033; }
QCheckBox { background: #FFFFFF; border: 1px solid #D0D5DD; border-radius: 7px; padding: 9px 12px; spacing: 10px; font-weight: 600; }
QCheckBox:hover { background: #F9FAFB; border-color: #98A2B3; }
QCheckBox::indicator { width: 20px; height: 20px; border: 2px solid #667085; border-radius: 5px; background: #FFFFFF; }
QCheckBox::indicator:checked { background: #155EEF; border-color: #155EEF; image: none; }
QDialog QLabel, QMessageBox QLabel { background: transparent; color: #172033; }
QDialogButtonBox QPushButton, QMessageBox QPushButton { min-width: 96px; color: #172033; background: #FFFFFF; }
QDialogButtonBox QPushButton:default, QMessageBox QPushButton:default { color: white; background: #155EEF; border-color: #155EEF; }
QTableWidget { background: white; border: 0; selection-background-color: #EAF2FF; selection-color: #172033; }
QHeaderView::section { background: #F9FAFB; color: #475467; border: 0; border-bottom: 1px solid #EAECF0; padding: 10px; font-weight: 700; }
QTableWidget::item { padding: 8px; border-bottom: 1px solid #F0F2F5; }
QTableWidget::item:focus { outline: none; }
"""


class Worker(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn())
        except Exception as exc:
            self.failed.emit(str(exc))


class FullRowCheckBox(QCheckBox):
    """شيك بوكس تُفعّل أي نقرة داخل صفّه، لا المربع الصغير وحده."""
    def __init__(self, text="", *args, **kwargs):
        super().__init__(tr(text), *args, **kwargs)

    def setText(self, text):
        super().setText(tr(text))

    def hitButton(self, position):
        return self.rect().contains(position)


class NoFocusCellDelegate(QStyledItemDelegate):
    """يبقي تحديد الصف والنسخ، لكنه يلغي مستطيل التركيز الأزرق داخل الخلية."""
    def paint(self, painter, option, index):
        option.state &= ~QStyle.State_HasFocus
        super().paint(painter, option, index)


class ReadController:
    """بيانات Qt عبر المحرك الموجود؛ الكتابة تنتقل فقط بعد اختبار التكافؤ."""

    def __init__(self, demo=False):
        if demo:
            legacy.paramiko = legacy._DemoParamiko()
            legacy.SETTINGS_FILE = os.path.join(legacy.BASE_DIR, "demo_settings.json")
            legacy.DB_FILE = os.path.join(legacy.BASE_DIR, "demo_devices.json")
            legacy.LOG_FILE = os.path.join(legacy.BASE_DIR, "demo_session.log")
        self.settings = legacy.load_settings()
        self.db = legacy.LocalDB()
        self.router = legacy.RouterSession(self._write_router_log)
        self.users, self.groups, self.online, self.states = {}, {}, [], {}
        # Raw policy components are kept separately from the simple group list.
        # A group ACL is not an interface traffic-policy binding.
        self.application_config = {}
        self.vlans, self.vlan_state, self.vlan_overlap = [], None, None
        self.mgmt_state, self.mgmt_rows, self.wan_lines = None, [], []
        self.nat_rules, self.nat_interfaces = [], []
        self.firebase = legacy.FirebaseSync(self.settings)
        self._firebase_dirty = True
        self.firebase_error = ""
        self.firebase_conflicts = self.db.data.get(cloud_merge.META_KEY, {}).get("conflicts", 0)
        self.db.on_save = self._on_local_saved

    def _on_local_saved(self):
        self._firebase_dirty = True

    def _write_router_log(self, text):
        """يحفظ مسار Qt ذاته في السجل، من دون أسرار قابلة للقراءة."""
        try:
            with open(legacy.LOG_FILE, "a", encoding="utf-8") as handle:
                handle.write(legacy.mask_password(text or ""))
        except OSError:
            pass

    def connect(self, host, port, username, password):
        self.router.connect(host, port, username, password)
        self.settings.update({"host": host, "port": port, "username": username})
        legacy.save_settings(self.settings)
        return self.refresh()

    def refresh(self):
        if not self.router.connected:
            return
        self.users = legacy.parse_local_users(self.router.read_aaa())
        group_config = self.router.read_group_acls()
        self.groups = legacy.parse_groups(self.router.read_groups(), group_config)
        self.application_config = legacy.parse_application_policy_config(group_config)
        self.online = legacy.parse_online(self.router.read_online())
        self.states = self.router.read_local_user_states()

    def refresh_online(self):
        """تحديث جلسات الوصول فقط، من دون أي تغيير في إعداد الراوتر."""
        if not self.router.connected:
            return []
        self.online = legacy.parse_online(self.router.read_online())
        return self.online

    def block_application(self, policy, application):
        result = legacy.ApplicationPolicyOperations(
            self.router, self.settings.get("auto_save_config", True)).block(policy, application)
        if result.ok:
            self.refresh()
        return result

    def allow_application(self, policy, application, allow_bundle=False):
        result = legacy.ApplicationPolicyOperations(
            self.router, self.settings.get("auto_save_config", True)).allow(
                policy, application, allow_bundle)
        if result.ok:
            self.refresh()
        return result

    def refresh_vlans(self, selected_vid=""):
        """يحدّث قائمة VLAN ثم يقرأ الشبكة المختارة من قارئ المحرك المشترك."""
        if not self.router.connected:
            return None
        self.vlans = self.router.read_vlans()
        if not self.vlans:
            self.vlan_state = None
            return None
        wanted = str(selected_vid or "")
        network = next((item for item in self.vlans if item["vid"] == wanted), None)
        if network is None:
            network = next((item for item in self.vlans if item.get("iface")), self.vlans[0])
        return self.select_vlan(network["vid"])

    def select_vlan(self, vid):
        """يقرأ العملاء للشبكة المحددة، بما في ذلك شكل الواجهة الفرعية."""
        if not self.router.connected:
            return None
        wanted = str(vid or "")
        network = next((item for item in self.vlans if item["vid"] == wanted), None)
        if network is None:
            return None
        state = self.router.read_vlan_clients(network["vid"], network.get("iface", ""))
        state["net"] = dict(network)
        self.vlan_state = state
        return state

    def disconnect_online(self, user_id):
        result = legacy.OnlineSessionOperations(self.router).disconnect(user_id)
        if result.online is not None:
            self.online = result.online
        return result

    def trust_online(self, session, name, group, note):
        """ينشئ حساب MAC من القيم المقروءة في جلسة محددة، لا من إدخال حر."""
        mac12 = legacy.normalize_mac((session or {}).get("mac", ""))
        if not mac12:
            return legacy.ActionResult(False, "bad_mac")
        if not (name or "").strip():
            return legacy.ActionResult(False, "missing_name")
        return self.create_device(mac12, name.strip(), group, note.strip())

    def close(self):
        self.router.close()

    def create_device(self, mac, name, group, note):
        """أول عملية كتابة في Qt؛ تستعمل خدمة AR730 المشتركة حرفياً."""
        mac12 = legacy.normalize_mac(mac)
        if not mac12:
            return legacy.ActionResult(False, "bad_mac")
        operation = legacy.TrustedDeviceOperations(
            self.router, self.db, self.users,
            self.settings.get("mac_shared_password", ""),
            self.settings.get("auto_save_config", True))
        result = operation.create(mac12, name, group, note)
        if result.users is not None:
            self.users = result.users
        if result.states is not None:
            self.states = result.states
        return result

    def update_device_metadata(self, mac, name, note):
        mac12 = legacy.normalize_mac(mac)
        if not mac12:
            return legacy.ActionResult(False, "bad_mac")
        return legacy.TrustedDeviceOperations(None, self.db, {}, "", False).update_metadata(
            mac12, name, note)

    def update_vlan_metadata(self, mac, name, note):
        """اسم محلي لجهاز شبكة؛ لا يضيفه إلى قائمة الأجهزة الموثوقة."""
        return legacy.NetworkDeviceNameOperations(self.db).update(mac, name, note)

    def scan_vlan_overlap(self):
        """يفحص عقود كل شبكات VLAN بالعملية المشتركة، من دون تغيير الراوتر."""
        result = legacy.VlanOverlapOperations(self.router, self.db).scan(self.vlans)
        if result.ok:
            self.vlan_overlap = result.data["report"]
        return result

    def disconnect_vlan_devices(self, macs):
        """يفصل جلسات العملاء المختارة ثم يعيد قراءة الشبكة ذاتها."""
        result = legacy.VlanSessionOperations(self.router, self.db).disconnect(
            self.vlan_state, macs)
        if result.code != "router_error" and self.vlan_state:
            self.select_vlan(self.vlan_state.get("vid", ""))
        return result

    def exclude_dhcp_range(self, start, end, disconnect_leases=False):
        """يستبعد نطاقاً من DHCP للشبكة المحددة ويعيد قراءة النتيجة."""
        result = legacy.DhcpPoolOperations(
            self.router, self.db, self.settings.get("auto_save_config", True)).exclude_range(
                self.vlan_state, start, end, disconnect_leases)
        if result.code not in {"router_error", "no_dhcp", "bad_range", "outside_network",
                               "overlap_excluded", "binding_in_range", "not_confirmed"} and self.vlan_state:
            self.select_vlan(self.vlan_state.get("vid", ""))
        return result

    def bind_vlan_dhcp(self, mac, ip, description="", disconnect=False):
        """ينشئ DHCP static-bind من الجهاز المحدد دون صلاحيات إدارة إضافية."""
        result = legacy.DhcpPoolOperations(
            self.router, self.db, self.settings.get("auto_save_config", True)).bind(
                self.vlan_state, mac, ip, description, disconnect)
        if result.code not in {"router_error", "no_dhcp", "bad_mac", "outside_network",
                               "address_excluded", "ip_in_use", "mac_bound", "not_confirmed"} and self.vlan_state:
            self.select_vlan(self.vlan_state.get("vid", ""))
        return result

    def update_portal_metadata(self, username, name, note):
        return legacy.PortalAccountOperations(self.db).update_metadata(username, name, note)

    def create_portal(self, username, password, name, group, note):
        result = legacy.PortalAccountOperations(
            self.db, self.router, self.users,
            self.settings.get("auto_save_config", True)).create(
                username, password, name, group, note)
        if result.users is not None:
            self.users = result.users
        return result

    def change_portal_password(self, username, password):
        return legacy.PortalAccountOperations(
            self.db, self.router, self.users,
            self.settings.get("auto_save_config", True)).change_password(username, password)

    def change_portal_group(self, username, group):
        result = legacy.PortalAccountOperations(
            self.db, self.router, self.users,
            self.settings.get("auto_save_config", True)).change_group(
                username, group, self.settings.get("portal_domain", ""))
        if result.users is not None:
            self.users = result.users
        return result

    def revoke_portal(self, username, reason):
        result = legacy.PortalAccountOperations(
            self.db, self.router, self.users,
            self.settings.get("auto_save_config", True)).revoke(
                username, reason, self.settings.get("portal_domain", ""))
        if result.users is not None:
            self.users = result.users
        return result

    def change_device_group(self, mac, group):
        mac12 = legacy.normalize_mac(mac)
        if not mac12:
            return legacy.ActionResult(False, "bad_mac")
        result = legacy.TrustedDeviceOperations(
            self.router, self.db, self.users,
            self.settings.get("mac_shared_password", ""),
            self.settings.get("auto_save_config", True)).change_group(mac12, group)
        if result.users is not None:
            self.users = result.users
        return result

    def revoke_device(self, mac, reason):
        mac12 = legacy.normalize_mac(mac)
        if not mac12:
            return legacy.ActionResult(False, "bad_mac")
        result = legacy.TrustedDeviceOperations(
            self.router, self.db, self.users,
            self.settings.get("mac_shared_password", ""),
            self.settings.get("auto_save_config", True)).revoke(mac12, reason)
        if result.users is not None:
            self.users = result.users
        return result

    def device_rows(self):
        """نفس صفوف جدول Tk، بما فيها الأرشيف المحلي والحسابات المفقودة."""
        macs, _, _ = legacy.split_user_kinds(self.users)
        rows, seen = [], set()
        for mac12, record in sorted(macs.items()):
            local = self.db.device(mac12) or {}
            seen.add(mac12)
            group = record.get("group") or ""
            state = "فعّال"
            if not local:
                state = "غير مسجّل محلياً"
            if not group:
                state += " ⚠"
            if self.states.get(mac12) == "B":
                state = "محظور"
            rows.append([legacy.mac_pretty(mac12), local.get("name", ""), group,
                         state, local.get("added", ""), local.get("note", "")])
        for mac12, local in sorted(self.db.data["devices"].items()):
            if mac12 in seen:
                continue
            revoked = local.get("state") == "revoked"
            note = " — ".join(x for x in (local.get("revoke_reason", ""),
                                            local.get("note", "")) if x) if revoked else local.get("note", "")
            rows.append([legacy.mac_pretty(mac12), local.get("name", ""),
                         local.get("group", ""), "ملغى" if revoked else "مفقود من الراوتر",
                         local.get("added", ""), note])
        return rows

    def export_devices(self, path):
        legacy.write_utf8_csv(path, APP_PAGES["devices"]["columns"], self.device_rows())
        return path

    def portal_rows(self):
        """نفس صفوف بوابة Tk، بما فيها الأرشيف المحلي والحسابات المفقودة."""
        _, accounts, _ = legacy.split_user_kinds(self.users)
        rows, seen = [], set()
        for username, record in sorted(accounts.items()):
            local = self.db.portal(username) or {}
            seen.add(username)
            group = record.get("group") or ""
            state = "فعّال" if local else "غير مسجّل محلياً"
            if not group:
                state += " ⚠"
            rows.append([username, local.get("name", ""), group, state,
                         local.get("added", ""), local.get("note", "")])
        for username, local in sorted(self.db.data["portal"].items()):
            if username in seen:
                continue
            revoked = local.get("state") == "revoked"
            note = " — ".join(x for x in (local.get("revoke_reason", ""),
                                            local.get("note", "")) if x) if revoked else local.get("note", "")
            rows.append([username, local.get("name", ""), local.get("group", ""),
                         "ملغى" if revoked else "مفقود من الراوتر",
                         local.get("added", ""), note])
        return rows

    def online_rows(self):
        """جلسات الوصول مع الوصف، طريقة المصادقة، ومجموعة الحساب."""
        rows = []
        for session in self.online:
            mac12 = legacy.normalize_mac(session.get("mac", ""))
            description = self.db.name_of(mac12) if mac12 else ""
            portal = self.db.portal(session.get("user", "")) or {}
            device = self.db.device(mac12) if mac12 else {}
            if not description:
                description = portal.get("name", "")
            account = self.users.get(session.get("user", "")) or {}
            service_types = account.get("service_types") or set()
            connection_method = self._connection_method(service_types, mac12)
            group = account.get("group") or (device or {}).get("group") or portal.get("group", "")
            rows.append({**session, "description": description,
                         "connection_method": connection_method, "group": group})
        return rows

    @staticmethod
    def _connection_method(service_types, mac12):
        """اسم مفهوم لطريقة خدمة AAA، مع بديل واضح للجلسة غير المكتملة."""
        names = {
            "8021x": "802.1X", "web": "Web portal", "ssh": "SSH", "http": "HTTP",
            "telnet": "Telnet", "terminal": "Terminal", "ppp": "PPP", "sslvpn": "SSL VPN",
        }
        methods = [names[item] for item in ("8021x", "web", "ssh", "http", "telnet", "terminal", "ppp", "sslvpn")
                   if item in service_types]
        if methods:
            return " + ".join(methods)
        return "MAC authentication" if mac12 else "—"

    def export_portal(self, path):
        legacy.write_utf8_csv(path, APP_PAGES["portal"]["columns"], self.portal_rows())
        return path

    # الإجراءات التالية تحافظ على المحرك الواحد: Qt لا تبني أوامر VRP بنفسها.
    def refresh_management(self):
        self.mgmt_state = self.router.read_mgmt_state()
        self.mgmt_rows = legacy.mgmt_entries(self.mgmt_state)
        return self.mgmt_rows

    def suggested_management_ip(self, iface):
        """أعلى عنوان حر فعلياً في شبكة الإدارة المختارة، للعرض فقط."""
        state = self.router.read_mgmt_state(iface)
        network = next((net for net in state.get("networks", []) if net.get("iface") == iface), None)
        if network is None:
            return ""
        pool = state.get("pool") or {"used": {}}
        taken = ({net["ip"] for net in state.get("networks", [])}
                 | set(pool.get("used", {}))
                 | {binding["ip"] for binding in state.get("binds", [])}
                 | set(state.get("arp_static", {})))
        return legacy.mgmt_free_ip(network, taken)

    def management_rows(self):
        rows = []
        for entry in self.mgmt_rows:
            local = self.db.data["mgmt"].get(entry["ip"], {})
            device = self.db.device(entry["mac"]) if entry.get("mac") else {}
            rows.append([entry["ip"], legacy.mac_pretty(entry["mac"]) if entry.get("mac") else "",
                         local.get("name") or (device or {}).get("name") or entry.get("desc", ""),
                         entry.get("iface", ""), ", ".join("%s/%d" % rule for rule in entry["rules"]) or "—",
                         "✓" if entry["bind"] else "✗", "✓" if entry["arp"] else "✗",
                         "مكتمل" if entry["complete"] else "ناقص", "محلي" if local else "—"])
        return rows

    def add_management(self, mac, name, iface, ip, acl):
        mac12 = legacy.normalize_mac(mac)
        if not mac12:
            return legacy.ActionResult(False, "bad_mac")
        if not (name or "").strip():
            return legacy.ActionResult(False, "missing_name")
        state = self.router.read_mgmt_state(iface, mac12)
        plan, errors, warns = legacy.plan_mgmt_device(state, mac12, iface, ip, acl, mac12 in self.users)
        if errors:
            return legacy.ActionResult(False, "invalid_plan", data={"errors": errors, "warnings": warns})
        result = self.router.apply_mgmt_device(plan, legacy.mgmt_description(name))
        self.mgmt_state = result.get("state") or self.router.read_mgmt_state()
        self.mgmt_rows = legacy.mgmt_entries(self.mgmt_state)
        if result.get("failed_step"):
            return legacy.ActionResult(False, "partial", data=result)
        self.db.upsert_mgmt(plan["ip"], mac12, name.strip(), iface, acl)
        self.db.log("mgmt_add", plan["ip"], "%s / %s" % (legacy.mac_pretty(mac12), iface))
        if self.settings.get("auto_save_config", True):
            self.router.save_config()
        return legacy.ActionResult(not result.get("missing"), "added" if not result.get("missing") else "partial",
                                   data={"result": result, "plan": plan, "warnings": warns})

    def remove_management(self, entry):
        if not entry:
            return legacy.ActionResult(False, "missing_selection")
        result = self.router.remove_mgmt_device(entry)
        self.mgmt_state = result["state"]
        self.mgmt_rows = legacy.mgmt_entries(self.mgmt_state)
        if result["errors"] or result["left"]:
            return legacy.ActionResult(False, "partial", data=result)
        if self.settings.get("auto_save_config", True):
            self.router.save_config()
        self.db.drop_mgmt(entry["ip"])
        self.db.log("mgmt_remove", entry["ip"], "")
        return legacy.ActionResult(True, "removed")

    def check_wan(self, live=True):
        withdrawn = self.settings.setdefault("withdrawn_lines", {})
        self.wan_lines = self.router.read_wan_lines(withdrawn, live_ping=live)
        stale = [gw for gw in withdrawn if any(line["gw"] == gw and line["in_config"] for line in self.wan_lines)]
        for gw in stale:
            withdrawn.pop(gw, None)
        if stale:
            legacy.save_settings(self.settings)
        return self.wan_lines

    def refresh_nat(self):
        """تحميل تحويلات المنافذ وواجهات WAN المتاحة، بلا أي كتابة."""
        self.nat_rules, self.nat_interfaces = self.router.read_static_nat()
        return self.nat_rules

    def add_static_nat(self, interface, external_port, inside_ip, inside_port):
        result = legacy.StaticNatOperations(
            self.router, self.settings.get("auto_save_config", True)).create(
                interface, external_port, inside_ip, inside_port)
        if result.ok:
            self.refresh_nat()
            rule = result.data["rule"]
            self.db.log("nat_add", "%s/%s" % (rule["interface"], rule["external_port"]),
                        "%s:%s/tcp" % (rule["inside_ip"], rule["inside_port"]))
        return result

    def edit_static_nat(self, original, interface, external_port, inside_ip, inside_port):
        result = legacy.StaticNatOperations(
            self.router, self.settings.get("auto_save_config", True)).edit(
                original, interface, external_port, inside_ip, inside_port)
        if result.ok:
            self.refresh_nat()
            rule = result.data["rule"]
            self.db.log("nat_edit", "%s/%s" % (rule["interface"], rule["external_port"]),
                        "%s:%s/tcp" % (rule["inside_ip"], rule["inside_port"]))
        return result

    def delete_static_nat(self, rule):
        result = legacy.StaticNatOperations(
            self.router, self.settings.get("auto_save_config", True)).delete(rule)
        if result.ok:
            self.refresh_nat()
            self.db.log("nat_delete", "%s/%s" % (rule["interface"], rule["external_port"]),
                        "%s:%s/tcp" % (rule["inside_ip"], rule["inside_port"]))
        return result

    def withdraw_wan(self, gw):
        line = next((x for x in self.wan_lines if x["gw"] == gw), None)
        if not line:
            return legacy.ActionResult(False, "missing_selection")
        if line.get("withdrawn") or not line.get("in_config"):
            return legacy.ActionResult(False, "already_out")
        other = [x for x in self.wan_lines if x["gw"] != gw and not x.get("withdrawn")
                 and x.get("route_state") == "Active" and x.get("health") in ("ok", "slow")]
        if not other:
            return legacy.ActionResult(False, "last_line")
        removed = self.router.withdraw_wan_line(gw)
        self.settings.setdefault("withdrawn_lines", {})[gw] = {"track": list(removed["track"]) if removed["track"] else None,
            "reason": "manual", "at": legacy.now_stamp(), "line": removed["line"], "health": line.get("health")}
        legacy.save_settings(self.settings)
        self.db.log("wan_withdraw", gw, "manual")
        if self.settings.get("auto_save_config", True): self.router.save_config()
        self.check_wan(live=False)
        return legacy.ActionResult(True, "withdrawn")

    def restore_wan(self, gw):
        line = next((x for x in self.wan_lines if x["gw"] == gw), None)
        rec = self.settings.setdefault("withdrawn_lines", {}).get(gw)
        if not line or not line.get("withdrawn") or not rec:
            return legacy.ActionResult(False, "not_out")
        self.router.restore_wan_line(gw, rec.get("track"))
        self.settings["withdrawn_lines"].pop(gw, None)
        legacy.save_settings(self.settings)
        self.db.log("wan_restore", gw, "")
        if self.settings.get("auto_save_config", True): self.router.save_config()
        self.check_wan(live=False)
        return legacy.ActionResult(True, "restored")

    def wan_report(self):
        return "\n".join("%s (%s) — %s" % (line.get("desc") or line["gw"], line["gw"], line.get("verdict", "—")) for line in self.wan_lines)

    def save_preferences(self, values):
        previous_mode = self.settings.get("storage_mode", "local")
        self.settings.update(values)
        if self.settings.get("storage_mode") not in {"local", "firebase"}:
            self.settings["storage_mode"] = "local"
        legacy.save_settings(self.settings)
        self.firebase = legacy.FirebaseSync(self.settings)
        if self.settings["storage_mode"] == "firebase" and not self.firebase.configured():
            self.settings["storage_mode"] = previous_mode
            legacy.save_settings(self.settings)
            return legacy.ActionResult(False, "bad_config")
        self._firebase_dirty = True
        return legacy.ActionResult(True, "saved")

    def rotate_mac_password(self, profile, password):
        problem = legacy.mac_password_problem(password)
        if problem: return legacy.ActionResult(False, problem)
        profiles = self.router.read_mac_profiles()
        if profile not in profiles: return legacy.ActionResult(False, "missing_profile")
        self.users = legacy.parse_local_users(self.router.read_aaa())
        macs = sorted(legacy.split_user_kinds(self.users)[0])
        states = self.router.read_local_user_states()
        result = self.router.rotate_mac_password(profile, password, macs,
                                                 unblock=[mac for mac, state in states.items() if state == "B"])
        if not result["profile_ok"]: return legacy.ActionResult(False, "profile_failed", data=result)
        self.settings.update({"mac_shared_password": password, "mac_access_profile": profile})
        legacy.save_settings(self.settings)
        if self.settings.get("auto_save_config", True): self.router.save_config()
        self.db.log("rotate_mac_password", profile, "%d accounts" % len(macs))
        return legacy.ActionResult(not result["failed"], "rotated" if not result["failed"] else "partial", data=result)

    def read_mac_password_profiles(self):
        """يجلب ملفات MAC في خيط العامل؛ لا نسمح لزر الواجهة بحجب Qt."""
        return self.router.read_mac_profiles()

    def _firebase_ready(self):
        if self.settings.get("storage_mode") != "firebase":
            return legacy.ActionResult(False, "storage_mode_local",
                                       error="Firebase is disabled while Local-only storage is selected.")
        if not self.firebase.configured():
            return legacy.ActionResult(False, "bad_config")
        return None

    def _backup_local_database(self):
        """Keep a recoverable copy before cloud data replaces the local cache."""
        backup_dir = os.path.join(os.path.dirname(self.db.path), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%S.%fZ")
        destination = os.path.join(backup_dir, "ar730_devices_before_firebase_%s.json" % stamp)
        legacy.atomic_json_write(destination, self.db.data)
        return destination

    def firebase_job(self):
        """Capture immutable inputs; the network worker never touches live app data."""
        problem = self._firebase_ready()
        if problem:
            return problem
        transport = getattr(self, "_firebase_transport", None)
        credential_keys = ("firebase_api_key", "firebase_project_id", "firebase_email",
                           "firebase_password", "firebase_service_account_file")
        if transport is None or any(self.settings.get(k) != transport.settings.get(k) for k in credential_keys):
            transport = legacy.FirebaseSync(copy.deepcopy(self.settings))
            self._firebase_transport = transport
        endpoint = transport._url()
        local = self.firebase_snapshot()
        checkpoint = self.db.data.get(cloud_merge.META_KEY, {})
        base = checkpoint.get("base") if checkpoint.get("endpoint") == endpoint else None
        if base is not None:
            cloud_merge.validate(base)
        return {"local": local, "endpoint": endpoint,
                "run": lambda: cloud_merge.synchronize(transport, local, base)}

    def firebase_snapshot(self):
        local = cloud_merge.snapshot(self.db.data, self.settings)
        checkpoint = self.db.data.get(cloud_merge.META_KEY, {})
        local["deleted"] = copy.deepcopy(checkpoint.get("base", {}).get("deleted", []))
        return local

    def firebase_accept(self, job, result):
        """Apply only on the UI thread while no router-operation worker is writing."""
        if self.settings.get("storage_mode") != "firebase" or self.firebase._url() != job["endpoint"]:
            self._firebase_dirty = True
            return legacy.ActionResult(False, "configuration_changed")
        current = self.firebase_snapshot()
        committed = cloud_merge.validate(result["state"])
        # Edits made during the request remain pending. They must not be replaced
        # by the acknowledged snapshot, even if they affect the same field.
        projected, unused = cloud_merge.merge(job["local"], committed, current)
        changed = projected["db"] != current["db"] or projected["settings"] != current["settings"]
        backup = self._backup_local_database() if changed or cloud_merge.META_KEY not in self.db.data else None
        new_data = copy.deepcopy(projected["db"])
        conflict_count = self.firebase_conflicts + len(result["conflicts"])
        new_data[cloud_merge.META_KEY] = {"endpoint": job["endpoint"], "base": committed,
                                        "conflicts": conflict_count}
        old_data, old_settings = self.db.data, copy.deepcopy(self.settings)
        callback = self.db.on_save
        try:
            for key in cloud_merge.SHARED_SETTINGS:
                if key not in projected["settings"]:
                    self.settings.pop(key, None)
            self.settings.update(projected["settings"])
            self.settings["firebase_last_sync"] = result["saved_at"]
            self.settings["firebase_pending_sync"] = projected != committed
            # Settings precede the DB/checkpoint. A crash can resend changes but
            # cannot acknowledge DB changes which were never saved.
            if self.settings != old_settings:
                legacy.save_settings(self.settings)
            self.db.data = new_data
            self.db.on_save = None
            if new_data != old_data:
                self.db.save()
        except Exception:
            self.db.data = old_data
            self.settings.clear()
            self.settings.update(old_settings)
            raise
        finally:
            self.db.on_save = callback
        self._firebase_dirty = projected != committed
        self.firebase_error = ""
        self.firebase_conflicts = conflict_count
        return legacy.ActionResult(True, "synced", data={"backup": backup, "changed": changed,
                                                       "conflicts": self.firebase_conflicts})

    def firebase_failure(self, error):
        self.firebase_error = str(error)
        self._firebase_dirty = True
        self.settings["firebase_pending_sync"] = True
        try:
            legacy.save_settings(self.settings)
        except OSError:
            # Pending DB edits and the old checkpoint are already durable;
            # persisting a cosmetic error flag must not stop automatic retry.
            pass

    def firebase_sync(self):
        try:
            job = self.firebase_job()
            if isinstance(job, legacy.ActionResult):
                return job
            return self.firebase_accept(job, job["run"]())
        except Exception as exc:
            self.firebase_failure(exc)
            return legacy.ActionResult(False, "offline", error=str(exc))

    # Compatibility callers now use the same safe merge in either direction.
    def firebase_download(self):
        return self.firebase_sync()

    def firebase_upload(self):
        return self.firebase_sync()

    def import_firebase_service_account(self, source_path):
        """يستورد ملف service-account محلياً من دون وضع مفتاحه في الإعدادات."""
        try:
            with open(source_path, encoding="utf-8") as handle:
                account = json.load(handle)
        except (OSError, ValueError):
            return legacy.ActionResult(False, "bad_credentials",
                                       error="تعذر قراءة ملف بيانات اعتماد Firebase.")
        required = ("project_id", "client_email", "private_key", "token_uri")
        if account.get("type") != "service_account" or not all(account.get(key) for key in required):
            return legacy.ActionResult(False, "bad_credentials",
                                       error="اختر ملف Firebase service account صالحاً.")
        destination = os.path.join(os.path.dirname(legacy.SETTINGS_FILE),
                                   "firebase_service_account.json")
        try:
            if os.path.abspath(source_path) != os.path.abspath(destination):
                temporary = destination + ".importing"
                shutil.copyfile(source_path, temporary)
                try:
                    os.chmod(temporary, 0o600)
                except OSError:
                    pass
                os.replace(temporary, destination)
            self.settings.update({"firebase_service_account_file": destination,
                                  "firebase_project_id": account["project_id"]})
            legacy.save_settings(self.settings)
            self.firebase = legacy.FirebaseSync(self.settings)
            self._firebase_transport = None
            self._firebase_dirty = True
            return legacy.ActionResult(True, "credentials_imported",
                                       data={"project_id": account["project_id"]})
        except OSError:
            return legacy.ActionResult(False, "credentials_import_failed",
                                       error="تعذر حفظ بيانات اعتماد Firebase محلياً.")


class ConnectDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("اتصال بالراوتر")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(430)
        form = QFormLayout(self)
        form.setContentsMargins(24, 22, 24, 22)
        form.setSpacing(12)
        self.host = QLineEdit(settings.get("host", ""))
        self.port = QLineEdit(str(settings.get("port", 22)))
        self.username = QLineEdit(settings.get("username", ""))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        form.addRow("عنوان الراوتر", self.host)
        form.addRow("المنفذ", self.port)
        form.addRow("اسم المستخدم", self.username)
        form.addRow("كلمة المرور", self.password)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("اتصال")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("إلغاء")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        # The address and user name are remembered; begin every new connection at
        # the only credential that must be typed each time.
        self.password.setFocus()


class AddDeviceDialog(QDialog):
    """حوار قصير ومحدد لعملية واحدة."""
    def __init__(self, groups, default_group, parent=None):
        super().__init__(parent)
        self.setWindowTitle("إضافة جهاز موثوق")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(460)
        form = QFormLayout(self)
        form.setContentsMargins(24, 22, 24, 22)
        form.setSpacing(12)
        self.mac = QLineEdit()
        self.mac.setPlaceholderText("00:00:5E:00:53:01")
        self.name = QLineEdit()
        self.group = QComboBox()
        self.group.addItems(groups)
        if default_group in groups:
            self.group.setCurrentText(default_group)
        self.note = QLineEdit()
        form.addRow("عنوان الماك", self.mac)
        form.addRow("الاسم الوصفي", self.name)
        form.addRow("مجموعة الصلاحيات", self.group)
        form.addRow("ملاحظة", self.note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("إضافة والتحقق")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("إلغاء")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class AddPortalDialog(QDialog):
    """إدخال حساب بوابة بعبارات واضحة من دون عرض كلمة المرور بعد الحفظ."""
    def __init__(self, groups, default_group, parent=None):
        super().__init__(parent)
        self.setWindowTitle("إضافة حساب بوابة")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(460)
        form = QFormLayout(self)
        form.setContentsMargins(24, 22, 24, 22)
        form.setSpacing(12)
        self.username = QLineEdit()
        self.username.setPlaceholderText("guest.staff")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.name = QLineEdit()
        self.group = QComboBox()
        self.group.addItems(groups)
        if default_group in groups:
            self.group.setCurrentText(default_group)
        self.note = QLineEdit()
        form.addRow("اسم الحساب", self.username)
        form.addRow("كلمة المرور", self.password)
        form.addRow("الاسم الوصفي", self.name)
        form.addRow("مجموعة الصلاحيات", self.group)
        form.addRow("ملاحظة", self.note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("إضافة والتحقق")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("إلغاء")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class ResetPortalPasswordDialog(QDialog):
    def __init__(self, username, parent=None):
        super().__init__(parent)
        self.setWindowTitle("تغيير كلمة مرور الحساب")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(440)
        form = QFormLayout(self)
        form.setContentsMargins(24, 22, 24, 22)
        form.setSpacing(12)
        account = QLineEdit(username)
        account.setReadOnly(True)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("8 محارف على الأقل")
        form.addRow("اسم الحساب", account)
        form.addRow("كلمة المرور الجديدة", self.password)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("تغيير كلمة المرور")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("إلغاء")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class RotateMacPasswordDialog(QDialog):
    """يجمع مدخلات التغيير قبل أي أمر كتابة على الراوتر."""
    def __init__(self, profiles, preferred_profile, parent=None):
        super().__init__(parent)
        self.setWindowTitle("تغيير كلمة السر وتعميمها")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(460)
        form = QFormLayout(self)
        form.setContentsMargins(24, 22, 24, 22)
        form.setSpacing(12)
        self.profile = QComboBox()
        self.profile.addItems(sorted(profiles))
        if preferred_profile in profiles:
            self.profile.setCurrentText(preferred_profile)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("8 محارف على الأقل")
        self.password_confirm = QLineEdit()
        self.password_confirm.setEchoMode(QLineEdit.Password)
        form.addRow("ملف MAC", self.profile)
        form.addRow("كلمة السر الجديدة", self.password)
        form.addRow("تأكيد كلمة السر", self.password_confirm)
        self.show_password = FullRowCheckBox("إظهار كلمة السر")
        self.show_password.toggled.connect(self._set_password_visibility)
        form.addRow(self.show_password)
        self.password_match = QLabel("اكتب كلمة السر مرتين للتحقق.", objectName="subtle")
        self.password_match.setWordWrap(True)
        form.addRow(self.password_match)
        self.password.textChanged.connect(self._update_password_match)
        self.password_confirm.textChanged.connect(self._update_password_match)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("متابعة")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("إلغاء")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _set_password_visibility(self, visible):
        mode = QLineEdit.Normal if visible else QLineEdit.Password
        self.password.setEchoMode(mode)
        self.password_confirm.setEchoMode(mode)

    def _update_password_match(self):
        password, confirmation = self.password.text(), self.password_confirm.text()
        if not password and not confirmation:
            self.password_match.setText("اكتب كلمة السر مرتين للتحقق.")
            self.password_match.setStyleSheet("")
        elif password == confirmation:
            self.password_match.setText("كلمتا السر متطابقتان.")
            self.password_match.setStyleSheet("color: #067647; font-weight: 700;")
        else:
            self.password_match.setText("كلمتا السر غير متطابقتين.")
            self.password_match.setStyleSheet("color: #B42318; font-weight: 700;")


class EditDeviceDialog(QDialog):
    def __init__(self, name, note, parent=None):
        super().__init__(parent)
        self.setWindowTitle("تعديل الاسم والملاحظة")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(440)
        form = QFormLayout(self)
        form.setContentsMargins(24, 22, 24, 22)
        form.setSpacing(12)
        self.name = QLineEdit(name)
        self.note = QLineEdit(note)
        form.addRow("الاسم الوصفي", self.name)
        form.addRow("ملاحظة", self.note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("حفظ التعديل")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("إلغاء")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class NameVlanDeviceDialog(QDialog):
    """حوار قصير يثبت هوية الجهاز قبل حفظ اسمه المحلي."""
    def __init__(self, mac, name, note, parent=None):
        super().__init__(parent)
        self.setWindowTitle("تسمية جهاز على الشبكة")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(450)
        form = QFormLayout(self)
        form.setContentsMargins(24, 22, 24, 22)
        form.setSpacing(12)
        address = QLineEdit(legacy.mac_pretty(legacy.normalize_mac(mac)))
        address.setReadOnly(True)
        self.name = QLineEdit(name)
        self.name.setPlaceholderText("مثال: طابعة الاستقبال")
        self.note = QLineEdit(note)
        form.addRow("عنوان الماك", address)
        form.addRow("الاسم الوصفي", self.name)
        form.addRow("ملاحظة", self.note)
        notice = QLabel("يُحفظ الاسم محلياً فقط، ولا يمنح الجهاز أي صلاحية أو ثقة على الراوتر.")
        notice.setWordWrap(True)
        form.addRow(notice)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("حفظ الاسم")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("إلغاء")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class ChangeDeviceGroupDialog(QDialog):
    """حوار مخصص يوضح أثر تغيير المجموعة قبل قطع الجلسة."""
    def __init__(self, mac, groups, current_group, parent=None):
        super().__init__(parent)
        self.setWindowTitle("تغيير مجموعة الجهاز")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(470)
        form = QFormLayout(self)
        form.setContentsMargins(24, 22, 24, 22)
        form.setSpacing(12)
        address = QLineEdit(legacy.mac_pretty(legacy.normalize_mac(mac)))
        address.setReadOnly(True)
        self.group = QComboBox()
        self.group.addItems(groups)
        if current_group in groups:
            self.group.setCurrentText(current_group)
        notice = QLabel("سيُفصل الجهاز من جلسته الحالية ثم يعيد المصادقة بمجموعة الصلاحيات الجديدة.")
        notice.setWordWrap(True)
        form.addRow("عنوان الماك", address)
        form.addRow("مجموعة الصلاحيات الجديدة", self.group)
        form.addRow(notice)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("تغيير المجموعة وفصل الجلسة")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("إلغاء")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class ChangePortalGroupDialog(QDialog):
    """حوار صريح يربط تغيير الصلاحية بفصل جلسة البوابة القائمة."""
    def __init__(self, username, groups, current_group, parent=None):
        super().__init__(parent)
        self.setWindowTitle("تغيير مجموعة الحساب")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(470)
        form = QFormLayout(self)
        form.setContentsMargins(24, 22, 24, 22)
        form.setSpacing(12)
        account = QLineEdit(username)
        account.setReadOnly(True)
        self.group = QComboBox()
        self.group.addItems(groups)
        if current_group in groups:
            self.group.setCurrentText(current_group)
        notice = QLabel("سيُفصل الحساب من جلسته الحالية لتطبيق مجموعة الصلاحيات الجديدة.")
        notice.setWordWrap(True)
        form.addRow("اسم الحساب", account)
        form.addRow("مجموعة الصلاحيات الجديدة", self.group)
        form.addRow(notice)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("تغيير المجموعة وفصل الجلسة")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("إلغاء")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class RevokePortalDialog(QDialog):
    """تأكيد يذكر أثر حذف حساب البوابة وسجل الإلغاء المحلي."""
    def __init__(self, username, parent=None):
        super().__init__(parent)
        self.setWindowTitle("حذف حساب البوابة")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(470)
        form = QFormLayout(self)
        form.setContentsMargins(24, 22, 24, 22)
        form.setSpacing(12)
        account = QLineEdit(username)
        account.setReadOnly(True)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("مثال: انتهت صلاحية الحساب")
        notice = QLabel("سيُحذف الحساب من الراوتر وتُقطع جلسته الحالية. سيبقى سجل الإلغاء محلياً.")
        notice.setWordWrap(True)
        form.addRow("اسم الحساب", account)
        form.addRow("سبب الحذف (اختياري)", self.reason)
        form.addRow(notice)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.Cancel)
        confirm = buttons.button(QDialogButtonBox.StandardButton.Yes)
        confirm.setText("حذف الحساب الآن")
        confirm.setObjectName("danger")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("إلغاء")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class ExcludeDhcpRangeDialog(QDialog):
    """An exclusion is a pool policy; the optional cut is deliberately opt-in."""
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.setWindowTitle("استثناء نطاق من DHCP")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(500)
        form = QFormLayout(self)
        form.setContentsMargins(24, 22, 24, 22)
        form.setSpacing(12)
        net = (state or {}).get("net") or {}
        self.start, self.end = QLineEdit(), QLineEdit()
        placeholder = ("%s to %s" if ACTIVE_LANGUAGE == "en" else "%s إلى %s") % (
            net.get("ip", tr("عنوان البداية")), tr("عنوان النهاية"))
        self.start.setPlaceholderText(placeholder)
        self.end.setPlaceholderText("عنوان النهاية")
        form.addRow("أول عنوان", self.start)
        form.addRow("آخر عنوان", self.end)
        self.disconnect = FullRowCheckBox("فصل جلسات DHCP المطابقة بعد الاستثناء")
        self.disconnect.setChecked(False)
        self.disconnect.setEnabled(bool((state or {}).get("nac")))
        form.addRow(self.disconnect)
        note = QLabel(
            "لن يُوزع DHCP هذا النطاق بعد الحفظ. فصل الجلسات اختياري ويقتصر على الأجهزة "
            "التي يطابق MAC الخاص بها إيجار DHCP؛ لا تُفصل الأجهزة ذات العنوان الثابت اليدوي.")
        note.setWordWrap(True)
        form.addRow(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("استثناء والتحقق")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("إلغاء")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class DhcpBindingDialog(QDialog):
    """One simple reservation: DHCP only, never the management ARP/ACL bundle."""
    def __init__(self, mac, state, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ربط IP ثابت بـ MAC")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(500)
        form = QFormLayout(self)
        form.setContentsMargins(24, 22, 24, 22)
        form.setSpacing(12)
        address = QLineEdit(legacy.mac_pretty(legacy.normalize_mac(mac)))
        address.setReadOnly(True)
        self.ip, self.description = QLineEdit(), QLineEdit()
        net = (state or {}).get("net") or {}
        self.ip.setPlaceholderText(("Example: %s" if ACTIVE_LANGUAGE == "en" else "مثال: %s") %
                                   net.get("ip", "10.0.20.50"))
        self.description.setPlaceholderText("اختياري، أحرف إنجليزية وأرقام")
        form.addRow("عنوان الماك", address)
        form.addRow("عنوان IP المطلوب", self.ip)
        form.addRow("وصف الراوتر", self.description)
        self.disconnect = FullRowCheckBox("فصل الجلسة بعد الربط لتجديد العنوان")
        self.disconnect.setChecked(False)
        self.disconnect.setEnabled(bool((state or {}).get("nac")))
        form.addRow(self.disconnect)
        note = QLabel(
            "الربط يحجز عنوان DHCP لهذا MAC فقط. لا يضيف ARP ثابتاً أو صلاحية إدارة، "
            "ولا يمكن اختيار عنوان مستثنى من مجمّع DHCP.")
        note.setWordWrap(True)
        form.addRow(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("ربط والتحقق")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("إلغاء")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class DisconnectOnlineDialog(QDialog):
    """تأكيد قصير يحدد الجلسة التي ستفصل، لا الحساب الدائم."""
    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.setWindowTitle("فصل متصل")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(470)
        form = QFormLayout(self)
        form.setContentsMargins(24, 22, 24, 22)
        form.setSpacing(12)
        for label, value in (("اسم الحساب", session["user"]),
                             ("عنوان IP", session["ip"]),
                             ("عنوان الماك", session["mac"])):
            field = QLineEdit(value)
            field.setReadOnly(True)
            form.addRow(label, field)
        notice = QLabel("سيُفصل هذا الاتصال الآن. لا يُحذف الحساب أو سجل الجهاز.")
        notice.setWordWrap(True)
        form.addRow(notice)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.Cancel)
        confirm = buttons.button(QDialogButtonBox.StandardButton.Yes)
        confirm.setText("فصل المتصل الآن")
        confirm.setObjectName("danger")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("إلغاء")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class TrustOnlineDialog(QDialog):
    """إضافة جهاز موثوق من جلسة مقروءة؛ الهوية الشبكية لا تُكتب يدوياً."""
    def __init__(self, session, groups, default_group, local, parent=None):
        super().__init__(parent)
        self.setWindowTitle("إضافة المتصل إلى الأجهزة الموثوقة")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(470)
        form = QFormLayout(self)
        form.setContentsMargins(24, 22, 24, 22)
        form.setSpacing(12)
        for label, value in (("عنوان الماك", session["mac"]),
                             ("عنوان IP", session["ip"]),
                             ("الحساب الحالي", session["user"])):
            field = QLineEdit(value)
            field.setReadOnly(True)
            form.addRow(label, field)
        self.name = QLineEdit(local.get("name", ""))
        self.group = QComboBox()
        self.group.addItems(groups)
        selected_group = local.get("group") or default_group
        if selected_group in groups:
            self.group.setCurrentText(selected_group)
        self.note = QLineEdit(local.get("note", ""))
        form.addRow("الاسم الوصفي", self.name)
        form.addRow("مجموعة الصلاحيات", self.group)
        form.addRow("ملاحظة", self.note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("إضافة والتحقق")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("إلغاء")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class RevokeDeviceDialog(QDialog):
    """تأكيد واضح لعملية لا يمكن التراجع عنها من الواجهة."""
    def __init__(self, mac, parent=None):
        super().__init__(parent)
        self.setWindowTitle("سحب الثقة من جهاز")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(470)
        form = QFormLayout(self)
        form.setContentsMargins(24, 22, 24, 22)
        form.setSpacing(12)
        address = QLineEdit(legacy.mac_pretty(legacy.normalize_mac(mac)))
        address.setReadOnly(True)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("مثال: انتهى عقد الجهاز")
        notice = QLabel("سيُحذف حساب MAC من الراوتر وتُقطع جلسته الحالية. سيبقى سجل الجهاز محليًا كمُلغى.")
        notice.setWordWrap(True)
        form.addRow("عنوان الماك", address)
        form.addRow("سبب السحب (اختياري)", self.reason)
        form.addRow(notice)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Yes).setText("سحب الثقة الآن")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("إلغاء")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class AddStaticNatDialog(QDialog):
    """حوار صغير يقابل صيغة NAT الثابتة المتحقق منها على AR730."""
    def __init__(self, interfaces, parent=None, rule=None):
        super().__init__(parent)
        editing = rule is not None
        self.setWindowTitle("تعديل تحويل المنفذ" if editing else "أضف قاعدة تحويل المنفذ")
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(490)
        form = QFormLayout(self)
        form.setContentsMargins(24, 22, 24, 22)
        form.setSpacing(12)
        self.interface = QComboBox()
        for item in interfaces:
            label = "%s — %s/%s" % (item["iface"], item.get("ip") or "—", item.get("len") or "—")
            self.interface.addItem(label, item["iface"])
        self.protocol = QLineEdit("TCP")
        self.protocol.setReadOnly(True)
        self.external_port = QLineEdit()
        self.external_port.setPlaceholderText("مثال: 65010")
        self.inside_ip = QLineEdit()
        self.inside_ip.setPlaceholderText("مثال: 10.0.20.210")
        self.inside_port = QLineEdit()
        self.inside_port.setPlaceholderText("مثال: 4370")
        if rule:
            selected = self.interface.findData(rule.get("interface"))
            if selected >= 0:
                self.interface.setCurrentIndex(selected)
            self.external_port.setText(str(rule.get("external_port") or ""))
            self.inside_ip.setText(rule.get("inside_ip") or "")
            self.inside_port.setText(str(rule.get("inside_port") or ""))
        form.addRow("واجهة الإنترنت", self.interface)
        form.addRow("البروتوكول", self.protocol)
        form.addRow("المنفذ الخارجي", self.external_port)
        form.addRow("عنوان الجهاز", self.inside_ip)
        form.addRow("المنفذ الداخلي", self.inside_port)
        notice = QLabel("سيستبدل التطبيق القاعدة بعد التحقق، ويعيد القديمة تلقائياً إن تعذر إنشاء البديل." if editing else
                        "سيضيف التطبيق: TCP من منفذ WAN الخارجي إلى منفذ الجهاز الداخلي. لا تضع جهازاً داخلياً في شبكة WAN نفسها.")
        notice.setWordWrap(True)
        form.addRow(notice)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("حفظ والتحقق" if editing else "إضافة والتحقق")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("إلغاء")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class MainWindow(QMainWindow):
    def __init__(self, controller, demo=False):
        super().__init__()
        self.c, self.demo, self.workers = controller, demo, []
        self._busy = False
        self._busy_widgets = []
        self._closing = False
        self._cloud_worker = None
        self._cloud_reply = None
        self._next_cloud_poll = 0
        self._cloud_failures = 0
        self.lang = self.c.settings.get("qt_ui_lang", "en")
        if self.lang not in {"ar", "en"}:
            self.lang = "en"
        self._activate_language(self.lang, persist=False)
        self.wan_timer = QTimer(self)
        self.wan_timer.timeout.connect(lambda: self._check_wan(False) if self.c.router.connected else self.wan_timer.stop())
        self.tables = {}
        self.connect_dialog = None
        self.logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "afz-logo.svg")
        self.setWindowIcon(QIcon(self.logo_path))
        self.setWindowTitle(tr("AR730 Access Manager"))
        self.setMinimumSize(1050, 650)
        self.resize(1280, 790)
        self.setLayoutDirection(current_direction())
        self._build()
        self._render()
        if self.c.settings.get("wan_auto"):
            self.wan_timer.start(60000)
        # Check asynchronously after the window is usable; offline operation
        # remains fully supported and intentionally produces no warning.
        QTimer.singleShot(1500, self._start_update_check)
        self.firebase_timer = QTimer(self)
        self.firebase_timer.timeout.connect(self._auto_firebase_sync)
        self.firebase_timer.start(1000)
        QTimer.singleShot(0, self._auto_firebase_sync)

    def _auto_firebase_sync(self):
        if self._closing or self.demo or self._busy or self._cloud_worker:
            return
        if any(worker.isRunning() for worker in self.workers):
            return
        if self._cloud_reply is not None:
            job, result, error = self._cloud_reply
            self._cloud_reply = None
            try:
                if error:
                    raise RuntimeError(error)
                accepted = self.c.firebase_accept(job, result)
                if accepted.ok and accepted.data["changed"] and self.c.router.connected:
                    # Cloud metadata alone cannot certify a router account's
                    # current state. Read the router again before painting it.
                    self._run(self.c.refresh)
                self._cloud_failures = 0
            except Exception as exc:
                self.c.firebase_failure(exc)
                self._cloud_failures += 1
                self._next_cloud_poll = time.monotonic() + min(60, 5 * 2 ** min(self._cloud_failures, 4))
            self._render()
            return
        if time.monotonic() < self._next_cloud_poll:
            return
        if self.c.settings.get("storage_mode") != "firebase":
            return
        try:
            job = self.c.firebase_job()
            if isinstance(job, legacy.ActionResult):
                self.c.firebase_error = job.error or "Firebase credentials are incomplete."
                self._next_cloud_poll = time.monotonic() + 30
                self._render_firebase_status()
                return
        except Exception as exc:
            self.c.firebase_failure(exc)
            self._next_cloud_poll = time.monotonic() + 30
            self._render_firebase_status()
            return
        worker = Worker(job["run"])
        self._cloud_worker = worker
        self.workers.append(worker)
        worker.done.connect(lambda result: self._queue_cloud_reply(worker, job, result, None))
        worker.failed.connect(lambda error: self._queue_cloud_reply(worker, job, None, error))
        self._next_cloud_poll = time.monotonic() + 5
        self._render_firebase_status()
        worker.start()

    def _queue_cloud_reply(self, worker, job, result, error):
        self._cloud_reply = (job, result, error)
        # QThread.done can arrive before run() has returned. Keep the thread
        # referenced until Qt's finished signal confirms it can be destroyed.
        worker.finished.connect(lambda: self._release_cloud_worker(worker))
        if worker.isFinished():
            self._release_cloud_worker(worker)

    def _release_cloud_worker(self, worker):
        if self._cloud_worker is not worker:
            return
        if worker in self.workers:
            self.workers.remove(worker)
        self._cloud_worker = None
        self._auto_firebase_sync()

    def _render_firebase_status(self):
        if not hasattr(self, "cloud_status"):
            return
        if self.c.settings.get("storage_mode") != "firebase":
            text = "تخزين محلي"
        elif self._cloud_worker:
            text = "جارٍ مزامنة البيانات…"
        elif self.c.firebase_error:
            text = "المزامنة معلّقة؛ البيانات محفوظة محلياً"
        elif self.c.firebase_conflicts:
            text = "تمت المزامنة؛ حُفظت نسخ التعارض للاسترجاع"
        elif self.c._firebase_dirty:
            text = "تغييرات محفوظة؛ بانتظار المزامنة"
        else:
            text = "البيانات متزامنة"
        self.cloud_status.setText(tr(text))
        self.cloud_status.setToolTip(self.c.firebase_error or self.c.settings.get("firebase_last_sync", ""))

    def _start_update_check(self):
        if self._closing or self.demo:
            return
        worker = Worker(lambda: legacy.check_for_update(legacy.APP_VERSION))
        self.workers.append(worker)
        worker.done.connect(lambda update: self._finish_update_check(worker, update))
        worker.failed.connect(lambda unused: self._finish_update_check(worker, None))
        worker.start()

    def _finish_update_check(self, worker, update):
        if worker in self.workers:
            self.workers.remove(worker)
        if not update:
            return
        if self.lang == "ar":
            text = ("يتوفر إصدار جديد: %s\nالإصدار المثبت: %s\n\n"
                    "سيُنزل التطبيق التحديث المناسب ويتحقق من SHA-256 ثم يثبّته "
                    "ويعيد تشغيل نفسه. بياناتك المحلية تبقى خارج مجلد التطبيق."
                    % (update["version"], legacy.APP_VERSION))
            prompt = "هل تريد تثبيت التحديث الآن؟"
        else:
            text = ("Version %s is available (installed: %s).\n\n"
                    "The app will download the correct update, verify SHA-256, install it, "
                    "and restart. Local data stays outside the app folder."
                    % (update["version"], legacy.APP_VERSION))
            prompt = "Install the update now?"
        answer = QMessageBox.question(self, "AR730 Manager update", text + "\n\n" + prompt,
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer == QMessageBox.Yes:
            ok, error = legacy.launch_update(update)
            if not ok:
                if self.lang == "ar":
                    QMessageBox.warning(self, "تحديث التطبيق", "تعذر بدء التحديث التلقائي:\n" + error)
                else:
                    QMessageBox.warning(self, "Application update", "Could not start the automatic update:\n" + error)
                return
            QTimer.singleShot(50, self.close)

    def _build(self):
        self.surface = localized_surface(self.lang)
        root = QWidget(objectName="canvas")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        sidebar = QFrame(objectName="sidebar")
        sidebar.setFixedWidth(245)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 24, 14, 18)
        side.setSpacing(5)
        side.addWidget(QLabel("AR730", objectName="brand"))
        side.addWidget(QLabel("مدير الوصول والشبكة", objectName="sideSub"))
        version_label = QLabel("v" + legacy.APP_VERSION, objectName="sideVersion")
        version_label.setAlignment(Qt.AlignRight if self.lang == "ar" else Qt.AlignLeft)
        side.addWidget(version_label)
        side.addSpacing(22)
        self.nav = []
        labels = [tr("نظرة عامة")] + [item["title"] for item in self.surface.values()] + [tr("الدليل والدعم")]
        for index, label in enumerate(labels):
            button = QPushButton(label, objectName="nav")
            # Qt style sheets do not infer text alignment from layout direction.
            # Keep English labels anchored to the left and Arabic labels to the
            # right, rather than applying the Arabic alignment to both.
            button.setProperty("rtl", self.lang == "ar")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, i=index: self.stack.setCurrentIndex(i))
            button.clicked.connect(lambda checked=False, i=index: self._select_nav(i))
            side.addWidget(button)
            self.nav.append(button)
        # Keep page indices stable while placing Settings immediately above Support.
        settings_button = self.nav[1 + list(self.surface).index("settings")]
        side.removeWidget(settings_button)
        side.insertWidget(side.indexOf(self.nav[-1]), settings_button)
        side.addStretch()
        side.addSpacing(12)
        afz_logo = QLabel(objectName="afzLogo")
        # The AFZ mark is wide rather than square.  Scale once by width so its
        # original 3900:2864 proportion is always preserved.
        logo_pixmap = QPixmap(self.logo_path).scaledToWidth(70, Qt.SmoothTransformation)
        afz_logo.setPixmap(logo_pixmap)
        afz_logo.setFixedSize(logo_pixmap.size())
        afz_logo.setAlignment(Qt.AlignCenter)
        afz_logo.setToolTip("AFZ Systems")
        side.addWidget(afz_logo, alignment=Qt.AlignCenter)
        credit = QLabel("AFZ Systems", objectName="afzCredit")
        credit.setFixedWidth(logo_pixmap.width())
        credit_font = credit.font()
        # Keep the attribution quieter than the mark itself.  It is a label,
        # not a second logo; avoid stretching it across the whole sidebar.
        credit_font.setPixelSize(9)
        credit_font.setBold(True)
        credit.setFont(credit_font)
        credit.setAlignment(Qt.AlignCenter)
        # Font metrics vary slightly between macOS, Windows and Linux. Keep
        # the attribution readable rather than clipping it to the logo width.
        credit.setFixedWidth(max(logo_pixmap.width(),
                                 QFontMetrics(credit_font).horizontalAdvance(credit.text()) + 2))
        side.addWidget(credit, alignment=Qt.AlignCenter)
        self.connection = QLabel("● غير متصل", objectName="connectionStatus")
        connection_font = self.connection.font()
        connection_font.setPixelSize(11)
        self.connection.setFont(connection_font)
        self.connection.setAlignment(Qt.AlignCenter)
        side.addWidget(self.connection)
        self.cloud_status = QLabel(objectName="subtle")
        self.cloud_status.setWordWrap(True)
        self.cloud_status.setAlignment(Qt.AlignCenter)
        side.addWidget(self.cloud_status)
        outer.addWidget(sidebar)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 18, 24, 12)
        layout.setSpacing(16)
        top = QFrame(objectName="topbar")
        top_layout = QHBoxLayout(top)
        self.router_label = QLabel("● غير متصل", objectName="routerStatus")
        self.operation_status = QLabel("جاهز", objectName="operationStatus")
        self.operation_status.setProperty("state", "ok")
        self.connect_button = QPushButton("اتصال", objectName="primary")
        self.connect_button.clicked.connect(self._connect)
        refresh = QPushButton("تحديث")
        refresh.clicked.connect(self._refresh)
        top_layout.addWidget(self.router_label)
        top_layout.addWidget(self.operation_status)
        top_layout.addStretch()
        self.language_toggle = QPushButton("🌐 AR" if self.lang == "en" else "🌐 EN")
        self.language_toggle.setToolTip("Switch to Arabic" if self.lang == "en" else "التبديل إلى الإنجليزية")
        self.language_toggle.setAccessibleName("Language switcher")
        self.language_toggle.clicked.connect(self._toggle_language)
        top_layout.addWidget(self.language_toggle)
        top_layout.addWidget(refresh)
        top_layout.addWidget(self.connect_button)
        layout.addWidget(top)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)
        outer.addWidget(content, 1)

        self.stack.addWidget(self._overview())
        for page_id, item in self.surface.items():
            self.stack.addWidget(self._page(page_id, item))
        self.stack.addWidget(self._guide())
        self._select_nav(0)

        # طبقة واحدة فوق كامل النافذة تمنع النقرات المتزامنة على الراوتر،
        # بينما يبقى شريط التقدم غير المحدد متحركاً إلى أن تنتهي العملية.
        self.busy_overlay = QFrame(root, objectName="busyOverlay")
        overlay_layout = QVBoxLayout(self.busy_overlay)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        overlay_layout.addStretch()
        busy_panel = QFrame(objectName="busyPanel")
        busy_panel.setFixedWidth(330)
        panel_layout = QVBoxLayout(busy_panel)
        panel_layout.setContentsMargins(22, 20, 22, 20)
        self.busy_title = QLabel("جارٍ تنفيذ العملية…", objectName="busyTitle")
        self.busy_title.setAlignment(Qt.AlignCenter)
        self.busy_hint = QLabel("انتظر حتى ينتهي التواصل مع الراوتر.", objectName="busyHint")
        self.busy_hint.setAlignment(Qt.AlignCenter)
        self.busy_hint.setWordWrap(True)
        self.busy_spinner = QProgressBar(objectName="busySpinner")
        self.busy_spinner.setRange(0, 0)
        self.busy_spinner.setTextVisible(False)
        panel_layout.addWidget(self.busy_title)
        panel_layout.addSpacing(4)
        panel_layout.addWidget(self.busy_hint)
        panel_layout.addSpacing(13)
        panel_layout.addWidget(self.busy_spinner)
        overlay_layout.addWidget(busy_panel, alignment=Qt.AlignHCenter)
        overlay_layout.addStretch()
        self.busy_overlay.hide()

    def _activate_language(self, language, persist=True):
        global ACTIVE_LANGUAGE
        self.lang = language
        ACTIVE_LANGUAGE = language
        if persist:
            self.c.settings["qt_ui_lang"] = language
            legacy.save_settings(self.c.settings)

    def _toggle_language(self):
        page_index = self.stack.currentIndex() if hasattr(self, "stack") else 0
        self._activate_language("ar" if self.lang == "en" else "en")
        self.setWindowTitle(tr("AR730 Access Manager"))
        self.setLayoutDirection(current_direction())
        old = self.centralWidget()
        self.tables = {}
        self._build()
        self.stack.setCurrentIndex(page_index)
        self._select_nav(page_index)
        if old is not None:
            old.deleteLater()
        self._render()

    def _head(self, title, hint):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(QLabel(title, objectName="title"))
        layout.addWidget(QLabel(hint, objectName="subtle"))
        return page, layout

    def _overview(self):
        page, layout = self._head("نظرة عامة", "ملخص حالة الوصول وإدارة الراوتر الحالية.")
        row = QHBoxLayout()
        self.metrics = []
        for title in ("أجهزة موثوقة", "حسابات بوابة", "متصلون الآن", "مجموعات صلاحيات"):
            card = QFrame(objectName="metric")
            card_layout = QVBoxLayout(card)
            value = QLabel("—", objectName="title")
            card_layout.addWidget(value)
            card_layout.addWidget(QLabel(title, objectName="subtle"))
            row.addWidget(card)
            self.metrics.append(value)
        layout.addLayout(row)
        panel = QFrame(objectName="panel")
        p = QVBoxLayout(panel)
        p.addWidget(QLabel("إدارة موحّدة", objectName="title"))
        p.addWidget(QLabel("تُعرض البيانات الحية وتُنفّذ الإجراءات من هذه الواجهة، مع إعادة القراءة للتحقق من نتيجة التغيير.", objectName="subtle"))
        p.addStretch()
        layout.addWidget(panel, 1)
        return page

    def _permission_groups_page(self):
        """A policy reader that makes the three AR730 access layers explicit."""
        page, layout = self._head(
            "مجموعات الصلاحيات",
            "راجع المجموعة وACL وسياسة التطبيقات المرتبطة بالواجهة قبل أن تغيّر أي قاعدة.")

        controls = QFrame(objectName="panel")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(18, 14, 18, 14)
        controls_layout.addWidget(QLabel("مجموعة الصلاحيات"))
        self.application_group = QComboBox()
        self.application_group.setMinimumWidth(180)
        self.application_group.currentIndexChanged.connect(self._render_permission_groups)
        controls_layout.addWidget(self.application_group)
        controls_layout.addSpacing(14)
        controls_layout.addWidget(QLabel("واجهة تطبيق السياسة"))
        self.application_interface = QComboBox()
        self.application_interface.setMinimumWidth(190)
        self.application_interface.setToolTip(
            "هذه واجهة شبكة مستقلة؛ لا ينشئ الراوتر ربطاً رسمياً بينها وبين مجموعة AAA.")
        self.application_interface.currentIndexChanged.connect(self._render_permission_groups)
        controls_layout.addWidget(self.application_interface)
        self.refresh_groups = QPushButton("تحديث", objectName="primary")
        self.refresh_groups.clicked.connect(self._refresh)
        controls_layout.addWidget(self.refresh_groups)
        controls_layout.addStretch()
        layout.addWidget(controls)

        self.application_context = QLabel(objectName="subtle")
        self.application_context.setWordWrap(True)
        layout.addWidget(self.application_context)

        app_panel = QFrame(objectName="panel")
        app_layout = QVBoxLayout(app_panel)
        app_layout.setContentsMargins(18, 16, 18, 16)
        top = QHBoxLayout()
        top.addWidget(QLabel("التطبيقات والتواقيع", objectName="title"))
        top.addStretch()
        self.application_search = QLineEdit()
        self.application_search.setPlaceholderText("ابحث عن تطبيق أو توقيع…")
        self.application_search.setMinimumWidth(250)
        top.addWidget(self.application_search)
        app_layout.addLayout(top)
        self.application_table = QTableWidget(0, 4)
        self.application_table.setHorizontalHeaderLabels((
            "التطبيق / التوقيع", "الفئة", "الحالة الفعلية", "مصدر القرار"))
        self.application_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.application_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.application_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.application_table.setItemDelegate(NoFocusCellDelegate(self.application_table))
        self.application_table.verticalHeader().hide()
        self.application_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.application_table.setToolTip(
            "يعرض التطبيق ما يقرأه من الراوتر؛ لا تُرسل التغييرات إلا بعد التأكيد.")
        self.application_search.textChanged.connect(
            lambda text: self._filter(self.application_table, text))
        self.application_table.itemSelectionChanged.connect(self._describe_selected_application)
        app_layout.addWidget(self.application_table, 1)
        app_actions = QHBoxLayout()
        self.block_application = QPushButton("حظر المحدد", objectName="danger")
        self.block_application.clicked.connect(self._block_selected_application)
        self.allow_application = QPushButton("السماح للمحدد", objectName="primary")
        self.allow_application.clicked.connect(self._allow_selected_application)
        self.review_application = QPushButton("شرح المحدد")
        self.review_application.clicked.connect(self._describe_selected_application)
        self.copy_application_review = QPushButton("نسخ تقرير السياسة")
        self.copy_application_review.clicked.connect(self._copy_application_review)
        app_actions.addWidget(self.block_application)
        app_actions.addWidget(self.allow_application)
        app_actions.addWidget(self.review_application)
        app_actions.addWidget(self.copy_application_review)
        app_actions.addStretch()
        app_layout.addLayout(app_actions)
        layout.addWidget(app_panel, 1)

        self.application_explanation = QLabel(objectName="subtle")
        self.application_explanation.setWordWrap(True)
        layout.addWidget(self.application_explanation)
        # Keep the established table registry stable for shortcuts and the
        # regression harness; this page's table is the group-policy table.
        self.tables["groups"] = self.application_table
        QShortcut(QKeySequence.Copy, self.application_table,
                  activated=lambda: self._copy_table_selection(self.application_table))
        return page

    def _guide(self):
        """دليل عملي قصير؛ يبدأ به المستخدم قبل إجراء أي تغيير على الراوتر."""
        page, layout = self._head("الدليل والدعم", "دليل تشغيل مختصر يوضح مسار العمل الآمن وقنوات الدعم.")
        guide = QFrame(objectName="panel")
        body = QVBoxLayout(guide)
        body.setContentsMargins(24, 22, 24, 22)
        title = QLabel("إدارة الوصول بثقة، لا بتخمين", objectName="title")
        body.addWidget(title)
        intro = QLabel("يحوّل التطبيق إجراءات Huawei AR730 المتكررة إلى خطوات واضحة: "
                       "يراجع البيانات، ينفّذ التغيير، ثم يعيد القراءة للتأكد من ثبوته.")
        intro.setWordWrap(True)
        body.addWidget(intro)
        steps = (
            ("1. ابدأ بوضع التجربة", "تدرّب على الأزرار ونتائجها بلا أي اتصال بالشبكة."),
            ("2. اتصل ثم حدّث", "تحقق من حالة الاتصال بالأعلى، ثم حدّث الجداول قبل اتخاذ قرار."),
            ("3. اختر طريقة الوصول", "الأجهزة الثابتة للطابعات والحواسيب؛ وحسابات البوابة للهواتف والضيوف."),
            ("4. راجع الأثر قبل التأكيد", "التغييرات الحساسة تعرض ما سيتغير. تغيير المجموعة يفصل الجلسة لتطبيق الصلاحيات الجديدة."),
            ("5. راقب النتيجة", "تظهر حالة التنفيذ في أعلى النافذة. انسخ صفوف الجداول بـ Ctrl+C وراجع سجل الأوامر عند الحاجة."),
        )
        for heading, description in steps:
            line = QLabel("<b>%s</b><br><span style='color:#667085'>%s</span>" %
                          (tr(heading), tr(description)))
            line.setWordWrap(True)
            line.setContentsMargins(0, 5, 0, 5)
            body.addWidget(line)
        layout.addWidget(guide)

        install = QFrame(objectName="panel")
        install_layout = QVBoxLayout(install)
        install_layout.setContentsMargins(24, 18, 24, 18)
        install_layout.addWidget(QLabel(tr("التثبيت والتحديث"), objectName="title"))
        install_text = QLabel(
            tr("للتثبيت الأول أو التحديث على Windows، افتح PowerShell ونفّذ:") +
            "<br><code>irm https://raw.githubusercontent.com/AFZ92/huawei-ar730-router-easy-manager/main/scripts/install.ps1 | iex</code><br><br>" +
            tr("وعلى macOS، افتح Terminal ونفّذ:") +
            "<br><code>curl -fsSL https://raw.githubusercontent.com/AFZ92/huawei-ar730-router-easy-manager/main/scripts/install.sh | bash</code><br><br>" +
            tr("الإصدار المثبّت: ") + legacy.APP_VERSION + "<br>" +
            tr("يتحقق المثبّت من SHA-256، ولا يمسّ بياناتك المحلية عند التحديث."))
        install_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        install_text.setWordWrap(True)
        install_layout.addWidget(install_text)
        layout.addWidget(install)

        support = QFrame(objectName="panel")
        support_layout = QVBoxLayout(support)
        support_layout.setContentsMargins(24, 18, 24, 18)
        support_layout.addWidget(QLabel("AFZ Systems", objectName="title"))
        links = QLabel(
            tr("تطوير ودعم حلول إدارة الشبكات والوصول.") + "<br>" +
            tr("البريد:") + " <a href='mailto:amjadzarour@gmail.com'>amjadzarour@gmail.com</a><br>"
            "GitHub: <a href='https://github.com/AFZ92/huawei-ar730-router-easy-manager'>"
            "AFZ92/huawei-ar730-router-easy-manager</a>")
        links.setOpenExternalLinks(True)
        links.setWordWrap(True)
        support_layout.addWidget(links)
        layout.addWidget(support)
        layout.addStretch()
        return page

    def _page(self, page_id, item):
        page, layout = self._head(item["title"], "إدارة مباشرة للبيانات والإجراءات المرتبطة بالراوتر.")
        if page_id in {"devices", "portal", "online", "vlans", "management", "wan", "nat"}:
            if page_id == "devices":
                actions = QHBoxLayout()
                add = QPushButton("إضافة جهاز", objectName="primary")
                add.clicked.connect(self._add_device)
                self.edit_device = QPushButton("تعديل الاسم والملاحظة")
                self.edit_device.clicked.connect(self._edit_device_metadata)
                self.change_device_group = QPushButton("تغيير المجموعة")
                self.change_device_group.clicked.connect(self._change_device_group)
                self.revoke_device = QPushButton("سحب الثقة")
                self.revoke_device.clicked.connect(self._revoke_device)
                export = QPushButton("تصدير CSV")
                export.clicked.connect(self._export_devices)
                self.refresh_devices = QPushButton("تحديث")
                self.refresh_devices.clicked.connect(self._refresh)
                actions.addWidget(add)
                actions.addWidget(self.edit_device)
                actions.addWidget(self.change_device_group)
                actions.addWidget(self.revoke_device)
                actions.addWidget(export)
                actions.addWidget(self.refresh_devices)
                actions.addStretch()
                layout.addLayout(actions)
            elif page_id == "portal":
                actions = QHBoxLayout()
                self.add_portal = QPushButton("إضافة حساب", objectName="primary")
                self.add_portal.clicked.connect(self._add_portal)
                self.reset_portal_password = QPushButton("تغيير كلمة المرور")
                self.reset_portal_password.clicked.connect(self._reset_portal_password)
                self.change_portal_group = QPushButton("تغيير المجموعة")
                self.change_portal_group.clicked.connect(self._change_portal_group)
                self.edit_portal = QPushButton("تعديل الاسم والملاحظة")
                self.edit_portal.clicked.connect(self._edit_portal_metadata)
                self.revoke_portal = QPushButton("حذف الحساب", objectName="danger")
                self.revoke_portal.clicked.connect(self._revoke_portal)
                self.export_portal = QPushButton("تصدير CSV")
                self.export_portal.clicked.connect(self._export_portal)
                self.refresh_portal = QPushButton("تحديث")
                self.refresh_portal.clicked.connect(self._refresh)
                actions.addWidget(self.add_portal)
                actions.addWidget(self.reset_portal_password)
                actions.addWidget(self.change_portal_group)
                actions.addWidget(self.edit_portal)
                actions.addWidget(self.revoke_portal)
                actions.addWidget(self.export_portal)
                actions.addWidget(self.refresh_portal)
                actions.addStretch()
                layout.addLayout(actions)
            elif page_id == "online":
                actions = QHBoxLayout()
                self.refresh_online = QPushButton("تحديث المتصلين", objectName="primary")
                self.refresh_online.clicked.connect(self._refresh_online)
                self.trust_online = QPushButton("إضافة المحدد للموثوقة")
                self.trust_online.clicked.connect(self._trust_online)
                self.disconnect_online = QPushButton("فصل المتصل", objectName="danger")
                self.disconnect_online.clicked.connect(self._disconnect_online)
                actions.addWidget(self.refresh_online)
                actions.addWidget(self.trust_online)
                actions.addWidget(self.disconnect_online)
                actions.addStretch()
                layout.addLayout(actions)
            elif page_id == "vlans":
                actions = QHBoxLayout()
                actions.addWidget(QLabel("الشبكة"))
                self.vlan_picker = QComboBox()
                self.vlan_picker.setMinimumWidth(260)
                self.vlan_picker.currentIndexChanged.connect(self._select_vlan)
                self.refresh_vlans = QPushButton("تحديث الشبكات", objectName="primary")
                self.refresh_vlans.clicked.connect(self._refresh_vlans)
                self.name_vlan_device = QPushButton("تسمية الجهاز")
                self.name_vlan_device.clicked.connect(self._name_vlan_device)
                self.scan_vlan_overlap = QPushButton("فحص التداخل")
                self.scan_vlan_overlap.clicked.connect(self._scan_vlan_overlap)
                self.exclude_dhcp_range = QPushButton("استثناء نطاق DHCP")
                self.exclude_dhcp_range.clicked.connect(self._exclude_dhcp_range)
                self.bind_vlan_dhcp = QPushButton("ربط IP بـ MAC")
                self.bind_vlan_dhcp.clicked.connect(self._bind_vlan_dhcp)
                self.cut_vlan_devices = QPushButton("فصل المحدد", objectName="danger")
                self.cut_vlan_devices.clicked.connect(self._disconnect_vlan_devices)
                actions.addWidget(self.vlan_picker)
                actions.addWidget(self.refresh_vlans)
                actions.addWidget(self.name_vlan_device)
                actions.addWidget(self.scan_vlan_overlap)
                actions.addWidget(self.exclude_dhcp_range)
                actions.addWidget(self.bind_vlan_dhcp)
                actions.addWidget(self.cut_vlan_devices)
                actions.addStretch()
                layout.addLayout(actions)
                self.vlan_context = QLabel("حدّث الشبكات لعرض الأجهزة المتصلة بها.", objectName="subtle")
                self.vlan_context.setWordWrap(True)
                layout.addWidget(self.vlan_context)
            elif page_id == "management":
                actions = QHBoxLayout()
                self.refresh_management = QPushButton("تحديث", objectName="primary")
                self.refresh_management.clicked.connect(self._refresh_management)
                self.add_management = QPushButton("إضافة جهاز إدارة")
                self.add_management.clicked.connect(self._add_management)
                self.remove_management = QPushButton("إزالة جهاز إدارة", objectName="danger")
                self.remove_management.clicked.connect(self._remove_management)
                for button in (self.refresh_management, self.add_management, self.remove_management): actions.addWidget(button)
                actions.addStretch(); layout.addLayout(actions)
            elif page_id == "wan":
                actions = QHBoxLayout()
                self.check_wan = QPushButton("فحص الخطوط الآن", objectName="primary")
                self.check_wan.clicked.connect(lambda: self._check_wan(True))
                self.withdraw_wan = QPushButton("إخراج الخط من التوزيع", objectName="danger")
                self.withdraw_wan.clicked.connect(self._withdraw_wan)
                self.restore_wan = QPushButton("إعادة الخط إلى التوزيع")
                self.restore_wan.clicked.connect(self._restore_wan)
                self.copy_wan_report = QPushButton("نسخ التقرير")
                self.copy_wan_report.clicked.connect(self._copy_wan_report)
                self.wan_auto = FullRowCheckBox("مراقبة تلقائية")
                self.wan_auto.setChecked(bool(self.c.settings.get("wan_auto")))
                self.wan_auto.toggled.connect(self._toggle_wan_auto)
                for button in (self.check_wan, self.withdraw_wan, self.restore_wan, self.copy_wan_report, self.wan_auto): actions.addWidget(button)
                actions.addStretch(); layout.addLayout(actions)
            elif page_id == "nat":
                hint = QLabel("أضف أو عدّل أو احذف تحويل TCP من واجهة WAN. يتحقق التطبيق من التعارض والمسار، ويعيد قراءة الراوتر بعد كل تغيير.", objectName="subtle")
                hint.setWordWrap(True)
                layout.addWidget(hint)
                actions = QHBoxLayout()
                self.add_static_nat = QPushButton("إضافة تحويل منفذ", objectName="primary")
                self.add_static_nat.clicked.connect(self._add_static_nat)
                self.edit_static_nat = QPushButton("تعديل التحويل المحدد")
                self.edit_static_nat.clicked.connect(self._edit_static_nat)
                self.delete_static_nat = QPushButton("حذف التحويل المحدد", objectName="danger")
                self.delete_static_nat.clicked.connect(self._delete_static_nat)
                self.refresh_nat = QPushButton("تحديث التحويلات")
                self.refresh_nat.clicked.connect(self._refresh_nat)
                actions.addWidget(self.add_static_nat)
                actions.addWidget(self.edit_static_nat)
                actions.addWidget(self.delete_static_nat)
                actions.addWidget(self.refresh_nat)
                actions.addStretch(); layout.addLayout(actions)
            search = QLineEdit()
            search.setPlaceholderText("بحث في النتائج…")
            layout.addWidget(search)
            panel = QFrame(objectName="panel")
            panel_layout = QVBoxLayout(panel)
            table = QTableWidget(0, len(item["columns"]))
            table.setHorizontalHeaderLabels(item["columns"])
            table.setEditTriggers(QTableWidget.NoEditTriggers)
            table.setSelectionBehavior(QTableWidget.SelectRows)
            table.setItemDelegate(NoFocusCellDelegate(table))
            table.setToolTip("حدّد صفاً ثم اضغط Ctrl+C للنسخ. لا يمكن تعديل الجدول.")
            if page_id == "vlans":
                table.setSelectionMode(QAbstractItemView.ExtendedSelection)
            if page_id == "online":
                table.cellDoubleClicked.connect(lambda _row, _column: self._trust_online())
            table.verticalHeader().hide()
            table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            panel_layout.addWidget(table)
            search.textChanged.connect(lambda text, view=table: self._filter(view, text))
            self.tables[page_id] = table
            QShortcut(QKeySequence.Copy, table,
                      activated=lambda view=table: self._copy_table_selection(view))
            layout.addWidget(panel, 1)
        elif page_id == "groups":
            return self._permission_groups_page()
        elif page_id == "settings":
            form = QFormLayout()
            self.setting_mac_password = QLineEdit(); self.setting_mac_password.setEchoMode(QLineEdit.Password)
            self.setting_mac_password_confirm = QLineEdit(); self.setting_mac_password_confirm.setEchoMode(QLineEdit.Password)
            self.setting_show_mac_password = FullRowCheckBox("إظهار كلمة السر")
            self.setting_show_mac_password.toggled.connect(self._set_setting_mac_password_visibility)
            self.setting_mac_password_status = QLabel("اكتب كلمة السر مرتين للتحقق.", objectName="subtle")
            self.setting_mac_password_status.setWordWrap(True)
            self.setting_mac_password.textChanged.connect(self._update_setting_mac_password_match)
            self.setting_mac_password_confirm.textChanged.connect(self._update_setting_mac_password_match)
            self.setting_autosave = FullRowCheckBox("حفظ إعداد الراوتر تلقائياً")
            self.setting_autosave.setChecked(bool(self.c.settings.get("auto_save_config", True)))
            self.storage_mode = QComboBox()
            self.storage_mode.addItem(tr("محلي فقط"), "local")
            self.storage_mode.addItem(tr("Firebase أساسي"), "firebase")
            self.storage_mode.setCurrentIndex(1 if self.c.settings.get("storage_mode") == "firebase" else 0)
            self.storage_mode_hint = QLabel(self._storage_mode_hint(), objectName="subtle")
            self.storage_mode_hint.setWordWrap(True)
            self.storage_mode.currentIndexChanged.connect(self._update_storage_mode_hint)
            self.setting_firebase_key, self.setting_firebase_project = QLineEdit(), QLineEdit()
            self.setting_firebase_email, self.setting_firebase_password = QLineEdit(), QLineEdit()
            self.setting_firebase_key.setText(self.c.settings.get("firebase_api_key", "")); self.setting_firebase_project.setText(self.c.settings.get("firebase_project_id", ""))
            self.setting_firebase_email.setText(self.c.settings.get("firebase_email", "")); self.setting_firebase_password.setEchoMode(QLineEdit.Password)
            password_row = QWidget()
            password_layout = QHBoxLayout(password_row)
            password_layout.setContentsMargins(0, 0, 0, 0)
            password_layout.setSpacing(8)
            password_layout.addWidget(self.setting_mac_password, 1)
            self.rotate_mac_password = QPushButton("تغيير كلمة السر وتعميمها")
            self.rotate_mac_password.clicked.connect(self._rotate_mac_password)
            password_layout.addWidget(self.rotate_mac_password)
            form.addRow("كلمة MAC المشتركة", password_row)
            form.addRow("تأكيد كلمة MAC", self.setting_mac_password_confirm)
            form.addRow(self.setting_show_mac_password)
            form.addRow(self.setting_mac_password_status)
            form.addRow(self.setting_autosave)
            form.addRow("وضع التخزين", self.storage_mode)
            form.addRow(self.storage_mode_hint)
            form.addRow("Firebase API Key", self.setting_firebase_key); form.addRow("Firebase Project ID", self.setting_firebase_project)
            form.addRow("Firebase e-mail", self.setting_firebase_email); form.addRow("Firebase password", self.setting_firebase_password)
            credential_row = QWidget()
            credential_layout = QHBoxLayout(credential_row)
            credential_layout.setContentsMargins(0, 0, 0, 0)
            credential_layout.setSpacing(8)
            self.firebase_credential_status = QLabel(self._firebase_credential_status(), objectName="subtle")
            self.firebase_credential_status.setWordWrap(True)
            self.import_firebase_credentials = QPushButton("استيراد بيانات اعتماد Firebase")
            self.import_firebase_credentials.clicked.connect(self._import_firebase_credentials)
            credential_layout.addWidget(self.firebase_credential_status, 1)
            credential_layout.addWidget(self.import_firebase_credentials)
            form.addRow("ملف Firebase service account", credential_row)
            layout.addLayout(form)
            actions = QHBoxLayout(); self.save_settings = QPushButton("حفظ الإعدادات", objectName="primary"); self.save_settings.clicked.connect(self._save_settings)
            self.firebase_sync = QPushButton("مزامنة Firebase الآن")
            self.firebase_sync.clicked.connect(self._firebase_sync)
            self.firebase_download = self.firebase_upload = self.firebase_sync
            self._update_storage_controls()
            for button in (self.save_settings, self.firebase_sync): actions.addWidget(button)
            actions.addStretch(); layout.addLayout(actions); layout.addStretch()
        elif page_id == "log":
            self.log_text = QTextEdit(objectName="commandLog"); self.log_text.setReadOnly(True); self.log_text.setLayoutDirection(Qt.LeftToRight)
            layout.addWidget(self.log_text, 1)
            self.copy_log = QPushButton("نسخ", objectName="primary"); self.copy_log.clicked.connect(self._copy_log)
            layout.addWidget(self.copy_log, alignment=Qt.AlignRight)
        return page

    def _select_nav(self, index):
        for i, button in enumerate(self.nav):
            button.setChecked(i == index)

    def _connect(self):
        if self.c.router.connected:
            self.c.close()
            self._render()
            return
        if self.connect_dialog is not None:
            self.connect_dialog.raise_()
            self.connect_dialog.activateWindow()
            return
        self.connect_dialog = ConnectDialog(self.c.settings, self)
        self.connect_dialog.finished.connect(self._finish_connect)
        self.connect_dialog.open()
        self.connect_dialog.raise_()
        self.connect_dialog.activateWindow()

    def _finish_connect(self, result):
        dialog, self.connect_dialog = self.connect_dialog, None
        if result != QDialog.Accepted or dialog is None:
            return
        try:
            port = int(dialog.port.text() or 22)
        except ValueError:
            QMessageBox.warning(self, "اتصال", "المنفذ يجب أن يكون رقماً.")
            return
        if not dialog.host.text().strip() or not dialog.username.text().strip() or not dialog.password.text():
            QMessageBox.warning(self, "اتصال", "أكمل عنوان الراوتر واسم المستخدم وكلمة المرور.")
            return
        self._run(lambda: self.c.connect(
            dialog.host.text().strip(), port, dialog.username.text().strip(), dialog.password.text()))

    def _refresh(self):
        if not self.c.router.connected:
            QMessageBox.information(self, "تحديث", "اتصل بالراوتر أولاً.")
            return
        self._run(self.c.refresh)

    def _refresh_online(self):
        if not self.c.router.connected:
            QMessageBox.information(self, "تحديث المتصلين", "اتصل بالراوتر أولاً.")
            return
        self._run(self.c.refresh_online)

    def _vlan_label(self, network):
        suffix = " — %s/%s" % (network["ip"], network["len"]) if network.get("ip") else " — بلا واجهة عنوان"
        return "VLAN %s%s" % (network["vid"], suffix)

    def _refresh_vlans(self):
        if not self.c.router.connected:
            QMessageBox.information(self, "تحديث الشبكات", "اتصل بالراوتر أولاً.")
            return
        current = self.vlan_picker.currentData() if hasattr(self, "vlan_picker") else ""
        self._run(lambda: self.c.refresh_vlans(current))

    def _select_vlan(self, _index):
        if not self.c.router.connected or not hasattr(self, "vlan_picker"):
            return
        vid = self.vlan_picker.currentData()
        if vid:
            self._run(lambda: self.c.select_vlan(vid))

    def _selected_vlan_mac(self):
        table = self.tables.get("vlans")
        if table is None or not table.selectionModel().hasSelection():
            return ""
        row = table.selectionModel().selectedRows()[0].row()
        item = table.item(row, 1)
        return item.text() if item else ""

    def _selected_vlan_macs(self):
        table = self.tables.get("vlans")
        if table is None or not table.selectionModel().hasSelection():
            return []
        macs = []
        for index in table.selectionModel().selectedRows():
            item = table.item(index.row(), 1)
            mac12 = legacy.normalize_mac(item.text() if item else "")
            if mac12 and mac12 not in macs:
                macs.append(mac12)
        return macs

    def _name_vlan_device(self):
        mac = self._selected_vlan_mac()
        if not mac:
            QMessageBox.information(self, "تسمية جهاز", "اختر جهازاً من الجدول أولاً.")
            return
        mac12 = legacy.normalize_mac(mac)
        if not mac12:
            QMessageBox.warning(self, "تسمية جهاز", "عنوان MAC المحدد غير صالح.")
            return
        dialog = NameVlanDeviceDialog(
            mac12, self.c.db.name_of(mac12), self.c.db.note_of(mac12), self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._run(lambda: self.c.update_vlan_metadata(
            mac12, dialog.name.text(), dialog.note.text()),
            lambda result: self._show_vlan_name_result(result, mac12))

    def _scan_vlan_overlap(self):
        if not self.c.router.connected:
            QMessageBox.information(self, "فحص التداخل", "اتصل بالراوتر أولاً.")
            return
        if not self.c.vlans:
            QMessageBox.information(self, "فحص التداخل", "حدّث قائمة الشبكات أولاً.")
            return
        self._run(self.c.scan_vlan_overlap, self._show_vlan_overlap_result)

    def _dhcp_network_ready(self, title):
        if not self.c.router.connected:
            QMessageBox.information(self, title, "اتصل بالراوتر أولاً.")
            return False
        state = self.c.vlan_state or {}
        if not state:
            QMessageBox.information(self, title, "حدّث الشبكات واختر شبكة أولاً.")
            return False
        if not state.get("iface"):
            QMessageBox.information(self, title,
                                    "هذه الشبكة بلا واجهة عنوان على الراوتر، ولا تملك DHCP محلياً.")
            return False
        if not state.get("dhcp"):
            QMessageBox.information(self, title,
                                    "هذه الشبكة لا تستخدم DHCP من واجهتها على الراوتر.")
            return False
        return True

    def _exclude_dhcp_range(self):
        title = "استثناء نطاق DHCP"
        if not self._dhcp_network_ready(title):
            return
        dialog = ExcludeDhcpRangeDialog(self.c.vlan_state, self)
        if dialog.exec() != QDialog.Accepted:
            return
        start, end = dialog.start.text().strip(), dialog.end.text().strip()
        if self.lang == "en":
            question = ("DHCP will stop distributing addresses from %s to %s on %s."
                        "\n\nManually static devices will not be disconnected." %
                        (start or "—", end or "—", self.c.vlan_state.get("iface", "")))
        else:
            question = ("سيُمنع DHCP من توزيع العناوين من %s إلى %s على %s."
                        "\n\nلن تُفصل الأجهزة ذات العنوان الثابت اليدوي." %
                        (start or "—", end or "—", self.c.vlan_state.get("iface", "")))
        if dialog.disconnect.isChecked():
            question += ("\nOnly exactly matching DHCP sessions will be disconnected to renew their address."
                         if self.lang == "en"
                         else "\nستُفصل فقط جلسات DHCP المطابقة لتجديد عنوانها.")
        choice = QMessageBox.question(self, title, question,
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if choice != QMessageBox.Yes:
            return
        self._run(lambda: self.c.exclude_dhcp_range(
            start, end, dialog.disconnect.isChecked()), self._show_exclude_dhcp_result)

    def _show_exclude_dhcp_result(self, result):
        messages = {
            "excluded": (QMessageBox.Information,
                         "تم استثناء النطاق والتحقق من إعداد الراوتر."),
            "unchanged": (QMessageBox.Information, "هذا النطاق مستثنى بالفعل."),
            "no_dhcp": (QMessageBox.Warning, "الشبكة المحددة لا تملك DHCP محلياً."),
            "bad_range": (QMessageBox.Warning, "أدخل نطاق IP صحيحاً بترتيب البداية ثم النهاية."),
            "outside_network": (QMessageBox.Warning, "النطاق خارج شبكة الواجهة المحددة."),
            "overlap_excluded": (QMessageBox.Warning,
                                 "النطاق يتداخل جزئياً مع نطاق DHCP مستثنى بالفعل."),
            "binding_in_range": (QMessageBox.Warning,
                                 "يوجد ربط DHCP ثابت داخل النطاق المطلوب استثناؤه."),
            "not_confirmed": (QMessageBox.Critical,
                              "نُفذ الأمر لكن النطاق لم يظهر عند إعادة قراءة الإعداد."),
            "router_error": (QMessageBox.Critical, result.error or "تعذر تعديل مجمّع DHCP."),
        }
        icon, message = messages.get(result.code, (QMessageBox.Warning,
            "تم الاستثناء، لكن تعذر فصل بعض الجلسات المطابقة."))
        if result.data and result.code in {"excluded", "excluded_partial"}:
            affected, cut = len(result.data.get("affected", [])), len(result.data.get("cut", []))
            message += (("\n\nDHCP leases in range: %d. Sessions disconnected: %d." if self.lang == "en"
                         else "\n\nإيجارات DHCP داخل النطاق: %d. جلسات مفصولة: %d.") %
                        (affected, cut))
            if not result.data.get("saved", True):
                message += "\n" + tr("لم يُحفظ إعداد بدء التشغيل تلقائياً.")
        box = QMessageBox(self)
        box.setWindowTitle("استثناء نطاق DHCP")
        box.setIcon(icon)
        box.setText(message)
        box.exec()

    def _bind_vlan_dhcp(self):
        title = "ربط IP ثابت بـ MAC"
        if not self._dhcp_network_ready(title):
            return
        mac = self._selected_vlan_mac()
        if not mac:
            QMessageBox.information(self, title, "اختر جهازاً من جدول الشبكة أولاً.")
            return
        dialog = DhcpBindingDialog(mac, self.c.vlan_state, self)
        if dialog.exec() != QDialog.Accepted:
            return
        ip = dialog.ip.text().strip()
        pretty_mac = legacy.mac_pretty(legacy.normalize_mac(mac))
        if self.lang == "en":
            question = "Bind %s to %s in DHCP on %s." % (
                pretty_mac, ip or "—", self.c.vlan_state.get("iface", ""))
        else:
            question = "سيُربط %s بالعنوان %s في DHCP على %s." % (
                pretty_mac, ip or "—", self.c.vlan_state.get("iface", ""))
        choice = QMessageBox.question(
            self, title, question,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if choice != QMessageBox.Yes:
            return
        self._run(lambda: self.c.bind_vlan_dhcp(
            mac, ip, dialog.description.text(), dialog.disconnect.isChecked()),
            self._show_bind_vlan_dhcp_result)

    def _show_bind_vlan_dhcp_result(self, result):
        messages = {
            "bound": (QMessageBox.Information, "تم ربط IP بـ MAC والتحقق من إعداد DHCP."),
            "unchanged": (QMessageBox.Information, "هذا الربط موجود بالفعل."),
            "no_dhcp": (QMessageBox.Warning, "الشبكة المحددة لا تملك DHCP محلياً."),
            "bad_mac": (QMessageBox.Warning, "عنوان MAC المحدد غير صالح."),
            "outside_network": (QMessageBox.Warning, "عنوان IP خارج شبكة الواجهة المحددة."),
            "address_excluded": (QMessageBox.Warning,
                                 "لا يمكن ربط عنوان مستثنى من مجمّع DHCP."),
            "ip_in_use": (QMessageBox.Warning,
                          "العنوان مستخدم حالياً أو ظاهر لجهاز MAC آخر."),
            "mac_bound": (QMessageBox.Warning, "هذا MAC مربوط بالفعل بعنوان DHCP آخر."),
            "not_confirmed": (QMessageBox.Critical,
                              "نُفذ الأمر لكن الربط لم يظهر عند إعادة قراءة الإعداد."),
            "router_error": (QMessageBox.Critical, result.error or "تعذر إنشاء ربط DHCP."),
        }
        icon, message = messages.get(result.code, (QMessageBox.Warning,
            "تم الربط، لكن تعذر فصل الجلسة المختارة لتجديد العنوان."))
        if result.data and result.code in {"bound", "bound_partial"}:
            if result.data.get("release"):
                message += (("\nReleased previous lease: %s." if self.lang == "en"
                             else "\nحُرر الإيجار السابق: %s.") % result.data["release"])
            if not result.data.get("saved", True):
                message += "\n" + tr("لم يُحفظ إعداد بدء التشغيل تلقائياً.")
        box = QMessageBox(self)
        box.setWindowTitle("ربط IP ثابت بـ MAC")
        box.setIcon(icon)
        box.setText(message)
        box.exec()

    def _show_vlan_overlap_result(self, result):
        if not result.ok:
            QMessageBox.warning(self, "فحص التداخل", result.error or "تعذر فحص مجمّعات الشبكات.")

    def _disconnect_vlan_devices(self):
        if not self.c.router.connected:
            QMessageBox.information(self, "فصل المحدد", "اتصل بالراوتر أولاً.")
            return
        macs = self._selected_vlan_macs()
        if not macs:
            QMessageBox.information(self, "فصل المحدد", "اختر جهازاً واحداً أو أكثر من الجدول أولاً.")
            return
        if not (self.c.vlan_state or {}).get("nac"):
            QMessageBox.information(
                self, "فصل المحدد",
                "لا توجد مصادقة على هذه الشبكة، لذلك لا توجد جلسة يمكن فصلها.")
            return
        details = []
        table = self.tables["vlans"]
        for index in table.selectionModel().selectedRows():
            row = index.row()
            values = [table.item(row, column).text() if table.item(row, column) else ""
                      for column in (0, 1, 2)]
            details.append("• %s  %s%s" % (values[0] or "—", values[1],
                                            ("  — " + values[2]) if values[2] else ""))
        question = ("سيُفصل %s جهازاً من جلسة الوصول الحالية فقط. "
                    "يمكن للجهاز العودة فور نجاح المصادقة من جديد.\n\n%s" %
                    (len(macs), "\n".join(details)))
        choice = QMessageBox.question(self, "فصل المحدد", question,
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if choice != QMessageBox.Yes:
            return
        self._run(lambda: self.c.disconnect_vlan_devices(macs),
                  self._show_vlan_disconnect_result)

    def _show_vlan_disconnect_result(self, result):
        if result.code == "disconnected":
            QMessageBox.information(self, "فصل المحدد", "تم فصل الجلسات المحددة وإعادة قراءة الشبكة.")
            return
        if result.code == "partial":
            bad = ", ".join(legacy.mac_pretty(mac) for mac in result.data["bad"])
            QMessageBox.warning(self, "فصل المحدد", "تعذر فصل بعض الجلسات: " + bad)
            return
        if result.code == "no_authentication":
            QMessageBox.information(self, "فصل المحدد", "لا توجد مصادقة على هذه الشبكة.")
            return
        QMessageBox.warning(self, "فصل المحدد", result.error or "تعذر فصل الجلسات المحددة.")

    def _show_vlan_name_result(self, result, mac):
        if not result.ok:
            QMessageBox.warning(self, "تسمية جهاز", "تعذر حفظ الاسم المحلي.")
            return
        if result.code == "updated":
            self._select_vlan_by_mac(mac)

    def _selected_online_session(self):
        table = self.tables.get("online")
        if table is None or not table.selectionModel().hasSelection():
            return None
        row = table.selectionModel().selectedRows()[0].row()
        session_id = table.item(row, 0).text() if table.item(row, 0) else ""
        session = next((item for item in self.c.online if item.get("id") == session_id), None)
        return dict(session) if session else None

    def _disconnect_online(self):
        if not self.c.router.connected:
            QMessageBox.information(self, "فصل المتصل", "اتصل بالراوتر أولاً.")
            return
        session = self._selected_online_session()
        if not session:
            QMessageBox.information(self, "فصل المتصل", "اختر اتصالاً من الجدول أولاً.")
            return
        dialog = DisconnectOnlineDialog(session, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._run(lambda: self.c.disconnect_online(session["id"]),
                  self._show_disconnect_online_result)

    def _trust_online(self):
        if not self.c.router.connected:
            QMessageBox.information(self, "إضافة جهاز موثوق", "اتصل بالراوتر أولاً.")
            return
        session = self._selected_online_session()
        if not session:
            QMessageBox.information(self, "إضافة جهاز موثوق", "اختر اتصالاً من الجدول أولاً.")
            return
        mac12 = legacy.normalize_mac(session["mac"])
        if not mac12:
            QMessageBox.warning(self, "إضافة جهاز موثوق", "هذا الاتصال لا يحمل عنوان MAC صالحاً.")
            return
        local = self.c.db.device(mac12) or {}
        if mac12 in self.c.users:
            QMessageBox.information(
                self, "إضافة جهاز موثوق",
                "هذا الجهاز موثوق مسبقاً.\n\n%s" % legacy.mac_pretty(mac12))
            return
        groups = sorted(self.c.groups)
        if not groups:
            QMessageBox.warning(self, "إضافة جهاز موثوق", "حدّث مجموعات الصلاحيات أولاً.")
            return
        dialog = TrustOnlineDialog(
            session, groups, self.c.settings.get("default_mac_group", "grp_staff"), local, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._run(lambda: self.c.trust_online(
            session, dialog.name.text(), dialog.group.currentText(), dialog.note.text()),
            lambda result: self._show_trust_online_result(result, session, dialog.group.currentText()))

    def _show_trust_online_result(self, result, session, group):
        messages = {
            "added": (QMessageBox.Information, "تمت إضافة الجهاز والتحقق منه على الراوتر."),
            "bad_mac": (QMessageBox.Warning, "عنوان MAC المحدد غير صالح."),
            "missing_name": (QMessageBox.Warning, "اكتب اسماً وصفياً للجهاز."),
            "duplicate": (QMessageBox.Warning, "هذا الجهاز موثوق مسبقاً."),
            "missing_group": (QMessageBox.Warning, "اختر مجموعة صلاحيات للجهاز."),
            "placeholder_password": (QMessageBox.Warning,
                                     "اضبط كلمة مرور حسابات MAC من الإعدادات أولاً."),
            "password_is_mac": (QMessageBox.Warning, "كلمة مرور حسابات MAC لا يجوز أن تساوي عنوان MAC."),
            "not_confirmed": (QMessageBox.Critical, "نُفذت الأوامر لكن الحساب لم يثبت في إعداد الراوتر."),
            "router_error": (QMessageBox.Critical, result.error or "تعذر تنفيذ العملية على الراوتر."),
        }
        icon, message = messages.get(result.code, (QMessageBox.Critical, "تعذر إتمام العملية."))
        box = QMessageBox(self)
        box.setWindowTitle("إضافة جهاز موثوق")
        box.setIcon(icon)
        box.setText(message)
        box.exec()
        mac12 = legacy.normalize_mac(session["mac"])
        if result.ok and session["user"].lower() != mac12:
            choice = QMessageBox.question(
                self, "فصل الاتصال الحالي",
                "أضيف الجهاز، لكن جلسته الحالية تستخدم الحساب %s.\n\n"
                "هل تريد فصلها الآن ليعيد المصادقة بمجموعة %s؟" % (session["user"], group),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if choice == QMessageBox.Yes:
                self._run(lambda: self.c.disconnect_online(session["id"]),
                          self._show_disconnect_online_result)

    def _show_disconnect_online_result(self, result):
        messages = {
            "disconnected": (QMessageBox.Information, "تم فصل الاتصال الحالي."),
            "missing_session": (QMessageBox.Warning, "رقم الجلسة غير صالح."),
            "not_confirmed": (QMessageBox.Critical,
                              "نُفذ الأمر لكن الجلسة ما زالت ظاهرة على الراوتر."),
            "router_error": (QMessageBox.Critical, result.error or "تعذر تنفيذ العملية على الراوتر."),
        }
        icon, message = messages.get(result.code, (QMessageBox.Critical, "تعذر فصل المتصل."))
        box = QMessageBox(self)
        box.setWindowTitle("فصل المتصل")
        box.setIcon(icon)
        box.setText(message)
        box.exec()

    def _run(self, fn, on_success=None):
        if self._busy:
            return
        self._set_busy(True)
        self._set_operation_status("جارٍ تنفيذ العملية…", "working")
        worker = Worker(fn)
        self.workers.append(worker)
        worker.done.connect(lambda result: self._finished(worker, result, on_success))
        worker.failed.connect(lambda message: self._failed(worker, message))
        worker.finished.connect(lambda: self._retire_worker(worker))
        worker.start()

    def _retire_worker(self, worker):
        if worker in self.workers:
            self.workers.remove(worker)

    def _finished(self, worker, result, on_success=None):
        if worker.isFinished() and worker in self.workers:
            self.workers.remove(worker)
        self._render()
        self._set_busy(False)
        if self.c._firebase_dirty and not self.c.firebase_error:
            self._next_cloud_poll = 0
        QTimer.singleShot(0, self._auto_firebase_sync)
        if isinstance(result, legacy.ActionResult) and not result.ok:
            self._set_operation_status("تعذرت العملية", "error")
        else:
            self._set_operation_status("اكتملت العملية", "ok")
        if on_success:
            on_success(result)

    def _failed(self, worker, message):
        if worker.isFinished() and worker in self.workers:
            self.workers.remove(worker)
        self._set_busy(False)
        self._set_operation_status("تعذرت العملية", "error")
        QMessageBox.critical(self, "تعذر إتمام العملية", message)

    def _render(self):
        self._render_firebase_status()
        connected = self.c.router.connected
        host = self.c.router.hostname if connected else tr("لا يوجد اتصال")
        self.router_label.setText((tr("● متصل بـ ") if connected else "● ") + host)
        self.connection.setText(tr("● متصل") if connected else tr("● غير متصل"))
        for label in (self.router_label, self.connection):
            label.setProperty("connected", connected)
            label.style().unpolish(label)
            label.style().polish(label)
        self.connect_button.setText("قطع الاتصال" if connected else "اتصال")
        if self.demo:
            self.connection.setText(self.connection.text() + " — DEMO")
        self._fill("devices", self._device_rows())
        self._fill("portal", self._portal_rows())
        self._render_online()
        self._render_vlans()
        self._fill("management", self.c.management_rows())
        self._render_wan()
        self._render_nat()
        if hasattr(self, "log_text"):
            self.log_text.setPlainText(self._masked_log())
        counts = {}
        for account in self.c.users.values():
            if account.get("group"):
                counts[account["group"]] = counts.get(account["group"], 0) + 1
        self._render_permission_groups()
        for metric, value in zip(self.metrics, (len(self._device_rows()), len(self._portal_rows()), len(self.c.online), len(self.c.groups))):
            metric.setText(str(value))

    def _device_rows(self):
        return self.c.device_rows()

    def _portal_rows(self):
        return self.c.portal_rows()

    def _online_status(self, status):
        """يحوّل قيمة الراوتر إلى حالة قصيرة قابلة للفهم وذات لون محدد."""
        normalized = (status or "").strip().lower()
        if normalized.startswith(("success", "authen", "active")):
            return tr("نشط"), QColor("#067647")
        if "pre-auth" in normalized or "preauth" in normalized:
            return tr("قبل المصادقة"), QColor("#B54708")
        return str(status or tr("غير معروف")), QColor("#B42318")

    def _render_online(self):
        sessions = self.c.online_rows()
        rows, colors = [], []
        for session in sessions:
            status, color = self._online_status(session.get("status", ""))
            rows.append([session.get("id", ""), session.get("user", ""), session.get("description", ""),
                         session.get("connection_method", "—"), session.get("group", "") or "—",
                         session.get("ip", ""), session.get("mac", ""), status])
            colors.append(color)
        self._fill("online", rows)
        table = self.tables.get("online")
        if table is not None:
            for row_index, color in enumerate(colors):
                item = table.item(row_index, 7)
                if item is not None:
                    item.setForeground(color)

    def _render_vlans(self):
        picker = getattr(self, "vlan_picker", None)
        context = getattr(self, "vlan_context", None)
        if picker is None or context is None:
            return
        current = picker.currentData()
        picker.blockSignals(True)
        picker.clear()
        for network in self.c.vlans:
            picker.addItem(self._vlan_label(network), network["vid"])
        desired = str((self.c.vlan_state or {}).get("vid") or current or "")
        index = picker.findData(desired)
        if index >= 0:
            picker.setCurrentIndex(index)
        picker.blockSignals(False)

        state = self.c.vlan_state or {}
        self._fill("vlans", self._vlan_rows(state))
        if not state:
            context.setText(tr("حدّث الشبكات لعرض الأجهزة المتصلة بها."))
            for button in (getattr(self, "exclude_dhcp_range", None),
                           getattr(self, "bind_vlan_dhcp", None)):
                if button is not None:
                    button.setEnabled(True)
            return
        english = self.lang == "en"
        ports = (", " if english else "، ").join(state.get("ports") or [])
        if not ports:
            ports = "No router port carries this VLAN" if english else "لا يوجد منفذ حامل على الراوتر"
        if not state.get("iface"):
            if english:
                context.setText("VLAN %s — %s. This network has no routed interface or DHCP pool." %
                                (state.get("vid", ""), ports))
            else:
                context.setText("VLAN %s — %s. لا توجد واجهة عنوان أو مجمّع DHCP لهذه الشبكة." %
                                (state.get("vid", ""), ports))
            for button in (getattr(self, "exclude_dhcp_range", None),
                           getattr(self, "bind_vlan_dhcp", None)):
                if button is not None:
                    button.setEnabled(True)
            return
        pool = state.get("pool") or {}
        pool_text = "No pool data" if english else "لا توجد بيانات مجمّع"
        if pool:
            usable = (pool.get("total") or 0) - (pool.get("disabled") or 0)
            pool_text = ("Pool: %s used of %s available" if english
                         else "المجمّع: مستخدم %s من %s متاح") % (pool.get("used", 0), usable)
        description = (" — %s" % state["desc"]) if state.get("desc") else ""
        dhcp_text = ("DHCP enabled" if english else "DHCP متاح") if state.get("dhcp") \
            else ("DHCP not enabled" if english else "DHCP غير مفعّل")
        excluded = state.get("excluded") or []
        if excluded:
            dhcp_text += (" · Excluded: " if english else " · مستثنى: ") + (", " if english else "، ").join(
                "%s–%s" % (item["start"], item["end"]) for item in excluded)
        for button in (getattr(self, "exclude_dhcp_range", None),
                       getattr(self, "bind_vlan_dhcp", None)):
            if button is not None:
                # Keep the action reachable so its handler can explain whether the
                # selected network has a DHCP pool, rather than leaving a silent
                # disabled control.  _dhcp_network_ready still blocks every write.
                button.setEnabled(True)
        summary = "VLAN %s%s · %s · %s · %s" % (
            state.get("vid", ""), description, state["iface"], pool_text + " · " + ports, dhcp_text)
        overlap = self.c.vlan_overlap or {}
        duplicates = overlap.get("dups") or {}
        crossed = sum(1 for record in state.get("rows", [])
                      if any(entry["vid"] != str(state.get("vid", ""))
                             for entry in duplicates.get(record["mac"], [])))
        tight = overlap.get("tight") or []
        notes = []
        if crossed:
            notes.append(("Warning: %s device(s) hold an address in another network." if english
                          else "تنبيه: %s جهاز يحمل عنواناً في شبكة أخرى.") % crossed)
        if tight:
            notes.append(("Pools close to full: " if english else "المجمّعات القريبة من الامتلاء: ")
                         + (", " if english else "، ").join(
                ("VLAN %s (%s/%s available)" if english else "VLAN %s (%s/%s متاح)") %
                (entry["vid"], entry["idle"], entry["usable"])
                for entry in tight))
        context.setText(summary + ("\n" + "\n".join(notes) if notes else ""))

    def _wan_probe(self, result, applicable=True):
        """يعرض نتيجة NQA كإشارة سريعة، لا كقاموس تقني خام."""
        if not applicable or result is None:
            return "—", QColor("#667085")
        if result.get("ok"):
            return tr("✓ يعمل"), QColor("#067647")
        return tr("✗ فشل"), QColor("#B42318")

    def _wan_verdict(self, line):
        verdict = line.get("verdict") or "unknown"
        texts = {
            "ok": tr("سليم"), "slow": tr("بطيء / غير مستقر"),
            "throttled": tr("مخنوق — انتهت الحصة؟"),
            "blocked": tr("محجوب — انتهت الحصة؟"), "down": tr("مقطوع"),
            "port_down": tr("المنفذ مفصول"), "withdrawn": tr("خارج التوزيع"),
            "unknown": tr("غير معروف"),
        }
        colors = {
            "ok": QColor("#067647"), "slow": QColor("#B54708"),
            "unknown": QColor("#B54708"), "throttled": QColor("#B42318"),
            "blocked": QColor("#B42318"), "down": QColor("#B42318"),
            "port_down": QColor("#B42318"), "withdrawn": QColor("#667085"),
        }
        text = texts.get(verdict, tr("غير معروف"))
        if verdict == "withdrawn" and line.get("health") not in (None, "withdrawn"):
            text = "%s · %s" % (text, texts.get(line["health"], tr("غير معروف")))
        return text, colors.get(verdict, QColor("#667085"))

    def _wan_route(self, line):
        if line.get("withdrawn"):
            return tr("خارج التوزيع")
        if line.get("route_state") == "Active":
            return tr("في التوزيع")
        if line.get("route_state"):
            return tr("مسار غير صالح")
        return "—"

    def _render_wan(self):
        rows, line_colors, probe_colors = [], [], []
        for line in self.c.wan_lines:
            applicable = line.get("health") != "port_down"
            ping, ping_color = self._wan_probe(line.get("icmp_result"), applicable)
            https, https_color = self._wan_probe(line.get("tcp_result"), applicable)
            verdict, verdict_color = self._wan_verdict(line)
            latency = (line.get("ping") or {}).get("avg")
            rows.append([
                line.get("desc") or line["gw"], line.get("iface") or "—", line["gw"],
                self._wan_route(line), ping, https, "—" if latency is None else "%s ms" % latency,
                "—" if line.get("kbps") is None else "%s kbps" % line["kbps"],
                line.get("phys") or "—", verdict,
            ])
            line_colors.append(verdict_color)
            probe_colors.append((ping_color, https_color))
        self._fill("wan", rows)
        table = self.tables.get("wan")
        if table is None:
            return
        for row_index, line_color in enumerate(line_colors):
            for column in range(table.columnCount()):
                item = table.item(row_index, column)
                if item is not None:
                    item.setForeground(line_color)
            for column, color in zip((4, 5), probe_colors[row_index]):
                item = table.item(row_index, column)
                if item is not None:
                    item.setForeground(color)

    def _render_nat(self):
        self._fill("nat", [[rule.get("interface", ""), rule.get("wan_ip", "") or "—",
                            rule.get("protocol", "").upper(), str(rule.get("external_port", "")),
                            rule.get("inside_ip", ""), str(rule.get("inside_port", ""))]
                           for rule in self.c.nat_rules])

    @staticmethod
    def _application_category(signature):
        categories = {
            "WhatsAPP": "Messaging", "WhatsAPP_FileTransfer": "Messaging",
            "WhatsAPP_VoIP": "Messaging", "WhatsAPP_Web": "Messaging",
            "Facebook": "Social media", "Instagram": "Social media", "Threads": "Social media",
            "TikTok": "Video & social", "Youtube": "Video", "YouTube_Music": "Video",
            "YouTube_Kids": "Video", "OpenVPN": "VPN / tunnel", "WireGuardVPN": "VPN / tunnel",
            "NordVPN": "VPN / tunnel", "ExpressVPN": "VPN / tunnel", "ProtonVPN": "VPN / tunnel",
            "Shadowsocks": "VPN / tunnel",
        }
        category = categories.get(signature, "Application signature")
        if ACTIVE_LANGUAGE != "en":
            return {
                "Messaging": "مراسلة", "Social media": "تواصل اجتماعي",
                "Video & social": "فيديو وتواصل", "Video": "فيديو",
                "VPN / tunnel": "VPN / نفق", "Application signature": "توقيع تطبيق",
            }.get(category, category)
        return category

    def _render_permission_groups(self, *_ignored):
        group_picker = getattr(self, "application_group", None)
        interface_picker = getattr(self, "application_interface", None)
        table = getattr(self, "application_table", None)
        if group_picker is None or interface_picker is None or table is None:
            return
        previous_group, previous_interface = group_picker.currentData(), interface_picker.currentData()
        group_picker.blockSignals(True)
        group_picker.clear()
        for name, acl in sorted(self.c.groups.items()):
            group_picker.addItem("%s  ·  ACL %s" % (name, acl or "—"), name)
        index = group_picker.findData(previous_group)
        if index >= 0:
            group_picker.setCurrentIndex(index)
        group_picker.blockSignals(False)

        group = group_picker.currentData() or ""
        group_key = re.sub(r"[^a-z0-9]", "", group.lower().replace("grp", "", 1))
        group_keys = {group_key}
        if group_key.endswith("s"):
            group_keys.add(group_key[:-1])
        elif group_key:
            group_keys.add(group_key + "s")
        interface_details = self.c.application_config.get("interfaces") or {}
        # VRP does not bind an AAA user-group to a Vlanif in its application-policy
        # syntax.  The gateway descriptions are only a safe display hint; actions
        # still target the selected interface policy explicitly.
        candidates = []
        for interface, details in sorted(interface_details.items()):
            description_key = re.sub(r"[^a-z0-9]", "", details.get("description", "").lower())
            if any(key and key in description_key for key in group_keys):
                candidates.append(interface)
        access_interfaces = [(interface, details) for interface, details in sorted(interface_details.items())
                             if details.get("nac") or details.get("inbound_policy")]
        interface_picker.blockSignals(True)
        interface_picker.clear()
        for interface, details in access_interfaces:
            policy = details.get("inbound_policy", "")
            description = details.get("description", "")
            policy_text = policy or ("لا توجد سياسة تطبيقات" if ACTIVE_LANGUAGE != "en" else "no application policy")
            label = "%s%s  →  %s" % (interface, (" · " + description) if description else "", policy_text)
            interface_picker.addItem(label, interface)
        group_changed = group != getattr(self, "_last_application_group", None)
        preferred_interface = candidates[0] if group_changed and candidates else previous_interface
        index = interface_picker.findData(preferred_interface)
        if index >= 0:
            interface_picker.setCurrentIndex(index)
        interface_picker.blockSignals(False)

        self._last_application_group = group
        acl_no = self.c.groups.get(group, "")
        interface = interface_picker.currentData() or ""
        policy = (interface_details.get(interface) or {}).get("inbound_policy", "")
        rows = legacy.application_policy_rows(self.c.application_config, policy, acl_no) if policy else []
        english = ACTIVE_LANGUAGE == "en"
        if not group:
            context = ("Refresh while connected to read permission groups and policies."
                       if english else "حدّث أثناء الاتصال لقراءة المجموعات والسياسات.")
        elif not policy:
            inferred = " (matched from its gateway description)" if interface in candidates and english else \
                       (" (مستنتجة من وصف البوابة)" if interface in candidates else "")
            context = (("%s uses ACL %s. Its selected network is %s%s, and it has no inbound application policy. "
                        "No application is currently shown as blocked for this group.") %
                       (group, acl_no or "—", interface or "—", inferred)
                       if english else
                       ("المجموعة %s مرتبطة بـ ACL %s. شبكتها المحددة هي %s%s ولا توجد عليها سياسة تطبيقات واردة؛ "
                        "لذلك لا يعرض التطبيق أي حظر تطبيقات لهذه المجموعة.") %
                       (group, acl_no or "—", interface or "—", inferred))
        else:
            default_deny = bool((self.c.application_config.get("acls") or {}).get(str(acl_no), {}).get("default_deny"))
            acl_state = ("default deny" if default_deny else "no detected default deny") if english else \
                        ("منع افتراضي" if default_deny else "لا يوجد منع افتراضي ظاهر")
            same_network = interface in candidates
            scope = ("The selected interface is separate from this group; " if not same_network and english else
                     ("الواجهة المحددة منفصلة عن هذه المجموعة؛ " if not same_network else ""))
            context = (("Group %s → ACL %s (%s). %sInterface %s applies policy %s inbound. "
                        "That policy affects every matching user on this interface, not this group alone.") %
                       (group, acl_no or "—", acl_state, scope, interface, policy) if english else
                       ("المجموعة %s ← ACL %s (%s). %sالواجهة %s تطبق السياسة %s على الاتجاه الوارد. "
                        "تؤثر السياسة في كل مستخدم يطابقها على الواجهة، لا في هذه المجموعة وحدها.") %
                       (group, acl_no or "—", acl_state, scope, interface, policy))
        self.application_context.setText(context)
        can_change_policy = bool(policy and (not candidates or interface in candidates))
        if hasattr(self, "block_application"):
            self.block_application.setEnabled(can_change_policy)
        if hasattr(self, "allow_application"):
            self.allow_application.setEnabled(can_change_policy)

        query = self.application_search.text() if hasattr(self, "application_search") else ""
        table.setRowCount(len(rows))
        for row_index, item in enumerate(rows):
            state = item["state"]
            if state == "blocked":
                label = "Blocked" if english else "محظور"
                rules = item["rules"]
                source = ", ".join("%s / %s" % (rule["classifier"], rule["precedence"])
                                   for rule in rules)
                color = QColor("#B42318")
            elif state == "acl-dependent":
                label = "ACL-dependent" if english else "مرتبط بـ ACL"
                source = (("ACL %s has a default deny; app policy does not grant access." % (acl_no or "—"))
                          if english else ("ACL %s لديه منع افتراضي؛ سياسة التطبيقات لا تمنح وصولاً." % (acl_no or "—")))
                color = QColor("#B54708")
            else:
                label = "Not blocked by this policy" if english else "غير محظور بهذه السياسة"
                source = ("No deny classifier in %s" % policy if english else "لا يوجد مصنف منع في %s" % policy)
                color = QColor("#067647")
            values = [item["application"], self._application_category(item["application"]), label, source]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if column == 2:
                    cell.setForeground(color)
                table.setItem(row_index, column, cell)
        self._filter(table, query)
        self.application_explanation.setText(
            ("Important: “not blocked by this policy” does not mean the application is allowed. "
             "A default-deny ACL may still block its IP/CDN traffic. WhatsApp media needs its file-transfer "
             "signature and reachable media destinations; Facebook and Instagram share Meta infrastructure, "
             "so an IP-only allowlist cannot reliably separate them. Block and allow actions show their scope, "
             "reread the router, then save only when automatic saving is enabled.") if english else
            ("مهم: «غير محظور بهذه السياسة» لا يعني أن التطبيق مسموح. قد يمنع ACL ذو المنع الافتراضي "
             "عناوين التطبيق أو CDN. يحتاج وسائط واتساب إلى توقيع نقل الملفات وإلى وجهات الوسائط المتاحة؛ "
             "وتشترك فيسبوك وإنستغرام في بنية Meta، لذلك لا تفصل بينهما قائمة سماح تعتمد على IP فقط بشكل موثوق. "
             "تعرض أزرار الحظر والسماح نطاق الأثر، ثم تعيد قراءة الراوتر، وتحفظ فقط عند تفعيل الحفظ التلقائي."))

    def _describe_selected_application(self):
        table = getattr(self, "application_table", None)
        if table is None or not table.selectionModel().hasSelection():
            return
        row = table.selectionModel().selectedRows()[0].row()
        app = table.item(row, 0).text() if table.item(row, 0) else ""
        state = table.item(row, 2).text() if table.item(row, 2) else ""
        source = table.item(row, 3).text() if table.item(row, 3) else ""
        english = ACTIVE_LANGUAGE == "en"
        message = (("%s\n\nCurrent state: %s\nSource: %s\n\nBlock creates a dedicated classifier and verifies it. "
                    "Allow removes the classifier association only; if that classifier has several signatures, "
                    "the application asks for an explicit bundle confirmation.") % (app, state, source) if english else
                   ("%s\n\nالحالة الحالية: %s\nالمصدر: %s\n\nالحظر ينشئ مصنفاً مستقلاً ويتحقق منه. "
                    "السماح يفك ارتباط المصنف فقط؛ وإذا احتوى المصنف عدة تواقيع سيطلب التطبيق تأكيداً صريحاً لنطاق الأثر.") % (app, state, source))
        QMessageBox.information(self, "تفاصيل التطبيق", message)

    def _selected_application_policy_item(self):
        table = getattr(self, "application_table", None)
        if table is None or not table.selectionModel().hasSelection():
            return "", "", ""
        row = table.selectionModel().selectedRows()[0].row()
        application = table.item(row, 0).text() if table.item(row, 0) else ""
        state = table.item(row, 2).text() if table.item(row, 2) else ""
        interface = self.application_interface.currentData() if hasattr(self, "application_interface") else ""
        policy = ((self.c.application_config.get("interfaces") or {}).get(interface, {})
                  .get("inbound_policy", ""))
        return application, policy, state

    def _block_selected_application(self):
        if not self.c.router.connected:
            QMessageBox.information(self, "حظر تطبيق", "اتصل بالراوتر أولاً.")
            return
        application, policy, state = self._selected_application_policy_item()
        if not application or not policy:
            QMessageBox.information(self, "حظر تطبيق", "اختر تطبيقاً وواجهة لديها سياسة واردة أولاً.")
            return
        if state in {"محظور", "Blocked"}:
            QMessageBox.information(self, "حظر تطبيق", "التطبيق محظور بهذه السياسة بالفعل.")
            return
        interface = self.application_interface.currentData()
        auto_save = bool(self.c.settings.get("auto_save_config", True))
        text = (
            "سيُنشئ التطبيق مصنفاً مستقلاً للتوقيع %s، ثم يربطه بالسلوك BLOCK "
            "في سياسة %s على الواجهة %s. لن يغيّر ACL المجموعة.\n\n"
            "سيعاد قراءة الراوتر للتحقق قبل الحفظ%s." %
            (application, policy, interface, " التلقائي" if auto_save else "")
        )
        if QMessageBox.question(self, "تأكيد حظر التطبيق", text,
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self._run(lambda: self.c.block_application(policy, application), self._show_block_application_result)

    def _show_block_application_result(self, result):
        messages = {
            "application_blocked": (QMessageBox.Information, "تم حظر التطبيق والتحقق من السياسة."),
            "already_blocked": (QMessageBox.Information, "التطبيق محظور بالفعل."),
            "bad_application": (QMessageBox.Warning, "التوقيع المحدد غير صالح لهذا الراوتر."),
            "missing_policy": (QMessageBox.Warning, "سياسة الواجهة لم تعد موجودة على الراوتر."),
            "missing_deny_behavior": (QMessageBox.Warning, "لا توجد قاعدة سلوك deny يمكن ربطها بأمان."),
            "classifier_conflict": (QMessageBox.Warning, "اسم المصنف المحجوز يتعارض مع مصنف مختلف."),
            "not_confirmed": (QMessageBox.Critical, "نُفذت الأوامر لكن الحظر لم يثبت عند إعادة القراءة."),
            "save_failed": (QMessageBox.Warning, "ثبت الحظر لكن تعذر حفظ إعداد بدء التشغيل."),
            "router_error": (QMessageBox.Critical, result.error or "رفض الراوتر الأمر."),
        }
        icon, text = messages.get(result.code, (QMessageBox.Critical, "تعذر تغيير سياسة التطبيق."))
        QMessageBox(icon, "حظر تطبيق", text, parent=self).exec()

    def _allow_selected_application(self):
        if not self.c.router.connected:
            QMessageBox.information(self, "السماح لتطبيق", "اتصل بالراوتر أولاً.")
            return
        application, policy, _state = self._selected_application_policy_item()
        if not application or not policy:
            QMessageBox.information(self, "السماح لتطبيق", "اختر تطبيقاً وواجهة لديها سياسة واردة أولاً.")
            return
        self._run(lambda: self.c.allow_application(policy, application),
                  lambda result: self._show_allow_application_result(result, policy, application, False))

    def _show_allow_application_result(self, result, policy, application, confirmed_bundle=False):
        if result.code == "shared_classifier" and not confirmed_bundle:
            affected = result.data.get("affected", []) if result.data else []
            text = ("التوقيع %s جزء من مصنف واحد. السماح له سيفك حظر التطبيقات التالية معاً:\n\n%s\n\n"
                    "لن يغيّر ذلك ACL المجموعة. هل تريد المتابعة؟" %
                    (application, "\n".join("• " + item for item in affected)))
            if QMessageBox.question(self, "تأكيد السماح لمجموعة تطبيقات", text,
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
                self._run(lambda: self.c.allow_application(policy, application, True),
                          lambda retry: self._show_allow_application_result(
                              retry, policy, application, True))
            return
        messages = {
            "application_allowed": (QMessageBox.Information, "تم فك الحظر والتحقق من السياسة."),
            "not_blocked": (QMessageBox.Information, "التطبيق غير محظور بهذه السياسة."),
            "not_confirmed": (QMessageBox.Critical, "نُفذت الأوامر لكن فك الحظر لم يثبت عند إعادة القراءة."),
            "save_failed": (QMessageBox.Warning, "ثبت فك الحظر لكن تعذر حفظ إعداد بدء التشغيل."),
            "router_error": (QMessageBox.Critical, result.error or "رفض الراوتر الأمر."),
        }
        icon, text = messages.get(result.code, (QMessageBox.Critical, "تعذر تغيير سياسة التطبيق."))
        QMessageBox(icon, "السماح لتطبيق", text, parent=self).exec()

    def _copy_application_review(self):
        group = self.application_group.currentData() if hasattr(self, "application_group") else ""
        interface = self.application_interface.currentData() if hasattr(self, "application_interface") else ""
        lines = [self.application_context.text(), ""]
        table = getattr(self, "application_table", None)
        if table is not None:
            for row in range(table.rowCount()):
                if table.isRowHidden(row):
                    continue
                lines.append(" | ".join(table.item(row, col).text() if table.item(row, col) else ""
                                        for col in range(table.columnCount())))
        QApplication.clipboard().setText("Group: %s\nInterface: %s\n%s" %
                                         (group or "—", interface or "—", "\n".join(lines)))
        self._set_operation_status("تم نسخ تقرير السياسة" if ACTIVE_LANGUAGE != "en" else "Policy report copied", "ok")

    def _vlan_rows(self, state):
        kinds = {"dhcp": "DHCP", "bind": tr("حجز ثابت"), "static": tr("عنوان ثابت"), "none": tr("بلا عنوان")}
        presence = {"active": tr("حاضر"), "seen": tr("مرئي بلا عنوان"), "lease": tr("حجز فقط")}
        rows = []
        for record in state.get("rows", []):
            mac = record["mac"]
            if record.get("random"):
                vendor = tr("عنوان عشوائي")
            else:
                vendor = legacy.mac_vendor(mac) or legacy.mac_oui(mac) or tr("غير معروف")
            other = [entry for entry in (self.c.vlan_overlap or {}).get("dups", {}).get(mac, [])
                     if entry["vid"] != str(state.get("vid", ""))]
            rows.append([
                record.get("ip", ""), legacy.mac_pretty(mac), self.c.db.name_of(mac), vendor,
                record.get("port") or "—", kinds.get(record.get("kind"), "—"),
                presence.get(record.get("presence"), "—"), record.get("auth") or "—",
                " · ".join("VLAN %s (%s)" % (entry["vid"], entry["ip"]) for entry in other) or "—",
            ])
        return rows

    def _fill(self, name, rows):
        table = self.tables.get(name)
        if table is None:
            return
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column, value in enumerate(row):
                table.setItem(row_index, column, QTableWidgetItem(tr(str(value))))

    def _filter(self, table, query):
        query = query.strip().lower()
        for row in range(table.rowCount()):
            text = " ".join(table.item(row, column).text().lower() for column in range(table.columnCount()) if table.item(row, column))
            table.setRowHidden(row, bool(query) and query not in text)

    def _copy_table_selection(self, table):
        rows = sorted({index.row() for index in table.selectionModel().selectedRows()})
        if not rows:
            return
        text = "\n".join("\t".join(
            table.item(row, column).text() if table.item(row, column) else ""
            for column in range(table.columnCount())) for row in rows)
        QApplication.clipboard().setText(text)
        self._set_operation_status("تم نسخ %d صف" % len(rows), "ok")

    def _set_operation_status(self, message, state):
        self.operation_status.setText(message)
        self.operation_status.setProperty("state", state)
        self.operation_status.style().unpolish(self.operation_status)
        self.operation_status.style().polish(self.operation_status)

    def _set_busy(self, busy):
        """يقفل عناصر التحكم أثناء أمر واحد؛ لا توجد جلسات RouterSession متوازية."""
        if self._busy == busy:
            return
        self._busy = busy
        if busy:
            # لا نسمح لدورة المراقبة التلقائية أن تبدأ قراءة ثانية أثناء أمر قائم.
            self.wan_timer.stop()
            self._busy_widgets = []
            for widget_type in (QPushButton, QCheckBox, QComboBox, QLineEdit, QTableWidget, QTextEdit):
                for widget in self.centralWidget().findChildren(widget_type):
                    if widget is not self.busy_overlay:
                        self._busy_widgets.append((widget, widget.isEnabled()))
                        widget.setEnabled(False)
            self.busy_overlay.setGeometry(self.centralWidget().rect())
            self.busy_overlay.show()
            self.busy_overlay.raise_()
            return
        self.busy_overlay.hide()
        for widget, was_enabled in self._busy_widgets:
            widget.setEnabled(was_enabled)
        self._busy_widgets = []
        if self.c.settings.get("wan_auto") and self.c.router.connected:
            self.wan_timer.start(60000)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._busy and hasattr(self, "busy_overlay"):
            self.busy_overlay.setGeometry(self.centralWidget().rect())

    def _masked_log(self):
        try:
            with open(legacy.LOG_FILE, encoding="utf-8") as handle:
                return legacy.mask_password(handle.read())[-50000:]
        except OSError:
            return ""

    def _selected_row(self, page, key_column=0):
        table = self.tables.get(page)
        if table is None or not table.selectionModel().hasSelection(): return ""
        item = table.item(table.selectionModel().selectedRows()[0].row(), key_column)
        return item.text() if item else ""

    def _refresh_management(self):
        if not self.c.router.connected: QMessageBox.information(self, "أجهزة الإدارة", "اتصل بالراوتر أولاً."); return
        self._run(self.c.refresh_management)

    def _add_management(self):
        if not self.c.router.connected: QMessageBox.information(self, "أجهزة الإدارة", "اتصل بالراوتر أولاً."); return
        # صفحة الإدارة لا تُحمّل حالتها عند فتح التطبيق. سابقاً كانت الضغطة
        # الأولى تحدّثها ثم تنتهي بصمت، فيبدو زر الإضافة معطلاً. نكمل الإجراء
        # نفسه بعد انتهاء القراءة، ولا نطلب من المستخدم ضغطة ثانية.
        if not self.c.mgmt_state:
            self._run(self.c.refresh_management, lambda _result: self._add_management())
            return
        dialog = QDialog(self); dialog.setWindowTitle("إضافة جهاز إدارة"); form = QFormLayout(dialog)
        mac, name, ip, iface, acl = QLineEdit(), QLineEdit(), QLineEdit(), QComboBox(), QComboBox()
        iface.setMinimumContentsLength(28)
        acl.setMinimumContentsLength(18)
        for net in self.c.mgmt_state.get("networks", []): iface.addItem("%s (%s/%s)" % (net["iface"], net["ip"], net["len"]), net["iface"])
        for number, value in sorted(self.c.mgmt_state.get("acls", {}).items()): acl.addItem("%s %s" % (number, value.get("desc", "")), number)
        form.addRow("عنوان MAC", mac); form.addRow("الاسم الوصفي", name); form.addRow("الشبكة", iface); form.addRow("عنوان IP", ip); form.addRow("ACL الإدارة", acl)
        suggestion = QLabel("يجري اختيار أعلى عنوان IP متاح…", objectName="subtle")
        form.addRow("", suggestion)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); form.addRow(buttons)
        confirm = buttons.button(QDialogButtonBox.Ok)

        def suggest_ip():
            selected_iface = iface.currentData()
            if not selected_iface:
                ip.clear(); confirm.setEnabled(False); suggestion.setText("لا توجد شبكة قابلة للاختيار."); return
            confirm.setEnabled(False)
            ip.setPlaceholderText("جاري البحث عن عنوان متاح…")
            suggestion.setText("يجري فحص العناوين المستخدمة في الشبكة المختارة…")
            worker = Worker(lambda: self.c.suggested_management_ip(selected_iface))
            self.workers.append(worker)

            def apply_suggestion(value):
                if worker in self.workers: self.workers.remove(worker)
                if iface.currentData() != selected_iface: return
                ip.setText(value)
                ip.setPlaceholderText("")
                confirm.setEnabled(bool(value))
                suggestion.setText("اقتراح تلقائي: أعلى عنوان IP غير مستخدم. يمكنك تعديله.")

            def show_suggestion_error(message):
                if worker in self.workers: self.workers.remove(worker)
                if iface.currentData() == selected_iface:
                    ip.setPlaceholderText("")
                    confirm.setEnabled(True)
                    suggestion.setText("تعذر فحص العناوين: %s" % message)

            worker.done.connect(apply_suggestion)
            worker.failed.connect(show_suggestion_error)
            worker.start()

        iface.currentIndexChanged.connect(suggest_ip)
        suggest_ip()
        if dialog.exec() != QDialog.Accepted: return
        detail = "سيُنشئ ربط DHCP وARP ثابتاً وقاعدة ACL لهذا العنوان فقط."
        if QMessageBox.question(self, "تأكيد إضافة جهاز إدارة", detail, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes: return
        self._run(lambda: self.c.add_management(mac.text(), name.text(), iface.currentData(), ip.text(), acl.currentData()), self._show_management_result)

    def _management_validation_text(self, items):
        """يعرض مفاتيح تحقق المحرك نفسها التي كانت تعرضها واجهة Tk."""
        messages = legacy.TXT.get(self.lang, legacy.TXT["ar"])
        lines = []
        for key, values in items or []:
            template = messages.get(key, key)
            try:
                lines.append("• " + (template % values))
            except (KeyError, TypeError, ValueError):
                lines.append("• " + template)
        return "\n".join(lines)

    def _show_management_result(self, result):
        """لا تُخفِ سبب رفض خطة الإدارة خلف رمز مثل invalid_plan."""
        title = tr("أجهزة الإدارة")
        data = result.data or {}
        messages = legacy.TXT.get(self.lang, legacy.TXT["ar"])
        if result.code == "added":
            ip = data.get("plan", {}).get("ip", "")
            QMessageBox.information(self, title, messages["mgmt_ok_status"] % ip)
            return
        if result.code == "bad_mac":
            QMessageBox.warning(self, title, messages["err_bad_mac"])
            return
        if result.code == "missing_name":
            QMessageBox.warning(self, title, messages["err_need_name"])
            return
        if result.code == "invalid_plan":
            text = self._management_validation_text(data.get("errors"))
            warnings = self._management_validation_text(data.get("warnings"))
            if warnings:
                text += ("\n\n" if text else "") + messages["mgmt_warn_head"] + "\n" + warnings
            QMessageBox.warning(self, title, messages["mgmt_err_title"] + ("\n\n" + text if text else ""))
            return
        if result.code == "partial":
            failed_step, error = data.get("failed_step"), data.get("error")
            missing = data.get("missing") or []
            if failed_step:
                message = messages["mgmt_fail"] % {"step": failed_step,
                                                    "error": error or "—",
                                                    "rollback": ""}
            elif missing:
                message = messages["mgmt_missing"] % ", ".join(missing)
            else:
                message = result.error or messages["mgmt_incomplete"]
            QMessageBox.critical(self, title, message)
            return
        QMessageBox.warning(self, title, result.error or result.code)

    def _remove_management(self):
        ip = self._selected_row("management")
        entry = next((x for x in self.c.mgmt_rows if x["ip"] == ip), None)
        if not entry: QMessageBox.information(self, "إزالة جهاز إدارة", "اختر جهازاً أولاً."); return
        if QMessageBox.question(self, "إزالة جهاز إدارة", "سيُزال ACL وARP وربط DHCP للعنوان %s." % ip, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes: return
        self._run(lambda: self.c.remove_management(entry), self._show_action("إزالة جهاز إدارة"))

    def _refresh_nat(self):
        if not self.c.router.connected:
            QMessageBox.information(self, "تحويل المنافذ NAT", "اتصل بالراوتر أولاً.")
            return
        self._run(self.c.refresh_nat)

    def _add_static_nat(self):
        if not self.c.router.connected:
            QMessageBox.information(self, "تحويل المنافذ NAT", "اتصل بالراوتر أولاً.")
            return
        # نعيد قراءة القواعد قبل إظهار الحوار؛ لا نعتمد على جدول قديم عند
        # اختيار المنفذ لأن التعارض قد يقطع خدمة قائمة.
        self._run(self.c.refresh_nat, self._show_add_static_nat_dialog)

    def _show_add_static_nat_dialog(self, _rules):
        if not self.c.nat_interfaces:
            QMessageBox.warning(self, "تحويل المنافذ NAT", "اختر واجهة الإنترنت أولاً.")
            return
        dialog = AddStaticNatDialog(self.c.nat_interfaces, self)
        if dialog.exec() != QDialog.Accepted:
            return
        interface = dialog.interface.currentData()
        external_port, inside_ip, inside_port = (dialog.external_port.text().strip(),
                                                 dialog.inside_ip.text().strip(),
                                                 dialog.inside_port.text().strip())
        if not interface:
            QMessageBox.warning(self, "تحويل المنافذ NAT", "اختر واجهة الإنترنت أولاً.")
            return
        if not legacy.valid_port(external_port) or not legacy.valid_port(inside_port):
            QMessageBox.warning(self, "تحويل المنافذ NAT", "رقم المنفذ يجب أن يكون بين 1 و65535.")
            return
        if not legacy.valid_ip(inside_ip):
            QMessageBox.warning(self, "تحويل المنافذ NAT", "عنوان الجهاز الداخلي غير صالح.")
            return
        detail = ("سيُضاف التحويل التالي ثم يعاد قراءته للتحقق:\n\n"
                  "TCP %s:%s → %s:%s" % (interface, external_port, inside_ip, inside_port))
        if QMessageBox.question(self, "أضف قاعدة تحويل المنفذ", detail,
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        self._run(lambda: self.c.add_static_nat(interface, external_port, inside_ip, inside_port),
                  self._show_static_nat_result)

    def _selected_nat_rule(self):
        table = self.tables.get("nat")
        if table is None or not table.selectionModel().hasSelection():
            return None
        row = table.selectionModel().selectedRows()[0].row()
        return self.c.nat_rules[row] if 0 <= row < len(self.c.nat_rules) else None

    def _edit_static_nat(self):
        if not self.c.router.connected:
            QMessageBox.information(self, "تحويل المنافذ NAT", "اتصل بالراوتر أولاً.")
            return
        original = self._selected_nat_rule()
        if not original:
            QMessageBox.information(self, "تعديل تحويل المنفذ", "اختر تحويلاً من الجدول أولاً.")
            return
        dialog = AddStaticNatDialog(self.c.nat_interfaces, self, original)
        if dialog.exec() != QDialog.Accepted:
            return
        interface = dialog.interface.currentData()
        external_port, inside_ip, inside_port = (dialog.external_port.text().strip(),
                                                 dialog.inside_ip.text().strip(),
                                                 dialog.inside_port.text().strip())
        if not interface:
            QMessageBox.warning(self, "تعديل تحويل المنفذ", "اختر واجهة الإنترنت أولاً.")
            return
        if not legacy.valid_port(external_port) or not legacy.valid_port(inside_port):
            QMessageBox.warning(self, "تعديل تحويل المنفذ", "رقم المنفذ يجب أن يكون بين 1 و65535.")
            return
        if not legacy.valid_ip(inside_ip):
            QMessageBox.warning(self, "تعديل تحويل المنفذ", "عنوان الجهاز الداخلي غير صالح.")
            return
        detail = ("سيُستبدل التحويل التالي بعد التحقق، ويعاد التحويل القديم تلقائياً إذا فشل البديل:\n\n"
                  "TCP %s:%s → %s:%s" % (interface, external_port, inside_ip, inside_port))
        if QMessageBox.question(self, "تعديل تحويل المنفذ", detail,
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        self._run(lambda: self.c.edit_static_nat(
            original, interface, external_port, inside_ip, inside_port), self._show_static_nat_result)

    def _delete_static_nat(self):
        if not self.c.router.connected:
            QMessageBox.information(self, "تحويل المنافذ NAT", "اتصل بالراوتر أولاً.")
            return
        rule = self._selected_nat_rule()
        if not rule:
            QMessageBox.information(self, "حذف تحويل المنفذ", "اختر تحويلاً من الجدول أولاً.")
            return
        detail = ("سيُحذف هذا التحويل ثم يعاد قراءة الراوتر للتأكد:\n\n"
                  "TCP %s:%s → %s:%s" % (rule["interface"], rule["external_port"],
                                          rule["inside_ip"], rule["inside_port"]))
        if QMessageBox.question(self, "حذف تحويل المنفذ", detail,
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        self._run(lambda: self.c.delete_static_nat(rule), self._show_static_nat_result)

    def _show_static_nat_result(self, result):
        title = "تحويل المنافذ NAT"
        messages = {
            "nat_added": (QMessageBox.Information, "أُضيف التحويل وتحقق التطبيق منه وحُفظ في الراوتر."),
            "nat_edited": (QMessageBox.Information, "عُدّل التحويل وتحقق التطبيق منه وحُفظ في الراوتر."),
            "nat_deleted": (QMessageBox.Information, "حُذف التحويل وتحقق التطبيق من اختفائه وحُفظ في الراوتر."),
            "unchanged": (QMessageBox.Information, "لم تتغير بيانات التحويل."),
            "missing_interface": (QMessageBox.Warning, "اختر واجهة الإنترنت أولاً."),
            "missing_selection": (QMessageBox.Warning, "لم تعد القاعدة المحددة موجودة على الراوتر. حدّث التحويلات ثم حاول مجدداً."),
            "bad_port": (QMessageBox.Warning, "رقم المنفذ يجب أن يكون بين 1 و65535."),
            "bad_ip": (QMessageBox.Warning, "عنوان الجهاز الداخلي غير صالح."),
            "inside_on_wan": (QMessageBox.Warning, "لا يمكن أن يكون الجهاز الداخلي في شبكة WAN نفسها."),
            "duplicate": (QMessageBox.Information, "هذا المنفذ محجوز بالفعل للتحويل نفسه."),
            "no_route": (QMessageBox.Warning, "لا يوجد مسار معروف إلى الجهاز الداخلي."),
            "not_confirmed": (QMessageBox.Critical, "نُفذت القاعدة لكن لم تظهر عند إعادة القراءة."),
            "edit_remove_not_confirmed": (QMessageBox.Critical, "لم يتأكد التطبيق من حذف التحويل القديم؛ لم تُنشأ القاعدة البديلة."),
            "edit_rolled_back": (QMessageBox.Warning, "تعذر إنشاء التحويل البديل؛ أعاد التطبيق التحويل القديم."),
            "edit_rollback_failed": (QMessageBox.Critical, "تعذر إنشاء التحويل البديل وتعذر استرجاع التحويل القديم. راجع سجل الأوامر فوراً."),
            "save_failed": (QMessageBox.Warning, "أُضيف التحويل وتحقق التطبيق منه، لكن تعذر حفظ إعداد بدء التشغيل."),
        }
        if result.code == "port_in_use":
            rule = (result.data or {}).get("rule", {})
            detail = "%s:%s" % (rule.get("inside_ip", "—"), rule.get("inside_port", "—"))
            QMessageBox.warning(self, title, "المنفذ الخارجي مستخدم بالفعل لتحويل آخر: %s" % detail)
            return
        icon, message = messages.get(result.code, (QMessageBox.Critical, result.error or "تعذر إتمام العملية."))
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(icon)
        box.setText(message)
        box.exec()

    def _check_wan(self, live):
        if not self.c.router.connected: QMessageBox.information(self, "خطوط الإنترنت", "اتصل بالراوتر أولاً."); return
        self._run(lambda: self.c.check_wan(live))

    def _withdraw_wan(self):
        gw = self._selected_row("wan", 2)
        if not gw: QMessageBox.information(self, "إخراج الخط", "اختر خطاً أولاً."); return
        if QMessageBox.question(self, "إخراج الخط", "سيُحذف المسار الافتراضي عبر %s مع إبقاء الخط قابلاً للإعادة." % gw, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes: return
        self._run(lambda: self.c.withdraw_wan(gw), self._show_action("إخراج الخط"))

    def _restore_wan(self):
        gw = self._selected_row("wan", 2)
        if not gw: QMessageBox.information(self, "إعادة الخط", "اختر خطاً أولاً."); return
        self._run(lambda: self.c.restore_wan(gw), self._show_action("إعادة الخط"))

    def _copy_wan_report(self):
        QApplication.clipboard().setText(self.c.wan_report())
        QMessageBox.information(self, "نسخ التقرير", "تم نسخ التقرير النصي.")

    def _toggle_wan_auto(self, enabled):
        self.c.settings["wan_auto"] = bool(enabled); legacy.save_settings(self.c.settings)
        if enabled: self.wan_timer.start(60000)
        else: self.wan_timer.stop()

    def _save_settings(self):
        password = self.setting_mac_password.text()
        confirmation = self.setting_mac_password_confirm.text()
        if password or confirmation:
            if password != confirmation:
                QMessageBox.warning(self, "الإعدادات", "كلمتا السر غير متطابقتين.")
                return
        values = {"mac_shared_password": password or self.c.settings.get("mac_shared_password", ""), "auto_save_config": self.setting_autosave.isChecked(), "firebase_api_key": self.setting_firebase_key.text().strip(), "firebase_project_id": self.setting_firebase_project.text().strip(), "firebase_email": self.setting_firebase_email.text().strip(), "firebase_password": self.setting_firebase_password.text() or self.c.settings.get("firebase_password", ""), "storage_mode": self.storage_mode.currentData()}
        self._run(lambda: self.c.save_preferences(values), self._show_storage_settings)

    def _set_setting_mac_password_visibility(self, visible):
        mode = QLineEdit.Normal if visible else QLineEdit.Password
        self.setting_mac_password.setEchoMode(mode)
        self.setting_mac_password_confirm.setEchoMode(mode)

    def _update_setting_mac_password_match(self):
        password = self.setting_mac_password.text()
        confirmation = self.setting_mac_password_confirm.text()
        if not password and not confirmation:
            self.setting_mac_password_status.setText("اكتب كلمة السر مرتين للتحقق.")
            self.setting_mac_password_status.setStyleSheet("")
        elif password == confirmation:
            self.setting_mac_password_status.setText("كلمتا السر متطابقتان.")
            self.setting_mac_password_status.setStyleSheet("color: #067647; font-weight: 700;")
        else:
            self.setting_mac_password_status.setText("كلمتا السر غير متطابقتين.")
            self.setting_mac_password_status.setStyleSheet("color: #B42318; font-weight: 700;")

    def _storage_mode_hint(self):
        cloud = hasattr(self, "storage_mode") and self.storage_mode.currentData() == "firebase"
        return ("Firebase أساسي: مزامنة تلقائية بين الأجهزة مع حفظ محلي ونسخ للاسترجاع."
                if cloud else "محلي فقط: لا اتصال بـ Firebase.")

    def _update_storage_mode_hint(self):
        if hasattr(self, "storage_mode_hint"):
            self.storage_mode_hint.setText(self._storage_mode_hint())

    def _update_storage_controls(self):
        cloud = self.c.settings.get("storage_mode") == "firebase"
        for button in (getattr(self, "firebase_download", None), getattr(self, "firebase_upload", None)):
            if button is not None:
                button.setEnabled(cloud)

    def _show_storage_settings(self, result):
        if not result.ok:
            QMessageBox.warning(self, "الإعدادات", result.error or "تعذرت العملية: " + result.code)
            return
        self._update_storage_controls()
        self._next_cloud_poll = 0
        QTimer.singleShot(0, self._auto_firebase_sync)
        QMessageBox.information(self, "الإعدادات", "اكتملت العملية.")

    def _firebase_credential_status(self):
        project = self.c.settings.get("firebase_project_id", "")
        if self.c.settings.get("firebase_service_account_file") and project:
            return "تم إعداد Firebase لمشروع: %s" % project
        return "لم يتم استيراد ملف Firebase بعد."

    def _import_firebase_credentials(self):
        path, _ = QFileDialog.getOpenFileName(self, "استيراد بيانات اعتماد Firebase", "",
                                               "JSON (*.json)")
        if not path:
            return
        self._run(lambda: self.c.import_firebase_service_account(path),
                  self._show_firebase_credential_import)

    def _show_firebase_credential_import(self, result):
        if not result.ok:
            QMessageBox.warning(self, "استيراد بيانات اعتماد Firebase",
                                result.error or "تعذر استيراد بيانات اعتماد Firebase.")
            return
        if hasattr(self, "firebase_credential_status"):
            self.firebase_credential_status.setText(self._firebase_credential_status())
        QMessageBox.information(self, "استيراد بيانات اعتماد Firebase",
                                "تم استيراد بيانات اعتماد Firebase. يمكنك الآن اختيار وضع التخزين.")

    def _rotate_mac_password(self):
        if not self.c.router.connected:
            QMessageBox.information(self, "تغيير كلمة السر", "اتصل بالراوتر أولاً.")
            return
        # القراءة قد تستغرق زمن الشبكة؛ نفذها في العامل حتى لا يبدو الزر بلا استجابة.
        self._run(self.c.read_mac_password_profiles, self._choose_mac_password_rotation)

    def _choose_mac_password_rotation(self, profiles):
        if not profiles:
            QMessageBox.warning(self, "تغيير كلمة السر", "لا يوجد ملف MAC صالح.")
            return
        dialog = RotateMacPasswordDialog(
            profiles, self.c.settings.get("mac_access_profile", ""), self)
        if dialog.exec() != QDialog.Accepted:
            return
        password = dialog.password.text()
        if password != dialog.password_confirm.text():
            QMessageBox.warning(self, "تغيير كلمة السر", "كلمتا السر غير متطابقتين.")
            return
        problem = legacy.mac_password_problem(password)
        if problem:
            messages = {
                "err_placeholder_pw": "أدخل كلمة سر جديدة بدلاً من القيمة الافتراضية.",
                "err_pw_weak": "كلمة السر يجب أن تكون 8 محارف على الأقل وتحتوي نوعين من المحارف.",
                "err_pw_chars": "كلمة السر لا يجوز أن تحتوي مسافات أو ? أو علامات تنصيص.",
                "err_pw_is_mac": "كلمة السر لا يجوز أن تساوي عنوان MAC.",
            }
            QMessageBox.warning(self, "تغيير كلمة السر", messages.get(problem, "كلمة السر غير صالحة."))
            return
        profile = dialog.profile.currentText()
        if QMessageBox.question(
                self, "تأكيد تغيير كلمة السر",
                "سيُحدّث التطبيق ملف %s وكل حسابات MAC، ويفك الحسابات المحظورة. هل تريد المتابعة؟" % profile,
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self._run(lambda: self.c.rotate_mac_password(profile, password),
                  self._show_mac_password_rotation_result)

    def _show_mac_password_rotation_result(self, result):
        if result.code == "rotated":
            self.setting_mac_password.setText(self.c.settings.get("mac_shared_password", ""))
            count = len((result.data or {}).get("unblocked", []))
            extra = "\nتم فك حظر %d حساب." % count if count else ""
            QMessageBox.information(self, "تغيير كلمة السر",
                                    "تم تغيير كلمة السر في الملف وحسابات MAC بنجاح." + extra)
            return
        if result.code == "partial":
            self.setting_mac_password.setText(self.c.settings.get("mac_shared_password", ""))
            failed = (result.data or {}).get("failed", {})
            detail = "\n".join("%s — %s" % (legacy.mac_pretty(mac), error)
                               for mac, error in sorted(failed.items()))
            QMessageBox.warning(self, "تغيير كلمة السر",
                                "تغيّرت كلمة السر في الملف، لكن بعض الحسابات رفضت التحديث.\n\n" + detail)
            return
        if result.code == "profile_failed":
            error = (result.data or {}).get("profile_error") or result.error
            QMessageBox.critical(self, "تغيير كلمة السر",
                                 "لم تتغير كلمة السر في ملف MAC، لذلك لم يُحدّث أي حساب.\n\n%s" % (error or "تعذر التحقق من التغيير."))
            return
        messages = {
            "missing_profile": "ملف MAC المحدد لم يعد موجوداً. حدّث البيانات ثم حاول مرة أخرى.",
            "err_placeholder_pw": "أدخل كلمة سر جديدة بدلاً من القيمة الافتراضية.",
            "err_pw_weak": "كلمة السر يجب أن تكون 8 محارف على الأقل وتحتوي نوعين من المحارف.",
            "err_pw_chars": "كلمة السر لا يجوز أن تحتوي مسافات أو ? أو علامات تنصيص.",
            "err_pw_is_mac": "كلمة السر لا يجوز أن تساوي عنوان MAC.",
        }
        QMessageBox.warning(self, "تغيير كلمة السر",
                            messages.get(result.code, result.error or "تعذرت العملية: " + result.code))

    def _firebase_download(self):
        self._firebase_sync()

    def _firebase_upload(self):
        self._firebase_sync()

    def _firebase_sync(self):
        self._next_cloud_poll = 0
        self._auto_firebase_sync()

    def _copy_log(self): QApplication.clipboard().setText(self._masked_log())
    def _show_action(self, title):
        def show(result):
            if result.ok and result.code == "pulled":
                self._render()
            box = QMessageBox.Information if result.ok else QMessageBox.Warning
            QMessageBox.information(self, title, "اكتملت العملية." if result.ok else (result.error or "تعذرت العملية: " + result.code)) if box == QMessageBox.Information else QMessageBox.warning(self, title, result.error or "تعذرت العملية: " + result.code)
        return show

    def _add_device(self):
        if not self.c.router.connected:
            QMessageBox.information(self, "إضافة جهاز", "اتصل بالراوتر أولاً.")
            return
        groups = sorted(self.c.groups)
        if not groups:
            QMessageBox.warning(self, "إضافة جهاز", "حدّث مجموعات الصلاحيات أولاً.")
            return
        dialog = AddDeviceDialog(groups, self.c.settings.get("default_mac_group", "grp_staff"), self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._run(lambda: self.c.create_device(
            dialog.mac.text(), dialog.name.text().strip(),
            dialog.group.currentText(), dialog.note.text().strip()), self._show_add_result)

    def _show_add_result(self, result):
        messages = {
            "added": (QMessageBox.Information, "تمت إضافة الجهاز والتحقق منه على الراوتر."),
            "bad_mac": (QMessageBox.Warning, "أدخل عنوان MAC صالحًا."),
            "duplicate": (QMessageBox.Warning, "عنوان MAC مسجل مسبقًا على الراوتر."),
            "missing_group": (QMessageBox.Warning, "اختر مجموعة صلاحيات للجهاز."),
            "placeholder_password": (QMessageBox.Warning,
                                     "اضبط كلمة مرور حسابات MAC من الإعدادات أولاً."),
            "password_is_mac": (QMessageBox.Warning, "كلمة مرور حسابات MAC لا يجوز أن تساوي عنوان MAC."),
            "not_confirmed": (QMessageBox.Critical, "نفذت الأوامر لكن الحساب لم يثبت في إعداد الراوتر."),
            "router_error": (QMessageBox.Critical, result.error or "تعذر تنفيذ العملية على الراوتر."),
        }
        icon, message = messages.get(result.code, (QMessageBox.Critical, "تعذر إتمام العملية."))
        box = QMessageBox(self)
        box.setWindowTitle("إضافة جهاز")
        box.setIcon(icon)
        box.setText(message)
        box.exec()

    def _add_portal(self):
        if not self.c.router.connected:
            QMessageBox.information(self, "إضافة حساب", "اتصل بالراوتر أولاً.")
            return
        groups = sorted(self.c.groups)
        if not groups:
            QMessageBox.warning(self, "إضافة حساب", "حدّث مجموعات الصلاحيات أولاً.")
            return
        dialog = AddPortalDialog(groups, self.c.settings.get("default_portal_group", "grp_staff"), self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._run(lambda: self.c.create_portal(
            dialog.username.text(), dialog.password.text(), dialog.name.text().strip(),
            dialog.group.currentText(), dialog.note.text().strip()), self._show_add_portal_result)

    def _show_add_portal_result(self, result):
        messages = {
            "added": (QMessageBox.Information, "تمت إضافة الحساب والتحقق منه على الراوتر."),
            "bad_username": (QMessageBox.Warning, "أدخل اسم حساب صالحًا من أحرف وأرقام فقط."),
            "short_password": (QMessageBox.Warning, "كلمة المرور يجب أن تكون 8 محارف على الأقل."),
            "password_is_username": (QMessageBox.Warning, "كلمة المرور لا يجوز أن تساوي اسم الحساب أو معكوسه."),
            "missing_group": (QMessageBox.Warning, "اختر مجموعة صلاحيات للحساب."),
            "duplicate": (QMessageBox.Warning, "اسم الحساب مسجل مسبقًا على الراوتر."),
            "not_confirmed": (QMessageBox.Critical, "نُفذت الأوامر لكن الحساب لم يثبت في إعداد الراوتر."),
            "router_error": (QMessageBox.Critical, result.error or "تعذر تنفيذ العملية على الراوتر."),
        }
        icon, message = messages.get(result.code, (QMessageBox.Critical, "تعذر إتمام العملية."))
        box = QMessageBox(self)
        box.setWindowTitle("إضافة حساب")
        box.setIcon(icon)
        box.setText(message)
        box.exec()

    def _reset_portal_password(self):
        if not self.c.router.connected:
            QMessageBox.information(self, "تغيير كلمة المرور", "اتصل بالراوتر أولاً.")
            return
        username = self._selected_portal_username()
        if not username:
            QMessageBox.information(self, "تغيير كلمة المرور", "اختر حسابًا من الجدول أولاً.")
            return
        dialog = ResetPortalPasswordDialog(username, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._run(lambda: self.c.change_portal_password(username, dialog.password.text()),
                  self._show_reset_portal_password_result)

    def _show_reset_portal_password_result(self, result):
        messages = {
            "password_changed": (QMessageBox.Information, "تم تغيير كلمة مرور الحساب."),
            "short_password": (QMessageBox.Warning, "كلمة المرور يجب أن تكون 8 محارف على الأقل."),
            "password_is_username": (QMessageBox.Warning, "كلمة المرور لا يجوز أن تساوي اسم الحساب."),
            "router_error": (QMessageBox.Critical, result.error or "تعذر تنفيذ العملية على الراوتر."),
        }
        icon, message = messages.get(result.code, (QMessageBox.Critical, "تعذر تغيير كلمة المرور."))
        box = QMessageBox(self)
        box.setWindowTitle("تغيير كلمة المرور")
        box.setIcon(icon)
        box.setText(message)
        box.exec()

    def _change_portal_group(self):
        if not self.c.router.connected:
            QMessageBox.information(self, "تغيير المجموعة", "اتصل بالراوتر أولاً.")
            return
        username = self._selected_portal_username()
        if not username:
            QMessageBox.information(self, "تغيير المجموعة", "اختر حسابًا من الجدول أولاً.")
            return
        groups = sorted(self.c.groups)
        if not groups:
            QMessageBox.warning(self, "تغيير المجموعة", "حدّث مجموعات الصلاحيات أولاً.")
            return
        current = (self.c.users.get(username) or {}).get("group", "")
        dialog = ChangePortalGroupDialog(username, groups, current, self)
        if dialog.exec() != QDialog.Accepted:
            return
        group = dialog.group.currentText().strip()
        if group == current:
            return
        self._run(lambda: self.c.change_portal_group(username, group),
                  lambda result: self._show_portal_group_result(result, username))

    def _show_portal_group_result(self, result, username):
        messages = {
            "group_changed": (QMessageBox.Information,
                              "تم تغيير المجموعة وفصل الجلسة الحالية للحساب."),
            "missing_group": (QMessageBox.Warning, "اختر مجموعة صلاحيات للحساب."),
            "not_confirmed": (QMessageBox.Critical,
                              "نُفذت الأوامر لكن تغيير المجموعة لم يثبت في إعداد الراوتر."),
            "router_error": (QMessageBox.Critical, result.error or "تعذر تنفيذ العملية على الراوتر."),
        }
        icon, message = messages.get(result.code, (QMessageBox.Critical, "تعذر إتمام العملية."))
        box = QMessageBox(self)
        box.setWindowTitle("تغيير المجموعة")
        box.setIcon(icon)
        box.setText(message)
        box.exec()
        if result.ok:
            self._select_portal_by_username(username)

    def _revoke_portal(self):
        if not self.c.router.connected:
            QMessageBox.information(self, "حذف الحساب", "اتصل بالراوتر أولاً.")
            return
        username = self._selected_portal_username()
        if not username:
            QMessageBox.information(self, "حذف الحساب", "اختر حسابًا من الجدول أولاً.")
            return
        dialog = RevokePortalDialog(username, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._run(lambda: self.c.revoke_portal(username, dialog.reason.text().strip()),
                  self._show_revoke_portal_result)

    def _show_revoke_portal_result(self, result):
        messages = {
            "revoked": (QMessageBox.Information, "تم حذف الحساب وحفظ سجل الإلغاء محلياً."),
            "not_confirmed": (QMessageBox.Critical,
                              "نُفذت الأوامر لكن حذف الحساب لم يثبت على الراوتر."),
            "router_error": (QMessageBox.Critical, result.error or "تعذر تنفيذ العملية على الراوتر."),
        }
        icon, message = messages.get(result.code, (QMessageBox.Critical, "تعذر حذف الحساب."))
        box = QMessageBox(self)
        box.setWindowTitle("حذف الحساب")
        box.setIcon(icon)
        box.setText(message)
        box.exec()

    def _selected_device_mac(self):
        table = self.tables.get("devices")
        if table is None or not table.selectionModel().hasSelection():
            return ""
        row = table.selectionModel().selectedRows()[0].row()
        item = table.item(row, 0)
        return item.text() if item else ""

    def _selected_portal_username(self):
        table = self.tables.get("portal")
        if table is None or not table.selectionModel().hasSelection():
            return ""
        row = table.selectionModel().selectedRows()[0].row()
        item = table.item(row, 0)
        return item.text() if item else ""

    def _edit_device_metadata(self):
        mac = self._selected_device_mac()
        if not mac:
            QMessageBox.information(self, "تعديل الجهاز", "اختر جهازًا من الجدول أولاً.")
            return
        local = self.c.db.device(legacy.normalize_mac(mac)) or {}
        dialog = EditDeviceDialog(local.get("name", ""), local.get("note", ""), self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._run(lambda: self.c.update_device_metadata(
            mac, dialog.name.text(), dialog.note.text()),
            lambda result: self._show_edit_result(result, mac))

    def _edit_portal_metadata(self):
        username = self._selected_portal_username()
        if not username:
            QMessageBox.information(self, "تعديل الحساب", "اختر حسابًا من الجدول أولاً.")
            return
        local = self.c.db.portal(username) or {}
        dialog = EditDeviceDialog(local.get("name", ""), local.get("note", ""), self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._run(lambda: self.c.update_portal_metadata(
            username, dialog.name.text(), dialog.note.text()),
            lambda result: self._show_portal_edit_result(result, username))

    def _change_device_group(self):
        if not self.c.router.connected:
            QMessageBox.information(self, "تغيير المجموعة", "اتصل بالراوتر أولاً.")
            return
        mac = self._selected_device_mac()
        if not mac:
            QMessageBox.information(self, "تغيير المجموعة", "اختر جهازًا من الجدول أولاً.")
            return
        groups = sorted(self.c.groups)
        if not groups:
            QMessageBox.warning(self, "تغيير المجموعة", "حدّث مجموعات الصلاحيات أولاً.")
            return
        current = (self.c.users.get(legacy.normalize_mac(mac)) or {}).get("group", "")
        dialog = ChangeDeviceGroupDialog(mac, groups, current, self)
        if dialog.exec() != QDialog.Accepted:
            return
        group = dialog.group.currentText().strip()
        if group == current:
            return
        self._run(lambda: self.c.change_device_group(mac, group),
                  lambda result: self._show_group_result(result, mac))

    def _show_group_result(self, result, mac):
        messages = {
            "group_changed": (QMessageBox.Information,
                              "تم تغيير المجموعة. قد يحتاج الجهاز دقيقة لإعادة الاتصال."),
            "bad_mac": (QMessageBox.Warning, "عنوان MAC المحدد غير صالح."),
            "missing_group": (QMessageBox.Warning, "اختر مجموعة صلاحيات للجهاز."),
            "not_confirmed": (QMessageBox.Critical,
                              "نُفذت الأوامر لكن تغيير المجموعة لم يثبت في إعداد الراوتر."),
            "router_error": (QMessageBox.Critical, result.error or "تعذر تنفيذ العملية على الراوتر."),
        }
        icon, message = messages.get(result.code, (QMessageBox.Critical, "تعذر إتمام العملية."))
        box = QMessageBox(self)
        box.setWindowTitle("تغيير المجموعة")
        box.setIcon(icon)
        box.setText(message)
        box.exec()
        if result.ok:
            self._select_device_by_mac(mac)

    def _revoke_device(self):
        if not self.c.router.connected:
            QMessageBox.information(self, "سحب الثقة", "اتصل بالراوتر أولاً.")
            return
        mac = self._selected_device_mac()
        if not mac:
            QMessageBox.information(self, "سحب الثقة", "اختر جهازًا من الجدول أولاً.")
            return
        dialog = RevokeDeviceDialog(mac, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._run(lambda: self.c.revoke_device(mac, dialog.reason.text().strip()),
                  self._show_revoke_result)

    def _show_revoke_result(self, result):
        messages = {
            "revoked": (QMessageBox.Information, "تم سحب الثقة وحفظ سجل الإلغاء محليًا."),
            "bad_mac": (QMessageBox.Warning, "عنوان MAC المحدد غير صالح."),
            "not_confirmed": (QMessageBox.Critical,
                              "نُفذت الأوامر لكن حذف الحساب لم يثبت على الراوتر."),
            "router_error": (QMessageBox.Critical, result.error or "تعذر تنفيذ العملية على الراوتر."),
        }
        icon, message = messages.get(result.code, (QMessageBox.Critical, "تعذر إتمام العملية."))
        box = QMessageBox(self)
        box.setWindowTitle("سحب الثقة")
        box.setIcon(icon)
        box.setText(message)
        box.exec()

    def _export_devices(self):
        default = "ar730_devices_%s.csv" % legacy.datetime.date.today()
        path, _ = QFileDialog.getSaveFileName(self, "تصدير الأجهزة الموثوقة", default,
                                              "CSV (*.csv)")
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        try:
            self.c.export_devices(path)
        except OSError as exc:
            QMessageBox.critical(self, "تصدير CSV", "تعذر كتابة الملف: %s" % exc)
            return
        QMessageBox.information(self, "تصدير CSV", "تم تصدير الأجهزة إلى:\n%s" % path)

    def _export_portal(self):
        default = "ar730_portal_%s.csv" % legacy.datetime.date.today()
        path, _ = QFileDialog.getSaveFileName(self, "تصدير حسابات البوابة", default,
                                              "CSV (*.csv)")
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        try:
            self.c.export_portal(path)
        except OSError as exc:
            QMessageBox.critical(self, "تصدير CSV", "تعذر كتابة الملف: %s" % exc)
            return
        QMessageBox.information(self, "تصدير CSV", "تم تصدير حسابات البوابة إلى:\n%s" % path)

    def _show_edit_result(self, result, mac):
        if not result.ok:
            QMessageBox.warning(self, "تعديل الجهاز", "تعذر حفظ التعديل.")
            return
        if result.code == "updated":
            self._select_device_by_mac(mac)

    def _show_portal_edit_result(self, result, username):
        if not result.ok:
            QMessageBox.warning(self, "تعديل الحساب", "تعذر حفظ التعديل.")
            return
        if result.code == "updated":
            self._select_portal_by_username(username)

    def _select_device_by_mac(self, mac):
        table = self.tables.get("devices")
        if table is None:
            return
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item and legacy.normalize_mac(item.text()) == legacy.normalize_mac(mac):
                table.selectRow(row)
                table.scrollToItem(item)
                return

    def _select_portal_by_username(self, username):
        table = self.tables.get("portal")
        if table is None:
            return
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item and item.text() == username:
                table.selectRow(row)
                table.scrollToItem(item)
                return

    def _select_vlan_by_mac(self, mac):
        table = self.tables.get("vlans")
        if table is None:
            return
        for row in range(table.rowCount()):
            item = table.item(row, 1)
            if item and legacy.normalize_mac(item.text()) == legacy.normalize_mac(mac):
                table.selectRow(row)
                table.scrollToItem(item)
                return

    def closeEvent(self, event):
        self._closing = True
        self.wan_timer.stop()
        self.firebase_timer.stop()
        if any(worker.isRunning() for worker in self.workers):
            # Preserve workers until their bounded requests finish. Unacknowledged
            # changes already live on disk and will resume on the next launch.
            event.ignore()
            QTimer.singleShot(100, self.close)
            return
        self.c.close()
        event.accept()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", "-d", action="store_true")
    parser.add_argument("--apply-update", nargs=2, metavar=("PARENT_PID", "PLAN"))
    args = parser.parse_args()
    if args.apply_update:
        parent_pid, plan = args.apply_update
        try:
            legacy.apply_windows_update(json.loads(plan), int(parent_pid))
        except Exception as exc:
            # This process has no GUI by design: it must be able to replace the
            # application's executable after the UI process exits.
            print("AR730 Manager update failed: %s" % exc, file=sys.stderr)
            return 1
        return 0
    app = QApplication(sys.argv)
    # يمنع وراثة عناصر Cocoa الداكنة داخل حوارات Qt في macOS.
    app.setStyle(QStyleFactory.create("Fusion"))
    app.setStyleSheet(STYLE)
    window = MainWindow(ReadController(args.demo), args.demo)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    sys.exit(main() or 0)
