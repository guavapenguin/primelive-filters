; primelive 一鍵濾鏡 — Windows 完整安裝檔（含 OBS）
; 編譯：ISCC.exe primelive.iss（或跑 build_installer.ps1）
[Setup]
AppName=primelive 一鍵濾鏡
AppVersion=1.0
AppPublisher=primelive
DefaultDirName={autopf}\primelive-filter
DefaultGroupName=primelive 一鍵濾鏡
DisableProgramGroupPage=yes
DisableDirPage=auto
OutputDir=f:\mcp\primelive\obs\installer\out
OutputBaseFilename=primelive_filter_setup
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
WizardStyle=modern

[Languages]
Name: "default"; MessagesFile: "compiler:Default.isl"

[Files]
; 濾鏡引擎（整個 dist：exe + 模型 + 設定 + 素材）
Source: "f:\mcp\primelive\obs\engine\dist\primelive_filter\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; Prime Stage 一鍵開播流程（選設備/金鑰/OBS 設定/開引擎+OBS）
Source: "f:\mcp\primelive\obs\installer\primestage\golive.ps1"; DestDir: "{app}\primestage"; Flags: ignoreversion
Source: "f:\mcp\primelive\obs\installer\primestage\devices.ps1"; DestDir: "{app}\primestage"; Flags: ignoreversion
Source: "f:\mcp\primelive\obs\installer\primestage\setup.ps1"; DestDir: "{app}\primestage"; Flags: ignoreversion
Source: "f:\mcp\primelive\obs\installer\primestage\cleanup_old.ps1"; DestDir: "{app}\primestage"; Flags: ignoreversion
; 使用說明
Source: "f:\mcp\primelive\obs\installer\使用說明.txt"; DestDir: "{app}"; Flags: ignoreversion
; OBS 安裝檔（含虛擬攝影機；裝完自動刪）
Source: "f:\mcp\primelive\obs\installer\OBS-Studio-Installer.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
; 桌面只留一顆:一鍵開播(首次自動跑 選設備→金鑰→OBS設定,之後直接開引擎+OBS)
Name: "{commondesktop}\primelive 一鍵開播"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File ""{app}\primestage\golive.ps1"""; IconFilename: "{app}\primelive_filter.exe"; Comment: "primelive 一鍵開播"
Name: "{group}\primelive 一鍵開播"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File ""{app}\primestage\golive.ps1"""; IconFilename: "{app}\primelive_filter.exe"
Name: "{group}\重新選攝影機麥克風"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File ""{app}\primestage\devices.ps1"""
Name: "{group}\使用說明"; Filename: "{app}\使用說明.txt"
Name: "{group}\移除 primelive 濾鏡"; Filename: "{uninstallexe}"

[Run]
; ① 先徹底清除舊的 OBS/引擎殘骸(卡住的虛擬相機 DLL、半殘資料夾),保留金鑰/設備
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\primestage\cleanup_old.ps1"""; StatusMsg: "正在清除舊版殘骸…"; Flags: waituntilterminated runhidden
; ② 靜默安裝 OBS（僅在缺 OBS 時；健康的 OBS 不重裝，避免相機被佔用時弄壞）
Filename: "{tmp}\OBS-Studio-Installer.exe"; Parameters: "/S"; StatusMsg: "正在安裝 OBS（含虛擬攝影機，請稍候約 1 分鐘）…"; Flags: waituntilterminated; Check: NeedInstallObs
; 裝完直接進入一鍵開播（首次會問攝影機/麥克風與串流金鑰）
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File ""{app}\primestage\golive.ps1"""; Description: "立即開播（第一次會先選設備、貼串流金鑰）"; Flags: postinstall nowait skipifsilent

[Code]
// 完整的 OBS = obs64.exe 且 en-US.ini(資料夾完整)都在。
// 只驗 obs64.exe 會漏掉「exe 在但 data/locale 不齊」的半殘裝→開 OBS 報「找不到 en-US.ini」。
function ObsHealthy(base: String): Boolean;
begin
  Result := FileExists(base + '\bin\64bit\obs64.exe')
        and FileExists(base + '\data\obs-studio\locale\en-US.ini');
end;

// 需要裝 OBS = 兩個路徑都沒有「完整」的 OBS(半殘也算沒有→cleanup 已先清掉,這裡補裝)
function NeedInstallObs(): Boolean;
begin
  Result := (not ObsHealthy(ExpandConstant('{commonpf}\obs-studio')))
        and (not ObsHealthy(ExpandConstant('{commonpf32}\obs-studio')));
end;
