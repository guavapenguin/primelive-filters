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

# 置頂小視窗進度回饋(主控台隱藏後,長時間作業給使用者「有在動」的訊息)
$script:progressFlag = $null
function Show-Progress($text) {
    Hide-Progress
    $script:progressFlag = Join-Path $env:TEMP ("primestage_busy_" + [guid]::NewGuid().ToString("N") + ".flag")
    New-Item -ItemType File -Path $script:progressFlag -Force | Out-Null
    $code = @"
Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing
`$f = New-Object System.Windows.Forms.Form
`$f.FormBorderStyle='None'; `$f.TopMost=`$true; `$f.StartPosition='CenterScreen'
`$f.Size = New-Object System.Drawing.Size(420, 90)
`$f.BackColor = [System.Drawing.Color]::FromArgb(22,18,27)
`$l = New-Object System.Windows.Forms.Label
`$l.Text = '$text'
`$l.ForeColor = [System.Drawing.Color]::FromArgb(246,243,240)
`$l.Font = New-Object System.Drawing.Font('Microsoft JhengHei UI', 11)
`$l.Dock = 'Fill'; `$l.TextAlign = 'MiddleCenter'
`$f.Controls.Add(`$l)
`$t = New-Object System.Windows.Forms.Timer; `$t.Interval = 400
`$t.Add_Tick({ if (-not (Test-Path '$($script:progressFlag)')) { `$f.Close() } })
`$t.Start(); [void]`$f.ShowDialog()
"@
    $enc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($code))
    Start-Process powershell -ArgumentList "-NoProfile","-WindowStyle","Hidden","-EncodedCommand",$enc | Out-Null
}
function Hide-Progress {
    if ($script:progressFlag) {
        Remove-Item $script:progressFlag -Force -ErrorAction SilentlyContinue
        $script:progressFlag = $null
    }
}

function Find-Obs {
    @("$env:ProgramFiles\obs-studio\bin\64bit\obs64.exe",
      "${env:ProgramFiles(x86)}\obs-studio\bin\64bit\obs64.exe") |
      Where-Object { Test-Path $_ } | Select-Object -First 1
}
function Find-Engine {
    @($EnginePath,
      (Join-Path (Split-Path $here) "primelive_filter.exe"),   # 安裝目錄相對(裝哪都對,最優先)
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
        Note "下載安裝檔(約400MB)..."
        Show-Progress "正在下載直播環境安裝檔(約 400MB)，請稍候…"
        $curl = "$env:SystemRoot\System32\curl.exe"
        if (Test-Path $curl) {
            & $curl -sL --retry 3 --connect-timeout 30 -o $setupExe $InstallerUrl
        } else {
            try { Start-BitsTransfer -Source $InstallerUrl -Destination $setupExe -ErrorAction Stop }
            catch { (New-Object Net.WebClient).DownloadFile($InstallerUrl, $setupExe) }
        }
        Hide-Progress
        if (-not (Test-Path $setupExe) -or (Get-Item $setupExe).Length -lt 100MB) {
            Die "安裝檔下載失敗。請檢查網路後重試,或向小編索取安裝檔放到本資料夾再執行。"
        }
    }
    # 先徹底清除舊 OBS/引擎殘骸(卡住的虛擬相機 DLL 會擋住 OBS 重裝)
    $cleanup = Join-Path $here "cleanup_old.ps1"
    if (Test-Path $cleanup) {
        Note "清除舊版殘骸(保留你的金鑰與設備)..."
        try { & $cleanup } catch {}
    }
    Note "安裝 OBS + 濾鏡引擎..."
    Show-Progress "正在安裝 OBS 與濾鏡引擎(約 2~3 分鐘)，權限視窗請按「是」…"
    try {
        $p = Start-Process -FilePath $setupExe -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART" -Verb RunAs -Wait -PassThru
        Note "安裝程式結束(代碼 $($p.ExitCode))。"
    } catch {
        Hide-Progress
        Die "安裝被取消或失敗($($_.Exception.Message))。請重新執行並在權限視窗按「是」。"
    }
    Hide-Progress
    $obsExe = Find-Obs; $engineExe = Find-Engine
    if (-not $obsExe) {
        # 多半是舊 OBS 檔案被鎖住、需重開機才能清乾淨 → 明確引導,別讓主播無限重試
        Die "OBS 需要重新開機才能完成安裝。`n`n請「重新開機」後,再點一次桌面的『primelive 一鍵開播』即可。"
    }
    if (-not $engineExe) { Die "濾鏡引擎安裝未完成,請重新開機後再點一次桌面捷徑。" }
    Note "安裝完成。"
}

# ---- ②' 升級刷新:設定版本落後→用新版模板重寫 OBS 設定(保留金鑰+設備,主播無感)----
$CONFIG_VER = "11"
$verFile = Join-Path $env:APPDATA "PrimeStage\config_ver.txt"
$curVer = ""
if (Test-Path $verFile) { $curVer = (Get-Content $verFile -Raw -ErrorAction SilentlyContinue).Trim() }
$profDir = Join-Path (Join-Path $env:APPDATA "obs-studio") "basic\profiles\Prime Stage 直式"
if ((Test-Path $profDir) -and ($curVer -ne $CONFIG_VER) -and -not $Setup) {
    Note "偵測到升級(設定版本 $curVer → $CONFIG_VER),自動刷新 OBS 設定(保留你的金鑰與設備)..."
    $obsSetupPs = Join-Path $here "setup.ps1"
    if (Test-Path $obsSetupPs) { & $obsSetupPs -Camera primelive -NoPrompt }   # -NoPrompt=不打擾,金鑰由 setup 自動沿用
}

# ---- ② 首次設定(或 -Setup):選設備 → OBS 設定(問金鑰) ------------------------
if ($Setup -or -not (Test-Path $profDir)) {
    $picker = @((Join-Path $here "選設備.ps1"), (Join-Path $here "devices.ps1")) |
              Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($picker) { Note "第一次先選你的攝影機和麥克風..."; & $picker -EnginePath $engineExe }
    Note "設定 OBS(會問你的串流金鑰)..."
    # 注意:不可命名 $setup(與 [switch]$Setup 參數同名,PS 不分大小寫會炸型別)
    $obsSetupPs = Join-Path $here "setup.ps1"
    if (-not (Test-Path $obsSetupPs)) { Die "找不到 setup.ps1(要和本檔放在一起)。" }
    & $obsSetupPs -Camera primelive
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
    Note "背景開啟 OBS(縮到系統匣;主播用引擎視窗的「開始直播」鈕即可)..."
    $wsPwd = ""
    try { $wsPwd = (Get-Content (Join-Path $env:APPDATA "PrimeStage\obsws.json") -Raw -Encoding UTF8 | ConvertFrom-Json).password } catch {}
    # 清 OBS「上次未正常關閉」標記(.sentinel),否則 OBS 停在安全模式詢問框(藏在系統匣沒人按→遙控埠不開)
    $sent = Join-Path $env:APPDATA "obs-studio\.sentinel"
    if (Test-Path $sent) { try { [System.IO.Directory]::Delete($sent, $true) } catch {} }
    # --profile/--collection 直接指定,不受 user.ini 初始化狀態影響;--minimize-to-tray 藏起 OBS
    Start-Process -FilePath $obsExe -WorkingDirectory (Split-Path -Parent $obsExe) `
        -ArgumentList '--profile','Prime Stage 直式','--collection','Prime Stage 直式','--minimize-to-tray','--disable-shutdown-check',
                      '--websocket_port','4455','--websocket_password',$wsPwd | Out-Null
}
Note "完成。引擎視窗滾輪選濾鏡;OBS 按「開始串流」後回平台「確認開播」。"
