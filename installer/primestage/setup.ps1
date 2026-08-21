# =============================================================================
#  Prime Stage 直播 - OBS 直式(垂直)一鍵設定  (Windows)
#  一次寫好手冊第三章的所有設定：進階輸出 / 編碼器 / 2500Kbps CBR / 直式 886x1920
#  主播只需要：① 雙擊執行 → ② 貼上自己的金鑰 → ③ 開 OBS 按「開始串流」
# =============================================================================
[CmdletBinding()]
param(
    # 推流伺服器(平台URL)。第一階段=自訂RTMP網頁版；日後改用 Amazon IVS 改 -ServiceType ivs
    [string]$Server = "rtmp://ingest.primestage.live:1935/live",

    # 串流金鑰。留空 = 執行時跳視窗問一次
    [string]$Key = "",

    # 編碼器：auto=自動偵測顯卡(NVENC>QSV>AMF>x264)；也可強制指定
    [ValidateSet("auto", "nvenc", "qsv", "amf", "x264")]
    [string]$Encoder = "auto",

    # 服務型態：custom=自訂RTMP(第一階段)；ivs=Amazon IVS(日後)
    [ValidateSet("custom", "ivs")]
    [string]$ServiceType = "custom",

    # 攝影機來源：primelive=預選自家濾鏡引擎的輸出「OBS Virtual Camera」(主播免選鏡頭)；
    #             none=留空,主播自己選
    [ValidateSet("primelive", "none")]
    [string]$Camera = "primelive",

    # 麥克風 device_id。留空=讀「選設備」存的設定,沒有就用 default(系統預設麥克風,最保險)
    [string]$Mic = "",

    # 不跳視窗(給批次/測試用)
    [switch]$NoPrompt
)

$ErrorActionPreference = "Stop"
$ProfileName = "Prime Stage 直式"
$SceneName   = "Prime Stage 直式"
# 直式解析度：手冊寫 886x1920，但 OBS 會把輸出寬度對齊到 4 的倍數(886→884)，
# 故用 884x1920(寬度可被 4 整除)讓 base=output、不產生縮放，畫面與 886 幾乎無差。
$BaseW = 884; $BaseH = 1920; $FPS = 30; $VBitrate = 2500; $ABitrate = 160

# ---- 小工具 -----------------------------------------------------------------
Add-Type -AssemblyName Microsoft.VisualBasic  -ErrorAction SilentlyContinue
Add-Type -AssemblyName System.Windows.Forms   -ErrorAction SilentlyContinue
function Show-Msg($text, $title, $icon = "Information") {
    if (-not $NoPrompt) { [System.Windows.Forms.MessageBox]::Show($text, $title, 'OK', $icon) | Out-Null }
    Write-Host "[$title] $text"
}
function Ask-Box($prompt, $title, $default = "") {
    if ($NoPrompt) { return $default }
    return [Microsoft.VisualBasic.Interaction]::InputBox($prompt, $title, $default)
}
function F($v) { ([double]$v).ToString([System.Globalization.CultureInfo]::InvariantCulture) }

# ini 用 UTF-8 帶 BOM + CRLF；json 用 UTF-8 不帶 BOM(比照 OBS 自己的寫法)
function Write-IniFile($path, $text) {
    $text = (($text -replace "`r`n", "`n") -replace "`n", "`r`n")
    [System.IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($true)))
}
function Write-TextNoBom($path, $text) {
    [System.IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($false)))
}

Write-Host "=== Prime Stage 直式一鍵設定 開始 ===" -ForegroundColor Cyan

# ---- 1. 找 OBS --------------------------------------------------------------
$obsRoot = Join-Path $env:APPDATA "obs-studio"
$obsExe = @(
    "$env:ProgramFiles\obs-studio\bin\64bit\obs64.exe",
    "${env:ProgramFiles(x86)}\obs-studio\bin\64bit\obs64.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $obsExe) {
    Show-Msg "找不到 OBS Studio。`n請先照手冊第一章到 https://obsproject.com/ 安裝 OBS(Windows 需 30.2 以上)，裝好後再執行本設定。" "找不到 OBS" "Error"
    exit 1
}
Write-Host "OBS：$obsExe"

# ---- 2. 先關閉 OBS(避免結束時覆蓋設定) --------------------------------------
$running = Get-Process obs64 -ErrorAction SilentlyContinue
if ($running) {
    Write-Host "OBS 執行中，先關閉..."
    $running | Stop-Process -Force -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt 20 -and (Get-Process obs64 -ErrorAction SilentlyContinue); $i++) { Start-Sleep -Milliseconds 300 }
}

# ---- 3. 問串流金鑰(升級刷新時保留舊金鑰,不重問)------------------------------
$oldKey = ""
$svcPath = Join-Path $obsRoot "basic\profiles\$ProfileName\service.json"
if (Test-Path $svcPath) {
    try { $oldKey = (Get-Content $svcPath -Raw -Encoding UTF8 | ConvertFrom-Json).settings.key } catch {}
}
if (-not $oldKey) {   # 後備:清理流程備份的金鑰(清掉 OBS profile 後仍保留)
    $savedKey = Join-Path $env:APPDATA "PrimeStage\saved_key.txt"
    if (Test-Path $savedKey) { try { $oldKey = (Get-Content $savedKey -Raw).Trim() } catch {} }
}
if (-not $Key) { $Key = $oldKey }                 # 已有金鑰(升級/清裝)→直接沿用
if (-not $Key) {
    $Key = Ask-Box "請貼上你的『串流金鑰』`n(直播主後台 → 設定 → OBS平台金鑰 → 複製)`n`n只會存在你這台電腦、不會外傳。" "Prime Stage 一鍵設定 - 貼上金鑰"
}
$Key = "$Key".Trim()
if (-not $Key) { $Key = $oldKey }                 # 取消也不清掉舊金鑰
if (-not $Key -and -not $NoPrompt) {
    $ans = [System.Windows.Forms.MessageBox]::Show("你沒有貼金鑰。要先把其他設定都設好、之後再自己到 OBS『設定→直播』貼金鑰嗎？`n`n「是」= 先設好其他；「否」= 取消", "沒有金鑰", 'YesNo', 'Warning')
    if ($ans -eq "No") { Write-Host "取消。"; exit 1 }
}

# ---- 4. 偵測編碼器 -----------------------------------------------------------
if ($Encoder -eq "auto") {
    $gpuNames = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | ForEach-Object { $_.Name }
    $gpus = ($gpuNames -join " | ")
    Write-Host "顯示卡：$gpus"
    if     ($gpus -match "NVIDIA")     { $Encoder = "nvenc" }
    elseif ($gpus -match "Intel")      { $Encoder = "qsv" }
    elseif ($gpus -match "AMD|Radeon") { $Encoder = "amf" }
    else                               { $Encoder = "x264" }
}
$encMap = @{
    nvenc = @{ id = "obs_nvenc_h264_tex"; s = [ordered]@{ bitrate=$VBitrate; rate_control="CBR"; keyint_sec=2; preset2="p5"; tune="hq"; multipass="qres"; profile="baseline"; bf=0; lookahead=$true; psycho_aq=$true } }
    qsv   = @{ id = "obs_qsv11_v2";       s = [ordered]@{ bitrate=$VBitrate; rate_control="CBR"; keyint_sec=2; profile="baseline"; target_usage="balanced" } }
    amf   = @{ id = "h264_texture_amf";   s = [ordered]@{ bitrate=$VBitrate; rate_control="CBR"; keyint_sec=2; profile="baseline"; preset="quality" } }
    x264  = @{ id = "obs_x264";           s = [ordered]@{ bitrate=$VBitrate; rate_control="CBR"; keyint_sec=2; profile="baseline"; preset="veryfast"; tune="" } }
}
$encId = $encMap[$Encoder].id
Write-Host "編碼器：$Encoder ($encId)"

# ---- 5. profile 三檔 --------------------------------------------------------
$profDir = Join-Path $obsRoot "basic\profiles\$ProfileName"
New-Item -ItemType Directory -Force -Path $profDir | Out-Null

$basicIni = @"
[General]
Name=$ProfileName

[Output]
Mode=Advanced
Reconnect=true
RetryDelay=2
MaxRetries=25
BindIP=default
NewSocketLoopEnable=false
LowLatencyEnable=false

[Stream1]
IgnoreRecommended=true
EnableMultitrackVideo=false

[AdvOut]
ApplyServiceSettings=false
UseRescale=false
TrackIndex=1
Encoder=$encId
AudioEncoder=ffmpeg_aac
RecEncoder=none
Track1Bitrate=$ABitrate
Track2Bitrate=$ABitrate

[Video]
BaseCX=$BaseW
BaseCY=$BaseH
OutputCX=$BaseW
OutputCY=$BaseH
FPSType=0
FPSCommon=$FPS
ScaleType=bicubic
ColorFormat=NV12
ColorSpace=709
ColorRange=Partial
SdrWhiteLevel=300
HdrNominalPeakLevel=1000

[Audio]
SampleRate=48000
ChannelSetup=Stereo
"@
Write-IniFile (Join-Path $profDir "basic.ini") $basicIni

# streamEncoder.json / service.json 為單純扁平物件，用 ConvertTo-Json 安全
Write-TextNoBom (Join-Path $profDir "streamEncoder.json") ($encMap[$Encoder].s | ConvertTo-Json -Depth 10)
if ($ServiceType -eq "ivs") {
    $service = [ordered]@{ type="rtmp_common"; settings=[ordered]@{ service="Amazon IVS"; server="auto"; key=$Key } }
} else {
    $service = [ordered]@{ type="rtmp_custom"; settings=[ordered]@{ server=$Server; key=$Key; use_auth=$false; bwtest=$false } }
}
Write-TextNoBom (Join-Path $profDir "service.json") ($service | ConvertTo-Json -Depth 10)

# ---- 6. 場景集(直式，攝影機填滿 + 麥克風/桌面音效) --------------------------
#  用文字模板寫，避免 PS 5.1 ConvertTo-Json 把空陣列變成 "" 的坑。
$posRelX = F ((0 - $BaseW/2.0)/($BaseH/2.0))   # 攝影機左上角對應的相對座標
$posRelY = F ((0 - $BaseH/2.0)/($BaseH/2.0))
$bRelX   = F ($BaseW/($BaseH/2.0))              # 邊界(填滿畫布)相對尺寸
$bRelY   = F ($BaseH/($BaseH/2.0))
$scenesDir = Join-Path $obsRoot "basic\scenes"
New-Item -ItemType Directory -Force -Path $scenesDir | Out-Null

# 攝影機來源設定：primelive=預選引擎輸出的「OBS Virtual Camera」(名稱+空路徑，OBS 會用名稱比對，跨機通用)
if ($Camera -eq "primelive") {
    $camSettingsJson = '{ "video_device_id": "OBS Virtual Camera:", "last_video_device_id": "OBS Virtual Camera:", "active": true }'
} else {
    $camSettingsJson = '{}'
}

# 麥克風 device_id：優先用 -Mic；否則讀「選設備」存的 devices.json；都沒有=default(系統預設，最保險，一定有音)
$MicId = "default"
$devFile = Join-Path $env:APPDATA "PrimeStage\devices.json"
if (Test-Path $devFile) {
    try { $d = Get-Content $devFile -Raw -Encoding UTF8 | ConvertFrom-Json; if ($d.micId) { $MicId = "$($d.micId)" } } catch {}
}
if ($Mic) { $MicId = $Mic }
$MicIdJson = ($MicId -replace '\\','\\')   # JSON 逸脫反斜線
Write-Host "麥克風 device_id：$MicId"

$sceneJson = @"
{
  "name": "$SceneName",
  "DesktopAudioDevice1": {
    "prev_ver": 536936450, "name": "輸出音效 1",
    "uuid": "a1b2c3d4-0003-4000-8000-primestageo01",
    "id": "wasapi_output_capture", "versioned_id": "wasapi_output_capture",
    "settings": { "device_id": "default" },
    "mixers": 255, "sync": 0, "flags": 0, "volume": 1.0, "balance": 0.5,
    "enabled": true, "muted": false,
    "push-to-mute": false, "push-to-mute-delay": 0, "push-to-talk": false, "push-to-talk-delay": 0,
    "hotkeys": { "libobs.mute": [], "libobs.unmute": [], "libobs.push-to-mute": [], "libobs.push-to-talk": [] },
    "deinterlace_mode": 0, "deinterlace_field_order": 0, "monitoring_type": 0, "private_settings": {}
  },
  "AuxAudioDevice1": {
    "prev_ver": 536936450, "name": "麥克風/輸入音效 1",
    "uuid": "a1b2c3d4-0004-4000-8000-primestagem01",
    "id": "wasapi_input_capture", "versioned_id": "wasapi_input_capture",
    "settings": { "device_id": "$MicIdJson" },
    "mixers": 255, "sync": 0, "flags": 0, "volume": 1.0, "balance": 0.5,
    "enabled": true, "muted": false,
    "push-to-mute": false, "push-to-mute-delay": 0, "push-to-talk": false, "push-to-talk-delay": 0,
    "hotkeys": { "libobs.mute": [], "libobs.unmute": [], "libobs.push-to-mute": [], "libobs.push-to-talk": [] },
    "deinterlace_mode": 0, "deinterlace_field_order": 0, "monitoring_type": 0, "private_settings": {}
  },
  "sources": [
    {
      "prev_ver": 536936450, "name": "攝影機",
      "uuid": "a1b2c3d4-0001-4000-8000-primestagec01",
      "id": "dshow_input", "versioned_id": "dshow_input",
      "settings": $camSettingsJson,
      "mixers": 255, "sync": 0, "flags": 0, "volume": 1.0, "balance": 0.5,
      "enabled": true, "muted": false,
      "push-to-mute": false, "push-to-mute-delay": 0, "push-to-talk": false, "push-to-talk-delay": 0,
      "hotkeys": { "libobs.mute": [], "libobs.unmute": [], "libobs.push-to-mute": [], "libobs.push-to-talk": [] },
      "deinterlace_mode": 0, "deinterlace_field_order": 0, "monitoring_type": 0, "private_settings": {}
    },
    {
      "prev_ver": 536936450, "name": "場景",
      "uuid": "a1b2c3d4-0002-4000-8000-primestages01",
      "id": "scene", "versioned_id": "scene",
      "settings": {
        "id_counter": 1, "custom_size": false,
        "items": [
          {
            "name": "攝影機", "source_uuid": "a1b2c3d4-0001-4000-8000-primestagec01",
            "visible": true, "locked": false, "rot": 0.0,
            "scale_ref": { "x": $BaseW.0, "y": $BaseH.0 },
            "align": 5, "bounds_type": 3, "bounds_align": 0, "bounds_crop": false,
            "crop_left": 0, "crop_top": 0, "crop_right": 0, "crop_bottom": 0,
            "id": 1, "group_item_backup": false,
            "pos": { "x": 0.0, "y": 0.0 }, "pos_rel": { "x": $posRelX, "y": $posRelY },
            "scale": { "x": 1.0, "y": 1.0 }, "scale_rel": { "x": 1.0, "y": 1.0 },
            "bounds": { "x": $BaseW.0, "y": $BaseH.0 }, "bounds_rel": { "x": $bRelX, "y": $bRelY },
            "scale_filter": "disable", "blend_method": "default", "blend_type": "normal",
            "show_transition": { "duration": 300 }, "hide_transition": { "duration": 300 },
            "private_settings": {}
          }
        ]
      },
      "mixers": 0, "sync": 0, "flags": 0, "volume": 1.0, "balance": 0.5,
      "enabled": true, "muted": false,
      "push-to-mute": false, "push-to-mute-delay": 0, "push-to-talk": false, "push-to-talk-delay": 0,
      "hotkeys": { "OBSBasic.SelectScene": [], "libobs.show_scene_item.1": [], "libobs.hide_scene_item.1": [] },
      "deinterlace_mode": 0, "deinterlace_field_order": 0, "monitoring_type": 0,
      "canvas_uuid": "6c69626f-6273-4c00-9d88-c5136d61696e", "private_settings": {}
    }
  ],
  "groups": [],
  "scene_order": [ { "name": "場景" } ],
  "current_scene": "場景", "current_program_scene": "場景",
  "canvases": [],
  "current_transition": "淡入淡出", "transition_duration": 300, "transitions": [],
  "saved_projectors": [], "preview_locked": false, "scaling_enabled": false,
  "virtual-camera": { "type2": 3 },
  "modules": {},
  "resolution": { "x": $BaseW, "y": $BaseH },
  "version": 2
}
"@
Write-TextNoBom (Join-Path $scenesDir "$SceneName.json") $sceneJson

# ---- 7. 讓 OBS 預設載入此 profile + 場景集 ----------------------------------
#  OBS 31+ 記在 user.ini [Basic]；OBS 30.2 記在 global.ini [Basic]。兩邊都寫最保險。
function Set-BasicSelection($iniPath) {
    $block = "[Basic]`r`nProfile=$ProfileName`r`nProfileDir=$ProfileName`r`nSceneCollection=$SceneName`r`nSceneCollectionFile=$SceneName"
    if (Test-Path $iniPath) {
        Copy-Item $iniPath "$iniPath.primestage.bak" -Force -ErrorAction SilentlyContinue
        $raw = [System.IO.File]::ReadAllText($iniPath)
        if ($raw -match "(?ms)^\[Basic\]\r?\n.*?(?=(\r?\n\[)|\z)") {
            $raw = [regex]::Replace($raw, "(?ms)^\[Basic\]\r?\n.*?(?=(\r?\n\[)|\z)", $block)
        } else {
            $raw = $raw.TrimEnd() + "`r`n`r`n" + $block + "`r`n"
        }
        Write-IniFile $iniPath $raw
    } else {
        # 全新機:OBS 還沒跑過、檔案不存在 → 直接建(含 FirstRun 標記,避免首次設定精靈蓋掉選擇)
        Write-IniFile $iniPath ("[General]`r`nFirstRun=true`r`nPre19Defaults=false`r`nPre21Defaults=false`r`nPre23Defaults=false`r`nPre24.1Defaults=false`r`n`r`n" + $block + "`r`n")
    }
}
# OBS 31+ 讀 user.ini、30.x 讀 global.ini;兩個都「一定」寫(全新機兩個都不存在,不存在就建)
Set-BasicSelection (Join-Path $obsRoot "user.ini")
Set-BasicSelection (Join-Path $obsRoot "global.ini")

# 啟用 OBS WebSocket(隨機密碼,只給本機引擎「開始直播」按鈕遙控用)
try {
    $wsPwd = [guid]::NewGuid().ToString("N")
    $existing = Join-Path $env:APPDATA "PrimeStage\obsws.json"
    if (Test-Path $existing) {   # 已有密碼就沿用(避免 OBS 端與引擎端不同步)
        try { $wsPwd = (Get-Content $existing -Raw -Encoding UTF8 | ConvertFrom-Json).password } catch {}
    }
    $wsDir = Join-Path $obsRoot "plugin_config\obs-websocket"
    New-Item -ItemType Directory -Force -Path $wsDir | Out-Null
    Write-TextNoBom (Join-Path $wsDir "config.json") ('{"alerts_enabled":false,"auth_required":true,"first_load":false,"server_enabled":true,"server_password":"' + $wsPwd + '","server_port":4455}')
    New-Item -ItemType Directory -Force -Path (Join-Path $env:APPDATA "PrimeStage") | Out-Null
    Write-TextNoBom $existing ('{"port":4455,"password":"' + $wsPwd + '"}')
} catch {}

# 關閉 OBS 自動更新提示(開播前跳更新視窗會讓主播卡住)
try {
    $gIni = Join-Path $obsRoot "global.ini"
    $raw = [System.IO.File]::ReadAllText($gIni)
    if ($raw -match "EnableAutoUpdates=") {
        $raw = $raw -replace "EnableAutoUpdates=\w+", "EnableAutoUpdates=false"
    } elseif ($raw -match "(?m)^\[General\]") {
        $raw = $raw -replace "(?m)^\[General\]", "[General]`r`nEnableAutoUpdates=false"
    } else {
        $raw = "[General]`r`nEnableAutoUpdates=false`r`n`r`n" + $raw
    }
    Write-IniFile $gIni $raw
} catch {}

# ---- 8. 完成 ----------------------------------------------------------------
$keyState = if ($Key) { "已寫入你的金鑰" } else { "尚未填金鑰(記得到 OBS 設定→直播 貼上)" }
$camStep = if ($Camera -eq "primelive") {
    "2. 攝影機已預選『OBS Virtual Camera』(＝濾鏡引擎輸出)，先開好引擎點濾鏡就會有畫面"
} else {
    "2. 雙擊畫面下方『攝影機』來源 → 選你的攝影機或美顏虛擬相機"
}
Show-Msg @"
設定完成！(直式 $BaseW x $BaseH / $VBitrate Kbps / 編碼器 $Encoder)
$keyState

接下來：
1. 開啟 OBS(會自動切到『$ProfileName』)
$camStep
3. 右下角按『開始串流』，再回平台按『確認開播』

要還原：user.ini / global.ini 已備份為 *.primestage.bak
"@ "Prime Stage 一鍵設定 完成"
# 設定版本戳記(golive 靠它判斷升級後要不要刷新設定)
$psDir = Join-Path $env:APPDATA "PrimeStage"
New-Item -ItemType Directory -Force -Path $psDir | Out-Null
Set-Content -Path (Join-Path $psDir "config_ver.txt") -Value "8" -Encoding Ascii -NoNewline
Write-Host "=== 完成 ===" -ForegroundColor Green
