[Setup]
AppName=Windows Screenshot Monitor Client
AppVersion=0.7
DefaultDirName={autopf}\Windows Screenshot Monitor\Client
DisableProgramGroupPage=yes
OutputBaseFilename=ScreenshotClientSetup
UninstallDisplayIcon={app}\ScreenshotClient.exe

[Files]
Source: "..\dist\ScreenshotClient.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "client_install.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "client_uninstall.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Code]
var
  ServerIpPage: TInputQueryWizardPage;

procedure InitializeWizard;
begin
  ServerIpPage := CreateInputQueryPage(wpWelcome, 'Server', 'Server IPv4', 'Port is fixed at 55550.');
  ServerIpPage.Add('Server IPv4:', False);
  ServerIpPage.Values[0] := '192.168.1.10';
end;

function ServerIp(Param: String): String;
begin
  Result := ServerIpPage.Values[0];
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
  Params: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    Params := '-ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\client_uninstall.ps1') + '"';
    if MsgBox('Delete application data?' + #13#10 + #13#10 + 'This will delete Screenshot Monitor application data.' + #13#10 + 'This action cannot be undone.', mbConfirmation, MB_YESNO) = IDYES then
      Params := Params + ' -DeleteApplicationData';
    Exec('powershell.exe', Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;

[Run]
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\client_install.ps1"" -ServerIp ""{code:ServerIp}"" -InstallPath ""{app}"""; Flags: runhidden
