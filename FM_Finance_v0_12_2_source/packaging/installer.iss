#define AppVersion "0.12.2"
#define ProjectRoot SourcePath + ".."

[Setup]
AppId={{326E9BD9-8992-47CB-86EC-CB97536C5016}
AppName=F&M Finance
AppVersion={#AppVersion}
AppPublisher=F&M IT Services
VersionInfoVersion={#AppVersion}.0
VersionInfoDescription=F&M Finance Setup
DefaultDirName={localappdata}\Programs\FM Finance
DefaultGroupName=F&M Finance
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#ProjectRoot}\installer-output
OutputBaseFilename=FM_Finance_Setup_v{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableWelcomePage=no
DisableProgramGroupPage=yes
UninstallDisplayName=F&M Finance
AppMutex=Local\FMFinanceLauncher
CloseApplications=no
RestartApplications=no
SetupLogging=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#ProjectRoot}\dist\FMExpenseTracker\*"; DestDir: "{app}"; Excludes: ".env,logs\*,data\*,*.db,*.db-wal,*.db-shm"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ProjectRoot}\packaging\configure.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjectRoot}\packaging\launch.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\F&M Finance"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\launch.ps1"""; WorkingDir: "{app}"; IconFilename: "{app}\FMExpenseTracker.exe"
Name: "{userdesktop}\F&M Finance"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\launch.ps1"""; WorkingDir: "{app}"; IconFilename: "{app}\FMExpenseTracker.exe"; Tasks: desktopicon
Name: "{group}\Configure F&M Finance"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -STA -ExecutionPolicy Bypass -File ""{app}\configure.ps1"""; WorkingDir: "{app}"
Name: "{group}\Uninstall F&M Finance"; Filename: "{uninstallexe}"

[Run]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\launch.ps1"""; Description: "Configure and open F&M Finance"; Flags: postinstall nowait skipifsilent

[Code]
procedure InitializeWizard;
begin
  WizardForm.WelcomeLabel2.Caption :=
    'This wizard installs F&M Finance and creates shortcuts.' + #13#10#13#10 +
    'SQLite testing needs no database installation. PostgreSQL is optional; MinIO is required only for receipt uploads.' + #13#10#13#10 +
    'The first launch asks for database, receipt storage, and administrator settings. Python and Node.js are not required on the destination computer.' + #13#10#13#10 +
    'For an update, close the application and stop any NSSM service first. Existing configuration, logs, and financial data are preserved.';
end;

function InitializeUninstall: Boolean;
begin
  Result := UninstallSilent or
    (MsgBox('Close F&M Finance first. If you installed its NSSM service, remove that service with uninstall_service.bat before continuing.' + #13#10#13#10 +
      'Uninstall removes the application and shortcuts. Configuration, SQLite data, logs, PostgreSQL data and MinIO receipts are kept. Continue?',
      mbConfirmation, MB_YESNO) = IDYES);
end;
