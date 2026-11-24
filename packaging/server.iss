[Setup]
AppName=Windows Screenshot Monitor Server
AppVersion=1.1
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DefaultDirName={autopf}\Windows Screenshot Monitor\Server
DisableProgramGroupPage=yes
PrivilegesRequired=admin
OutputBaseFilename=ScreenshotServerSetup-1.1
WizardStyle=modern
WizardSizePercent=150
UninstallDisplayIcon={app}\ScreenshotServer.exe

[Files]
Source: "..\dist\ScreenshotServer.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\ScreenshotServerConfig.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "server_install.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "server_uninstall.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Windows Screenshot Monitor\Screenshot Server Configuration"; Filename: "{app}\ScreenshotServerConfig.exe"; Comment: "Edit server settings. Restart Screenshot Server after saving."

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

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
  Params: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    Params := '-ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\server_uninstall.ps1') + '"';
    if MsgBox('Delete application data?' + #13#10 + #13#10 + 'This will delete Screenshot Monitor application data.' + #13#10 + 'This action cannot be undone.', mbConfirmation, MB_YESNO) = IDYES then
      Params := Params + ' -DeleteApplicationData';
    Exec('powershell.exe', Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;

[Run]
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\server_install.ps1"" -StorageRoot ""{code:StorageRoot}"" -InstallPath ""{app}"""; Flags: runhidden
