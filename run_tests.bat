@echo off
REM  UTF-8 code page so the Arabic test output renders in the console
chcp 65001 >nul
python harness\run_qt_test.py
pause
