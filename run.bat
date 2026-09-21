@echo off
REM  التشغيل الحقيقي بواجهة Qt — يحتاج  pip install -r requirements.txt
python ar730_qt.py
if errorlevel 1 pause
