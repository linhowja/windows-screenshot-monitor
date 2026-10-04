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
