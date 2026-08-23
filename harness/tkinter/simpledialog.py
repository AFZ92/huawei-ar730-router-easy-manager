# -*- coding: utf-8 -*-
"""askstring مبرمج: يسحب من قائمة replies بالترتيب."""
calls = []
replies = []

def askstring(title, prompt, **k):
    calls.append((title, prompt))
    return replies.pop(0) if replies else ""

def askinteger(title, prompt, **k):
    v = askstring(title, prompt)
    try: return int(v)
    except Exception: return None

def reset():
    del calls[:]
    del replies[:]
