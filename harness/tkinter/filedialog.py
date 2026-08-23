# -*- coding: utf-8 -*-
"""
بديل tkinter.filedialog بلا شاشة.

المسار يؤخذ من المجلد المؤقت الخاص بالنظام لا من "/tmp" الثابت — فذاك
غير موجود على ويندوز وكان يُسقط فحص التصدير هناك وحده.
"""
import os
import tempfile

path = os.path.join(tempfile.gettempdir(), "ar730_export.csv")
calls = []


def asksaveasfilename(**k):
    calls.append(k)
    return path


def askopenfilename(**k):
    calls.append(k)
    return path


def reset(new_path=None):
    """يسمح للاختبار بتوجيه الحفظ إلى مسار آخر."""
    global path
    del calls[:]
    if new_path:
        path = new_path
    return path
