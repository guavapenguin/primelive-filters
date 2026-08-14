# =============================================================================
#  Prime Stage 一鍵開播（Windows）— 全新電腦也能一路走到底
#   ① 缺 OBS / 濾鏡引擎 → 自動用 primelive 安裝檔靜默補裝(本地找不到就從雲端下載)
#   ② 第一次:選攝影機/麥克風 → 設定 OBS(問金鑰)
#   ③ 啟動濾鏡引擎(單排選擇器) → 等虛擬攝影機就緒 → 開 OBS
#  之後主播只要按「開始串流」→ 回平台「確認開播」。
# =============================================================================
[CmdletBinding()]
param(
    [string]$EnginePath = "",     # 引擎 exe;留空自動找
    [switch]$Fast,                # 引擎順暢模式(540p)
    [switch]$Setup                # 強制重跑 OBS 設定(例如換金鑰)
)
$ErrorActionPreference = "Continue"
Add-Type -AssemblyName System.Windows.Forms -ErrorAction SilentlyContinue
function Note($m){ Write-Host "[開播] $m" }
function Die($m){
    try { [System.Windows.Forms.MessageBox]::Show($m, "Prime Stage 開播", 'OK', 'Error') | Out-Null } catch {}
    Write-Host "[錯誤] $m"; exit 1
}

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallerUrl = "https://storage.googleapis.com/mail_use/primelive_filter_setup.exe"

function Find-Obs {
    @("$env:ProgramFiles\obs-studio\bin\64bit\obs64.exe",
      "${env:ProgramFiles(x86)}\obs-studio\bin\64bit\obs64.exe") |
      Where-Object { Test-Path $_ } | Select-Object -First 1
}
function Find-Engine {
    @($EnginePath,
      "$env:ProgramFiles\primelive-filter\primelive_filter.exe",
      "${env:ProgramFiles(x86)}\primelive-filter\primelive_filter.exe",
      (Join-Path $here "engine\primelive_filter.exe"),
      (Join-Path $here "engine\primelive_filter\primelive_filter.exe"),
      "F:\mcp\primelive\obs\engine\dist\primelive_filter\primelive_filter.exe"
    ) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}

# ---- ① 全新電腦:缺 OBS 或引擎 → 自動補裝(primelive 安裝檔=OBS+引擎一次裝好) ----
$obsExe = Find-Obs
$engineExe = Find-Engine
if (-not $obsExe -or -not $engineExe) {
    Note "偵測到第一次使用(缺 OBS 或濾鏡引擎),自動安裝中..."
    # 安裝檔:先找本地(跟 bat 同層/上層),沒有就從雲端下載
    $setupExe = @((Join-Path $here "primelive_filter_setup.exe"),
                  (Join-Path (Split-Path $here) "primelive_filter_setup.exe")) |
                Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $setupExe) {
        $setupExe = Join-Path $env:TEMP "primelive_filter_setup.exe"
        Note "下載安裝檔(約400MB,依網速需數分鐘,請勿關閉視窗)..."
        $curl = "$env:SystemRoot\System32\curl.exe"
        if (Test-Path $curl) {
            & $curl -L --retry 3 --connect-timeout 30 -o $setupExe $InstallerUrl
        } else {
            try { Start-BitsTransfer -Source $InstallerUrl -Destination $setupExe -ErrorAction Stop }
            catch { (New-Object Net.WebClient).DownloadFile($InstallerUrl, $setupExe) }
        }
        if (-not (Test-Path $setupExe) -or (Get-Item $setupExe).Length -lt 100MB) {
            Die "安裝檔下載失敗。請檢查網路後重試,或向小編索取安裝檔放到本資料夾再執行。"
        }
    }
    Note "安裝 OBS + 濾鏡引擎(會跳出權限視窗請按「是」;約 2~3 分鐘)..."
    try {
        $p = Start-Process -FilePath $setupExe -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART" -Verb RunAs -Wait -PassThru
        Note "安裝程式結束(代碼 $($p.ExitCode))。"
    } catch {
        Die "安裝被取消或失敗($($_.Exception.Message))。請重新執行並在權限視窗按「是」。"
    }
    $obsExe = Find-Obs; $engineExe = Find-Engine
    if (-not $obsExe)    { Die "OBS 安裝未完成,請重新執行本檔一次。" }
    if (-not $engineExe) { Die "濾鏡引擎安裝未完成,請重新執行本檔一次。" }
    Note "安裝完成。"
}

# ---- ② 首次設定(或 -Setup):選設備 → OBS 設定(問金鑰) ------------------------
$profDir = Join-Path (Join-Path $env:APPDATA "obs-studio") "basic\profiles\Prime Stage 直式"
if ($Setup -or -not (Test-Path $profDir)) {
    $picker = @((Join-Path $here "選設備.ps1"), (Join-Path $here "devices.ps1")) |
              Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($picker) { Note "第一次先選你的攝影機和麥克風..."; & $picker -EnginePath $engineExe }
    Note "設定 OBS(會問你的串流金鑰)..."
    $setup = Join-Path $here "setup.ps1"
    if (-not (Test-Path $setup)) { Die "找不到 setup.ps1(要和本檔放在一起)。" }
    & $setup -Camera primelive
}

# ---- ③ 啟動引擎 → 等虛擬攝影機 → 開 OBS -------------------------------------
$readyFlag = Join-Path $env:TEMP "primelive_ready.flag"
Remove-Item $readyFlag -Force -ErrorAction SilentlyContinue
$engineArgs = @("--ready-file", $readyFlag)
$devFile = Join-Path $env:APPDATA "PrimeStage\devices.json"
if (Test-Path $devFile) {
    try {
        $d = Get-Content $devFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($d.cameraName) { $engineArgs += @("--camera-name", "$($d.cameraName)"); Note "攝影機用你選的:$($d.cameraName)" }
    } catch {}
}
if ($Fast) { $engineArgs += "--fast" }

Note "啟動濾鏡引擎:$engineExe"
Start-Process -FilePath $engineExe -ArgumentList $engineArgs -WorkingDirectory (Split-Path -Parent $engineExe) | Out-Null

Note "等濾鏡引擎的虛擬攝影機就緒(最多 40 秒)..."
$ok = $false
for ($i = 0; $i -lt 80; $i++) {
    if (Test-Path $readyFlag) { $ok = $true; break }
    Start-Sleep -Milliseconds 500
}
if ($ok) { Note "引擎就緒。" } else { Note "等逾時,仍先開 OBS(引擎可能還在載入,稍等畫面就會出現)。" }

if (Get-Process obs64 -ErrorAction SilentlyContinue) {
    Note "OBS 已經開著。"
} else {
    Note "開啟 OBS..."
    Start-Process -FilePath $obsExe -WorkingDirectory (Split-Path -Parent $obsExe) | Out-Null
}
Note "完成。引擎視窗滾輪選濾鏡;OBS 按「開始串流」後回平台「確認開播」。"
