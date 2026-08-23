# -*- coding: utf-8 -*-
"""صناديق رسائل مبرمجة: تسجّل كل نداء، وتردّ بما نضعه في answers."""
calls = []
answers = []          # قائمة ردود askyesno بالترتيب
default_yes = True

def _rec(kind, title, message):
    calls.append((kind, title, message))

def showinfo(title, message, **k): _rec("info", title, message)
def showwarning(title, message, **k): _rec("warning", title, message)
def showerror(title, message, **k): _rec("error", title, message)

def askyesno(title, message, **k):
    _rec("askyesno", title, message)
    return answers.pop(0) if answers else default_yes

def askokcancel(title, message, **k): return askyesno(title, message)
def askretrycancel(title, message, **k): return False

def reset():
    del calls[:]
    del answers[:]

def errors():
    return [c for c in calls if c[0] == "error"]
