[Setup]
AppName=Windows Screenshot Monitor Client
AppVersion=1.2
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
DefaultDirName={commonappdata}\Microsoft\Windows\RuntimeHost
DisableProgramGroupPage=yes
WizardStyle=modern
WizardSizePercent=150
OutputBaseFilename=ScreenshotClientSetup-1.2
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
  ServerIpPage.Values[0] := '172.16.0.200';
end;

function ServerIp(Param: String): String;
begin
  Result := Trim(ServerIpPage.Values[0]);
end;

function IsValidIPv4(const Ip: String): Boolean;
var
  S, Part: String;
  DotCount, I, N: Integer;
begin
  Result := False;
  S := Trim(Ip);
  if S = '' then Exit;
  DotCount := 0;
  Part := '';
  for I := 1 to Length(S) do
  begin
    if S[I] = '.' then
    begin
      if (Part = '') or (Length(Part) > 3) then Exit;
      N := StrToIntDef(Part, -1);
      if (N < 0) or (N > 255) then Exit;
      Inc(DotCount);
      Part := '';
    end
    else if (S[I] < '0') or (S[I] > '9') then
      Exit
    else
      Part := Part + S[I];
  end;
  if (Part = '') or (Length(Part) > 3) then Exit;
  N := StrToIntDef(Part, -1);
  if (N < 0) or (N > 255) then Exit;
  Result := (DotCount = 3);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = ServerIpPage.ID then
  begin
    if not IsValidIPv4(ServerIpPage.Values[0]) then
    begin
      MsgBox('Please enter a valid IPv4 address, for example 172.16.0.200.', mbError, MB_OK);
      Result := False;
    end;
  end;
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
