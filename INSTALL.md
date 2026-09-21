# تثبيت AR730 Manager

لا يلزم تثبيت Python أو مكتبات المشروع عند استخدام النسخ المنشورة.

## Windows x64

افتح **PowerShell** ثم الصق الأمر التالي:

```powershell
irm https://raw.githubusercontent.com/AFZ92/huawei-ar730-router-easy-manager/main/scripts/install.ps1 | iex
```

ينزّل الأمر مثبت Windows المناسب من أحدث GitHub Release، ويتحقق من SHA-256، ثم يفتح المثبت.
بعدها شغّل **AR730 Manager** من قائمة Start. لتحديث التطبيق لاحقاً، نفّذ الأمر نفسه.

## macOS (Apple Silicon أو Intel)

افتح **Terminal** ثم الصق الأمر التالي:

```bash
curl -fsSL https://raw.githubusercontent.com/AFZ92/huawei-ar730-router-easy-manager/main/scripts/install.sh | bash
```

يختار الأمر تلقائياً بناء Apple Silicon أو Intel، ويتحقق من SHA-256، ثم يثبت التطبيق في
`/Applications`. قد يطلب macOS كلمة مرور المدير. افتح **AR730 Manager** من Applications.

## التحديث والبيانات

يفحص التطبيق الإصدارات عند التشغيل ويعرض رقم الإصدار الجديد إذا كان متاحاً لجهازك. تبقى
الإعدادات وسجل الأوامر وبيانات الأجهزة خارج مجلد التطبيق، لذلك لا تُحذف عند التحديث.

يمكنك كذلك تنزيل الملفات يدوياً من [GitHub Releases](https://github.com/AFZ92/huawei-ar730-router-easy-manager/releases)،
لكن تحقّق من SHA-256 بمقارنته مع ملف `SHA256SUMS.txt` المنشور مع الإصدار.
