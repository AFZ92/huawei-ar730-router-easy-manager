@echo off
REM ===================================================================
REM  بناء AR730Manager.exe  —  شغّل هذا الملف على ويندوز مرة واحدة
REM ===================================================================
echo.
echo [1/3] تثبيت المتطلبات...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto fail

echo.
echo [2/3] بناء الملف التنفيذي...
python -m PyInstaller --onefile --windowed --name AR730Manager --clean ar730_qt.py
if errorlevel 1 goto fail

echo.
echo [3/3] تم.  الملف جاهز في:  dist\AR730Manager.exe
echo انسخ الملف وحده الى اي مجلد — سينشئ ملفات الاعدادات وقاعدة البيانات بجانبه.
pause
exit /b 0

:fail
echo.
echo فشل البناء. تأكد من تثبيت Python 3.9 او احدث مع خيار "Add python.exe to PATH".
pause
exit /b 1
