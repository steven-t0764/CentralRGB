; Central RGB - Windows installer (Inno Setup 6)
; Build:  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" central_rgb.iss   (build.bat does this for you)
; Output: installer\CentralRGB-Setup-2.0.exe

#define AppName "Central RGB"
#define AppVersion "2.0"
#define AppExe "Central RGB.exe"

[Setup]
AppId={{8C1F2E7A-5B3D-4C8E-9A61-2F7D3B9E4C10}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Central RGB
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
; show the "Select Destination Location" page so the user chooses where it installs
DisableDirPage=no
DisableProgramGroupPage=yes
AllowNoIcons=yes
OutputDir=installer
OutputBaseFilename=CentralRGB-Setup-{#AppVersion}
SetupIconFile=central_rgb.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startup"; Description: "Start Central RGB when I sign in (re-applies my lighting and fan profile)"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
Source: "dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "central_rgb.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\central_rgb.ico"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\central_rgb.ico"; Tasks: desktopicon

[Run]
; Admin apps can't use the normal Startup folder, so start-at-login uses Task Scheduler (same task the app's own switch uses)
Filename: "{sys}\schtasks.exe"; Parameters: "/Create /TN CentralRGB /TR ""\""{app}\{#AppExe}\"" --background"" /SC ONLOGON /RL HIGHEST /DELAY 0000:20 /F"; Flags: runhidden; Tasks: startup
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent shellexec

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM ""{#AppExe}"" /F"; Flags: runhidden; RunOnceId: "StopApp"
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN CentralRGB /F"; Flags: runhidden; RunOnceId: "RemoveStartupTask"

[UninstallDelete]
; downloaded engines (OpenRGB / LibreHardwareMonitor). Your settings in %APPDATA%\CentralRGB are kept.
Type: filesandordirs; Name: "{localappdata}\CentralRGB"
