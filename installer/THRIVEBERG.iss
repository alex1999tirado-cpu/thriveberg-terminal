#ifndef BetaVersion
  #define BetaVersion "020"
#endif
#ifndef AppVersion
  #define AppVersion "0.5.0"
#endif

#define AppName "THRIVEBERG Terminal"
#define AppExeName "THRIVEBERG_Terminal.exe"

[Setup]
AppId={{8EB67EF1-5EFC-4CC4-B012-03E46BBA2CF3}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} Beta {#BetaVersion}
AppPublisher=THRIVEBERG
DefaultDirName={localappdata}\Programs\THRIVEBERG Terminal
DefaultGroupName=THRIVEBERG Terminal
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\releases\BETA
OutputBaseFilename=THRIVEBERG-Terminal-BETA-{#BetaVersion}-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
SetupIconFile=..\ajax_terminal\assets\thriveberg.ico
ChangesAssociations=yes
CloseApplications=yes
RestartApplications=no
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
VersionInfoVersion={#AppVersion}.0
VersionInfoCompany=THRIVEBERG
VersionInfoDescription=THRIVEBERG Terminal installer
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\{#AppExeName}"
Type: files; Name: "{autodesktop}\THRIVEBERG Terminal - ULTIMA VERSION.lnk"

[Files]
Source: "..\dist\THRIVEBERG_Terminal\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: checkedonce

[Icons]
Name: "{group}\THRIVEBERG Terminal"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExeName}"; IconIndex: 0
Name: "{autodesktop}\THRIVEBERG Terminal"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExeName}"; IconIndex: 0; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch THRIVEBERG Terminal"; Flags: nowait postinstall skipifsilent

[Code]
function InstallMarkerPath(): String;
begin
  Result := ExpandConstant('{app}\.thriveberg-installing');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    ForceDirectories(ExpandConstant('{app}'));
    SaveStringToFile(InstallMarkerPath(), 'UPDATING' + #13#10, False);
  end
  else if CurStep = ssPostInstall then
    DeleteFile(InstallMarkerPath());
end;
