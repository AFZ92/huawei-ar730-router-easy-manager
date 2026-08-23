# -*- coding: utf-8 -*-
path = "/tmp/ar730_export.csv"
calls = []

def asksaveasfilename(**k):
    calls.append(k)
    return path

def askopenfilename(**k):
    calls.append(k)
    return path
