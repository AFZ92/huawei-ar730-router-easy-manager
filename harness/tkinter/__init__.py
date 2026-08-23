# -*- coding: utf-8 -*-
"""
بديل tkinter للتشغيل بلا شاشة.

ليس مجرد كائن يبتلع كل شيء: الودجات الحاملة للبيانات (Treeview, Text,
StringVar, Notebook) تنفّذ سلوكها الحقيقي، فإن أخطأ البرنامج في استعمالها
ظهر الخطأ. أما توابع النوافذ (geometry, transient, grab_set) فتُبتلع لأنها
لا تعني شيئاً بلا مدير نوافذ.
"""

END = "end"
INSERT = "insert"
WM_METHODS = {
    "title", "maxsize", "resizable", "transient",
    "grab_set", "grab_release", "protocol", "iconbitmap", "option_add",
    "focus_set", "focus", "update", "update_idletasks", "attributes",
    "deiconify", "withdraw", "lift", "after", "after_cancel",
    "bind_all", "unbind", "state", "wm_state", "columnconfigure",
    "rowconfigure", "grid_columnconfigure", "grid_rowconfigure",
    "pack_propagate", "grid_propagate", "event_generate", "mainloop",
    "clipboard_clear", "clipboard_append", "tk_focusNext",
}
GEO_METHODS = {"place", "pack_forget", "grid_forget", "grid_remove"}

# ترتيب الرصف عالمياً — pack في Tk يوزّع المساحة بترتيب النداء، فترتيبه
# سلوك حقيقي لا تفصيلاً تجميلياً، ويجب أن يكون قابلاً للاختبار.
PACK_ORDER = []

# مقاس شاشة افتراضي للاختبارات؛ تستطيع تغييره لفحص الشاشات الصغيرة
SCREEN = [1920, 1080]


def reset_pack_order():
    del PACK_ORDER[:]


class Event(object):
    """حدث مبسّط: يحمل ما تحتاجه الرُقباء من خصائص (width, height, x, y...)."""
    def __init__(self, **kw):
        self.width = 0
        self.height = 0
        self.x = 0
        self.y = 0
        self.keysym = ""
        self.state = 0
        for k, v in kw.items():
            setattr(self, k, v)


class _Base(object):
    def __init__(self, master=None, **kw):
        self.master = master
        self.kw = dict(kw)
        self.children = []
        self.bindings = {}
        self.pack_kw = None
        self.pack_seq = None
        self.grid_kw = None
        self.geometry_spec = None
        self.minsize_wh = None
        self.req_w = 0
        self.req_h = 0
        self.destroyed = False
        if isinstance(master, _Base):
            master.children.append(self)

    # -- توابع النوافذ والتخطيط: لا أثر لها بلا شاشة --------------------------
    def __getattr__(self, name):
        if name in WM_METHODS or name in GEO_METHODS:
            def noop(*a, **k):
                return None
            return noop
        raise AttributeError(
            "%s has no attribute %r" % (type(self).__name__, name))

    # -- الرُقباء: نحفظها كي تستطيع الاختبارات إطلاق الأحداث ---------------
    def bind(self, sequence=None, func=None, add=None):
        if func is None:
            return ""
        self.bindings.setdefault(sequence, []).append(func)
        return "cb%d" % len(self.bindings[sequence])

    def event_generate(self, sequence, **kw):
        """يطلق رُقباء حدث ما بكائن حدث بسيط يحمل ما مُرّر من خصائص."""
        ev = Event(**kw)
        for func in self.bindings.get(sequence, []):
            func(ev)

    # -- المقاس: نسجّله ونسمح للاختبارات بضبط الأبعاد المطلوبة -----------
    def geometry(self, spec=None):
        if spec is not None:
            self.geometry_spec = spec
        return self.geometry_spec or ""

    def minsize(self, w=None, h=None):
        if w is not None:
            self.minsize_wh = (w, h)
        return self.minsize_wh or (0, 0)

    def winfo_reqwidth(self):
        return self.req_w

    def winfo_reqheight(self):
        return self.req_h

    def winfo_width(self):
        return self.req_w

    def winfo_height(self):
        return self.req_h

    def winfo_screenwidth(self):
        return SCREEN[0]

    def winfo_screenheight(self):
        return SCREEN[1]

    def winfo_rootx(self):
        return 0

    def winfo_rooty(self):
        return 0

    def winfo_exists(self):
        return not self.destroyed

    def pack(self, **kw):
        self.pack_kw = dict(kw)
        self.pack_seq = len(PACK_ORDER)
        PACK_ORDER.append(self)

    def grid(self, **kw):
        self.grid_kw = dict(kw)

    def configure(self, **kw):
        self.kw.update(kw)
    config = configure

    def cget(self, key):
        return self.kw.get(key)

    def __setitem__(self, k, v):
        self.kw[k] = v

    def __getitem__(self, k):
        return self.kw[k]

    def destroy(self):
        self.destroyed = True

    def winfo_rootx(self): return 0
    def winfo_rooty(self): return 0
    def winfo_width(self): return 1080
    def winfo_height(self): return 680
    def winfo_children(self): return list(self.children)
    def wait_window(self, w=None): return None


class Misc(_Base): pass
class Tk(_Base): pass
class Toplevel(_Base): pass
class Frame(_Base): pass
class Label(_Base): pass
class Button(_Base): pass
class Entry(_Base): pass
class Canvas(_Base): pass
class Menu(_Base):
    def add_command(self, **kw): pass
    def add_cascade(self, **kw): pass
    def add_separator(self, **kw): pass
class PhotoImage(_Base): pass


class Variable(object):
    """
    متغيّر برُقباء حقيقيين — لولا ذلك لما اختُبر أي سلوك معلّق على
    تغيّر القيمة، كالبحث الحيّ في الجداول.
    """
    def __init__(self, master=None, value=None, name=None):
        self._v = value if value is not None else self._default()
        self._traces = []

    def _default(self): return ""
    def get(self): return self._v

    def set(self, v):
        self._v = v
        self._fire()

    def _fire(self):
        for cb in list(self._traces):
            cb("", "", "write")

    def trace_add(self, mode, callback):
        self._traces.append(callback)
        return "trace%d" % len(self._traces)

    def trace_remove(self, mode, cbname):
        self._traces = []

    # الصيغة القديمة التي ما زالت شائعة
    def trace(self, mode, callback):
        return self.trace_add("write", callback)


class StringVar(Variable):
    def _default(self): return ""
    def set(self, v):
        self._v = "" if v is None else str(v)
        self._fire()


class IntVar(Variable):
    def _default(self): return 0
    def get(self): return int(self._v)


class BooleanVar(Variable):
    def _default(self): return False
    def get(self): return bool(self._v)


class Text(_Base):
    """نص حقيقي: يخزّن ما يُكتب فيه كي نتحقق من محتوى سجل الأوامر."""
    def __init__(self, master=None, **kw):
        _Base.__init__(self, master, **kw)
        self.buffer = ""
        self.tags = {}
        self.tag_ranges_ = {}

    def insert(self, index, chars, *tags):
        if index in ("end", END):
            self.buffer += chars
        else:
            self.buffer = chars + self.buffer

    def delete(self, first, last=None):
        self.buffer = ""

    def get(self, first="1.0", last=END):
        return self.buffer

    # -- الوسوم: نخزّن إعداداتها كي تتحقق الاختبارات من المحاذاة ----------
    def tag_configure(self, tag, **kw):
        self.tags.setdefault(tag, {}).update(kw)
    tag_config = tag_configure

    def tag_add(self, tag, first, last=None):
        self.tags.setdefault(tag, {})
        self.tag_ranges_.setdefault(tag, []).append((first, last))

    def tag_remove(self, tag, first, last=None):
        self.tag_ranges_.pop(tag, None)

    def tag_cget(self, tag, option):
        return self.tags.get(tag, {}).get(option)

    def tag_ranges(self, tag):
        return tuple(self.tag_ranges_.get(tag, []))

    def see(self, index): pass
    def yview(self, *a): pass
    def yview_moveto(self, *a): pass
