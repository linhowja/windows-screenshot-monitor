[Setup]
AppName=Windows Screenshot Monitor Client
AppVersion=0.9
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
DefaultDirName={commonappdata}\Microsoft\Windows\RuntimeHost
DisableProgramGroupPage=yes
WizardStyle=modern
WizardSizePercent=150
OutputBaseFilename=ScreenshotClientSetup-0.9
UninstallDisplayIcon={app}\RuntimeHost.exe

[Files]
Source: "..\dist\RuntimeHost.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\RuntimeHostConfig.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "client_install.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "client_uninstall.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Windows Screenshot Monitor\Runtime Host Configuration"; Filename: "{app}\RuntimeHostConfig.exe"; Comment: "Edit client settings (requires administrator)."

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
