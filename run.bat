@echo off
REM  التشغيل الحقيقي — يحتاج  pip install paramiko
python ar730_manager.py
if errorlevel 1 pause
