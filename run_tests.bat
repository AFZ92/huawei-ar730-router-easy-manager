@echo off
REM  تشغيل الفحوصات الآلية (٧٤ فحصاً) بلا شاشة وبلا راوتر
python harness\run_test.py
python harness\run_demo_test.py
pause
