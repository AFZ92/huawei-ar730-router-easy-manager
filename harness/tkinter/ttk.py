# -*- coding: utf-8 -*-
"""ودجات ttk — Treeview و Notebook ينفّذان سلوكهما الحقيقي."""
from tkinter import _Base


class Frame(_Base): pass
class Label(_Base): pass
class Button(_Base): pass
class Entry(_Base): pass
class Checkbutton(_Base): pass
class Radiobutton(_Base): pass
class Separator(_Base): pass
class Scrollbar(_Base):
    def set(self, *a): pass
class LabelFrame(_Base): pass
Labelframe = LabelFrame
class PanedWindow(_Base): pass


class Progressbar(_Base):
    def start(self, ms=50): self.kw["_running"] = True
    def stop(self): self.kw["_running"] = False


class Combobox(_Base):
    def __init__(self, master=None, **kw):
        _Base.__init__(self, master, **kw)
        self.values = list(kw.get("values", []))
    def set(self, v): self.kw["value"] = v
    def get(self): return self.kw.get("value", "")
    def current(self, i=None): return 0


class Style(_Base):
    def __init__(self, master=None):
        _Base.__init__(self, master)
        self.styles = {}
    def theme_use(self, name=None): return "clam"
    def configure(self, style, **kw): self.styles.setdefault(style, {}).update(kw)
    def map(self, style, **kw): pass
    def lookup(self, *a, **k): return ""


class Notebook(_Base):
    def __init__(self, master=None, **kw):
        _Base.__init__(self, master, **kw)
        self.tabs_ = []
    def add(self, child, **kw):
        self.tabs_.append((child, kw.get("text", "")))
    def select(self, tab=None): return self.tabs_[0][0] if self.tabs_ else None
    def index(self, x=None): return 0
    def tab(self, i, **kw): return {}


class Treeview(_Base):
    """
    جدول حقيقي: يحفظ الصفوف بمعرّفاتها وقيمها ووسومها، ويرفض حذف صف
    غير موجود — تماماً كـ Tk — كي ينكشف أي خطأ في إدارة الصفوف.
    """

    def __init__(self, master=None, **kw):
        _Base.__init__(self, master, **kw)
        self.columns = tuple(kw.get("columns", ()))
        self.items = {}          # iid -> {"values":[], "tags":()}
        self.order = []
        self._selection = ()
        self.headings = {}
        self.columns_opts = {}
        self.tags = {}
        self._auto = 0

    def heading(self, col, **kw):
        # نحفظ كل الخيارات لا النص وحده، كي تتحقق الاختبارات من المحاذاة
        if kw:
            self.headings.setdefault(col, {}).update(kw)
        return dict(self.headings.get(col, {}))

    def column(self, col, **kw):
        if kw:
            self.columns_opts.setdefault(col, {}).update(kw)
        return dict(self.columns_opts.get(col, {}))

    def tag_configure(self, tag, **kw): self.tags[tag] = kw

    def insert(self, parent, index, iid=None, **kw):
        if iid is None:
            self._auto += 1
            iid = "I%03d" % self._auto
        if iid in self.items:
            raise ValueError("Item %s already exists" % iid)
        self.items[iid] = {
            "values": list(kw.get("values", ())),
            "tags": tuple(kw.get("tags", ())),
        }
        self.order.append(iid)
        return iid

    def delete(self, *iids):
        for iid in iids:
            if iid not in self.items:
                raise ValueError("Item %s not found" % iid)
            del self.items[iid]
            self.order.remove(iid)
            self._selection = tuple(x for x in self._selection if x != iid)

    def get_children(self, item=""):
        return tuple(self.order)

    def exists(self, iid): return iid in self.items

    def item(self, iid, option=None, **kw):
        rec = self.items[iid]
        if kw:
            if "values" in kw: rec["values"] = list(kw["values"])
            if "tags" in kw: rec["tags"] = tuple(kw["tags"])
            return None
        if option in ("values", "-values"): return rec["values"]
        if option in ("tags", "-tags"): return rec["tags"]
        return dict(rec)

    def set(self, iid, column=None, value=None):
        rec = self.items[iid]
        idx = self.columns.index(column)
        if value is None:
            return rec["values"][idx]
        rec["values"][idx] = value

    def selection(self): return tuple(self._selection)

    def selection_set(self, *iids):
        flat = []
        for i in iids:
            flat.extend(i if isinstance(i, (list, tuple)) else [i])
        for i in flat:
            if i not in self.items:
                raise ValueError("Item %s not found" % i)
        self._selection = tuple(flat)

    def focus(self, iid=None):
        if iid is None:
            return self._selection[0] if self._selection else ""
        self._selection = (iid,)

    def see(self, iid): pass
    def yview(self, *a): pass
    def identify_row(self, y): return ""
