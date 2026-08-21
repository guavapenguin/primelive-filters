# =============================================================================
#  primelive 安裝前清理 — 把舊的 OBS / 引擎 / 卡住的殘骸徹底移除,讓新版乾淨裝
#  (保留主播的串流金鑰與設備選擇,不用重貼)。install 流程最前面先跑這支。
# =============================================================================
[CmdletBinding()]
param([switch]$KeepConfig)
$ErrorActionPreference = "Continue"
function Note($m){ Write-Host "[清理] $m" }

$pf   = $env:ProgramFiles
$pfx  = ${env:ProgramFiles(x86)}
$obsBases = @("$pf\obs-studio", "$pfx\obs-studio")

# ---- 0. 關掉會鎖住檔案的程序 ----
foreach ($n in @("obs64","primelive_filter","OBS")) {
    Get-Process $n -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Milliseconds 800

# ---- 1. 備份金鑰(存 PrimeStage 安全區,清 OBS 也不掉)----
$psDir = Join-Path $env:APPDATA "PrimeStage"
New-Item -ItemType Directory -Force -Path $psDir | Out-Null
if (-not $KeepConfig) {
    $svc = Join-Path $env:APPDATA "obs-studio\basic\profiles\Prime Stage 直式\service.json"
    if (Test-Path $svc) {
        try {
            $k = (Get-Content $svc -Raw -Encoding UTF8 | ConvertFrom-Json).settings.key
            if ($k) { Set-Content (Join-Path $psDir "saved_key.txt") -Value $k -Encoding Ascii -NoNewline; Note "已備份串流金鑰" }
        } catch {}
    }
}

# ---- 2. 只清「壞掉的」OBS(資料夾在但 obs64.exe 不見=半殘);健康的 OBS 留著不動 ----
#    (盲目重裝健康 OBS 會在相機被佔用時把它弄壞,反而製造問題)
foreach ($base in $obsBases) {
    if (-not (Test-Path $base)) { continue }
    $healthy = Test-Path (Join-Path $base "bin\64bit\obs64.exe")
    if ($healthy) { Note "OBS 正常,保留不動。"; continue }

    Note "偵測到半殘 OBS,徹底清除..."
    # 2a. 反註冊卡住的虛擬相機 DLL
    foreach ($dll in @("$base\data\obs-plugins\win-dshow\obs-virtualcam-module64.dll",
                       "$base\data\obs-plugins\win-dshow\obs-virtualcam-module32.dll")) {
        if (Test-Path $dll) { Start-Process "regsvr32.exe" -ArgumentList @("/u","/s",$dll) -Wait -ErrorAction SilentlyContinue }
    }
    Start-Sleep -Milliseconds 500
    # 2b. 反安裝器(若還在)
    $uninst = Join-Path $base "uninstall.exe"
    if (Test-Path $uninst) { try { Start-Process $uninst -ArgumentList "/S" -Wait -ErrorAction Stop } catch {}; Start-Sleep 2 }
    # 2c. 砍資料夾;被鎖的檔逐一試刪,刪不掉就排進重開機刪除
    if (Test-Path $base) {
        try {
            [System.IO.Directory]::Delete($base, $true)
        } catch {
            Get-ChildItem $base -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
                try { Remove-Item $_.FullName -Force -ErrorAction Stop } catch {}
            }
            try { [System.IO.Directory]::Delete($base, $true) } catch { Note "部分檔案被鎖,需重開機後再裝一次" }
        }
    }
}

# ---- 4.(不動引擎)----
#  引擎由 installer [Files] ignoreversion 覆蓋更新,不需先移除。
#  先移除反而會在「重灌失敗時」害引擎消失→「引擎安裝未完成」,故不清引擎。

Note "清理完成。"
