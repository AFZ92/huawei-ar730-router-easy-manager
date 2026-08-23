@echo off
REM  وضع التجربة — راوتر وهمي داخل البرنامج، لا اتصال بأي جهاز حقيقي
REM  اضغط (اتصال) بأي كلمة سر، وجرّب كل زر بلا خوف
python ar730_manager.py --demo
if errorlevel 1 pause
