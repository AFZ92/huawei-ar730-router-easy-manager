; Inno Setup installer. App data never lives below {app}, so an upgrade cannot erase it.
#define AppName "Huawei AR730 Router Easy Manager"
#define AppVersion GetEnv('AR730_VERSION')
#if AppVersion == ""
  #define AppVersion "1.0.0"
#endif
#ifndef SourceExe
  #define SourceExe "..\\..\\dist\\AR730Manager-Windows-x64.exe"
#endif

[Setup]
AppId={{43E74882-35E5-4F65-89A7-0BA02DCB9CB6}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=AFZ Systems
DefaultDirName={autopf}\AR730 Manager
DefaultGroupName=AR730 Manager
DisableProgramGroupPage=yes
OutputBaseFilename=AR730Manager-Windows-x64-Setup
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\AR730Manager.exe

[Files]
Source: "{#SourceExe}"; DestDir: "{app}"; DestName: "AR730Manager.exe"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\AR730 Manager"; Filename: "{app}\AR730Manager.exe"
Name: "{autodesktop}\AR730 Manager"; Filename: "{app}\AR730Manager.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\AR730Manager.exe"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
