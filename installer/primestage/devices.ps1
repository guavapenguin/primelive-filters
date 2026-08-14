# =============================================================================
#  Prime Stage - 選攝影機 & 麥克風(GUI 視窗版,無主控台互動)
#  存到 %APPDATA%\PrimeStage\devices.json;一鍵開播/設定會自動套用。
# =============================================================================
[CmdletBinding()]
param([string]$EnginePath = "")   # 保留參數相容,GUI 版不需要引擎
$ErrorActionPreference = "Continue"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$cfgDir = Join-Path $env:APPDATA "PrimeStage"
$cfgFile = Join-Path $cfgDir "devices.json"
New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null

# ---- 攝影機清單(WMI;名稱與 DirectShow 相同,引擎用名稱比對) ----
$cams = @()
try {
    $cams = Get-CimInstance Win32_PnPEntity -ErrorAction Stop |
        Where-Object { $_.PNPClass -in @("Camera","Image") -and $_.Status -eq "OK" } |
        Select-Object -ExpandProperty Name -Unique |
        Where-Object { $_ -notmatch "OBS Virtual|Virtual Camera" }   # 排除虛擬相機(那是引擎輸出)
} catch {}

# ---- 麥克風清單(登錄檔 Active 錄音端點) ----
$base = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture"
$fnKey = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"
$mics = @()
Get-ChildItem $base -ErrorAction SilentlyContinue | ForEach-Object {
    $state = (Get-ItemProperty $_.PSPath -Name DeviceState -ErrorAction SilentlyContinue).DeviceState
    if ($state -ne 1) { return }
    $fn = (Get-ItemProperty (Join-Path $_.PSPath "Properties") -Name $fnKey -ErrorAction SilentlyContinue).$fnKey
    if ($fn) { $mics += ,@($fn, "{0.0.1.00000000}." + $_.PSChildName) }
}

# ---- GUI ----
$form = New-Object System.Windows.Forms.Form
$form.Text = "primelive 選設備"
$form.Size = New-Object System.Drawing.Size(430, 260)
$form.StartPosition = "CenterScreen"
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false; $form.MinimizeBox = $false
$form.Font = New-Object System.Drawing.Font("Microsoft JhengHei UI", 10)

$lbl1 = New-Object System.Windows.Forms.Label
$lbl1.Text = "攝影機  Camera"
$lbl1.Location = New-Object System.Drawing.Point(20, 20)
$lbl1.AutoSize = $true
$form.Controls.Add($lbl1)

$cbCam = New-Object System.Windows.Forms.ComboBox
$cbCam.DropDownStyle = "DropDownList"
$cbCam.Location = New-Object System.Drawing.Point(20, 45)
$cbCam.Size = New-Object System.Drawing.Size(375, 30)
[void]$cbCam.Items.Add("(自動偵測,推薦)")
foreach ($c in $cams) { [void]$cbCam.Items.Add($c) }
$cbCam.SelectedIndex = 0
$form.Controls.Add($cbCam)

$lbl2 = New-Object System.Windows.Forms.Label
$lbl2.Text = "麥克風  Microphone"
$lbl2.Location = New-Object System.Drawing.Point(20, 85)
$lbl2.AutoSize = $true
$form.Controls.Add($lbl2)

$cbMic = New-Object System.Windows.Forms.ComboBox
$cbMic.DropDownStyle = "DropDownList"
$cbMic.Location = New-Object System.Drawing.Point(20, 110)
$cbMic.Size = New-Object System.Drawing.Size(375, 30)
[void]$cbMic.Items.Add("(系統預設,最保險)")
foreach ($m in $mics) { [void]$cbMic.Items.Add($m[0]) }
$cbMic.SelectedIndex = 0
$form.Controls.Add($cbMic)

$btn = New-Object System.Windows.Forms.Button
$btn.Text = "確定"
$btn.Location = New-Object System.Drawing.Point(295, 165)
$btn.Size = New-Object System.Drawing.Size(100, 34)
$btn.DialogResult = [System.Windows.Forms.DialogResult]::OK
$form.Controls.Add($btn)
$form.AcceptButton = $btn

# 帶入上次選擇
if (Test-Path $cfgFile) {
    try {
        $prev = Get-Content $cfgFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($prev.cameraName) { $i = $cbCam.Items.IndexOf($prev.cameraName); if ($i -ge 0) { $cbCam.SelectedIndex = $i } }
        if ($prev.micName)    { $i = $cbMic.Items.IndexOf($prev.micName);    if ($i -ge 0) { $cbMic.SelectedIndex = $i } }
    } catch {}
}

if ($form.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { exit 0 }

$camName = if ($cbCam.SelectedIndex -le 0) { "" } else { $cbCam.SelectedItem }
if ($cbMic.SelectedIndex -le 0) { $micId = "default"; $micName = "系統預設麥克風" }
else { $micId = $mics[$cbMic.SelectedIndex - 1][1]; $micName = $mics[$cbMic.SelectedIndex - 1][0] }

$cfg = [ordered]@{ cameraName = "$camName"; micId = $micId; micName = $micName }
[System.IO.File]::WriteAllText($cfgFile, ($cfg | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($false)))

# 若 OBS 場景已存在,直接套用麥克風
$sceneFile = Join-Path $env:APPDATA "obs-studio\basic\scenes\Prime Stage 直式.json"
if (Test-Path $sceneFile) {
    try {
        $j = [System.IO.File]::ReadAllText($sceneFile, (New-Object System.Text.UTF8Encoding($false)))
        $idx = $j.IndexOf('"AuxAudioDevice1"')
        if ($idx -ge 0) {
            $head = $j.Substring(0, $idx); $tail = $j.Substring($idx)
            $tail = ([regex]'"device_id":\s*"[^"]*"').Replace($tail, ('"device_id": "' + $micId + '"'), 1)
            [System.IO.File]::WriteAllText($sceneFile, ($head + $tail), (New-Object System.Text.UTF8Encoding($false)))
        }
    } catch {}
}
exit 0
