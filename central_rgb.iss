; Central RGB - Windows installer (Inno Setup 6.1+)
; Copyright (C) 2026 steven-t0764 - GPL-3.0-or-later
; Build:  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" central_rgb.iss   (build.bat does this for you)
; Output: installer\CentralRGB-Setup.exe
;
; If the PawnIO driver isn't installed yet, setup offers to install it. The official, signed PawnIO
; installer is downloaded from the link on pawnio.eu while setup runs - it is not bundled here.

#define AppName "Central RGB"
; release builds pass the tag version with /DAppVersion=...; this is the default for local builds
#ifndef AppVersion
  #define AppVersion "2.4.0"
#endif
#define AppExe "Central RGB.exe"
#define PawnIOUrl "https://github.com/namazso/PawnIO.Setup/releases/latest/download/PawnIO_setup.exe"

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
OutputBaseFilename=CentralRGB-Setup
SetupIconFile=central_rgb.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
; show the GPL-3.0 license page during setup
LicenseFile=LICENSE
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=admin
; Windows 10 version 1803 or newer, on a real 64-bit Intel/AMD PC. ARM PCs are blocked: they can run the app
; under emulation, but it can't reach RGB or fan hardware there.
MinVersion=10.0.17134
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
CloseApplications=yes

[Tasks]
Name: "pawnio"; Description: "Install the PawnIO driver (recommended - needed for RGB RAM, fan control and temperature sensors; downloaded from pawnio.eu)"; GroupDescription: "Driver:"; Check: PawnIOMissing
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startup"; Description: "Start Central RGB when I sign in (re-applies my lighting and fan profile)"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
; folder build: starts without unpacking itself on every launch
Source: "dist_app\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "central_rgb.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\central_rgb.ico"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\central_rgb.ico"; Tasks: desktopicon

[Run]
; Admin apps can't use the normal Startup folder, so start-at-login uses Task Scheduler (same task the app's own switch uses)
Filename: "{sys}\schtasks.exe"; Parameters: "/Create /TN CentralRGB /TR ""\""{app}\{#AppExe}\"" --background"" /SC ONLOGON /RL HIGHEST /DELAY 0000:20 /F"; Flags: runhidden; Tasks: startup
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent shellexec; Check: not RestartNeeded

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM ""{#AppExe}"" /F"; Flags: runhidden; RunOnceId: "StopApp"
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN CentralRGB /F"; Flags: runhidden; RunOnceId: "RemoveStartupTask"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
; downloaded engines (OpenRGB / LibreHardwareMonitor). Your settings in %APPDATA%\CentralRGB are kept.
; PawnIO is left installed on purpose: other apps (OpenRGB, FanControl, LibreHardwareMonitor...) use it too.
Type: filesandordirs; Name: "{localappdata}\CentralRGB"

[Messages]
WindowsVersionNotSupported=Central RGB needs Windows 10 (version 1803 or newer) or Windows 11.
OnlyOnTheseArchitectures=Central RGB needs a 64-bit Windows PC with an Intel or AMD processor.%n%nARM-based PCs (such as some Surface and Snapdragon laptops) aren't supported, because the app can't reach RGB or fan hardware on them.

[Code]
var
  DownloadPage: TDownloadWizardPage;
  PawnIOReady: Boolean;
  NeedsReboot: Boolean;

function PawnIOMissing: Boolean;
begin
  { the PawnIO driver registers a Windows service called PawnIO }
  Result := not RegKeyExists(HKLM, 'SYSTEM\CurrentControlSet\Services\PawnIO');
end;

function RestartNeeded: Boolean;
begin
  Result := NeedsReboot;
end;

function NeedRestart: Boolean;
begin
  Result := NeedsReboot;
end;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage('Downloading the PawnIO driver',
    'Getting the official PawnIO installer from pawnio.eu...', nil);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpReady) and WizardIsTaskSelected('pawnio') then
  begin
    DownloadPage.Clear;
    DownloadPage.Add('{#PawnIOUrl}', 'PawnIO_setup.exe', '');
    DownloadPage.Show;
    try
      try
        DownloadPage.Download;
        PawnIOReady := True;
      except
        PawnIOReady := False;
        if not DownloadPage.AbortedByUser then
          SuppressibleMsgBox('The PawnIO driver could not be downloaded:' + #13#10 + GetExceptionMessage + #13#10#13#10 +
            'Central RGB will still be installed. You can install PawnIO later from https://pawnio.eu',
            mbInformation, MB_OK, IDOK);
      end;
    finally
      DownloadPage.Hide;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if (CurStep = ssPostInstall) and PawnIOReady then
  begin
    WizardForm.StatusLabel.Caption := 'Installing the PawnIO driver...';
    if Exec(ExpandConstant('{tmp}\PawnIO_setup.exe'), '-install -silent', '', SW_HIDE,
            ewWaitUntilTerminated, ResultCode) then
    begin
      if ResultCode = 3010 then
        NeedsReboot := True
      else if ResultCode <> 0 then
        SuppressibleMsgBox('The PawnIO installer finished with code ' + IntToStr(ResultCode) + '.' + #13#10 +
          'If RGB RAM or fan control does not work, install PawnIO manually from https://pawnio.eu',
          mbInformation, MB_OK, IDOK);
    end
    else
      SuppressibleMsgBox('The PawnIO installer could not be started: ' + SysErrorMessage(ResultCode),
        mbInformation, MB_OK, IDOK);
  end;
end;
