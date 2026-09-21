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
python build\create_app_icons.py
if errorlevel 1 goto fail
python -m PyInstaller --onefile --windowed --icon build\icons\afz-logo.ico --name AR730Manager --add-data "data;data" --add-data "assets;assets" --clean ar730_qt.py
if errorlevel 1 goto fail

echo.
echo [3/3] تم.  الملف جاهز في:  dist\AR730Manager.exe
echo تحفظ البيانات في %%APPDATA%%\AFZ Systems\AR730 Manager ولا يمسها التحديث.
pause
exit /b 0

:fail
echo.
echo فشل البناء. تأكد من تثبيت Python 3.9 او احدث مع خيار "Add python.exe to PATH".
pause
exit /b 1
