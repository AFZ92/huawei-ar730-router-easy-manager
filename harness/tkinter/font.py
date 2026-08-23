# -*- coding: utf-8 -*-
"""بديل tkinter.font بلا شاشة — يكفي لاختيار عائلة الخط."""

_FAMILIES = ("Helvetica", "Helvetica Neue", "Courier New", "Menlo")


def families(root=None, displayof=None):
    return list(_FAMILIES)


def nametofont(name):
    return Font()


class Font(object):
    def __init__(self, root=None, font=None, name=None, exists=False, **kw):
        self.kw = dict(kw)

    def configure(self, **kw):
        self.kw.update(kw)

    def cget(self, key):
        return self.kw.get(key)

    def actual(self, option=None):
        return self.kw if option is None else self.kw.get(option)

    def measure(self, text):
        return len(text) * 7

    def metrics(self, *a):
        return {"linespace": 16, "ascent": 12, "descent": 4}
