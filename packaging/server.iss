[Setup]
AppName=Windows Screenshot Monitor Server
AppVersion=0.7
DefaultDirName={autopf}\Windows Screenshot Monitor\Server
DisableProgramGroupPage=yes
PrivilegesRequired=admin
OutputBaseFilename=ScreenshotServerSetup
UninstallDisplayIcon={app}\ScreenshotServer.exe

[Files]
Source: "..\dist\ScreenshotServer.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "server_install.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "server_uninstall.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Tasks]
Name: "deletedata"; Description: "Delete application data"; Flags: unchecked

[Code]
var
  StoragePage: TInputQueryWizardPage;

procedure InitializeWizard;
begin
  StoragePage := CreateInputQueryPage(wpWelcome, 'Storage', 'Storage Root', 'Existing screenshot data is not moved.');
  StoragePage.Add('Storage Root:', False);
  StoragePage.Values[0] := 'D:\ScreenshotServer';
end;

function StorageRoot(Param: String): String;
begin
  Result := StoragePage.Values[0];
end;

[Run]
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\server_install.ps1"" -StorageRoot ""{code:StorageRoot}"" -InstallPath ""{app}"""; Flags: runhidden

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\server_uninstall.ps1"""; Flags: runhidden; Tasks: not deletedata
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\server_uninstall.ps1"" -DeleteApplicationData"; Flags: runhidden; Tasks: deletedata
