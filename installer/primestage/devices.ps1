# =============================================================================
#  Prime Stage - 選我的攝影機 & 麥克風（每位主播設備不同，這裡挑一次就記住）
#   - 攝影機：給濾鏡引擎用(引擎會開你選的那台)
#   - 麥克風：寫進 OBS(直接進直播的聲音)；預設=系統預設麥克風(最保險，一定有音)
#  選好存到 %APPDATA%\PrimeStage\devices.json，一鍵開播/設定都會自動套用。
# =============================================================================
[CmdletBinding()]
param([string]$EnginePath = "")
$ErrorActionPreference = "Continue"
try { chcp 65001 > $null } catch {}
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$cfgDir = Join-Path $env:APPDATA "PrimeStage"
$cfgFile = Join-Path $cfgDir "devices.json"
New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null

function Read-Num($prompt, $max) {
    while ($true) {
        $s = Read-Host $prompt
        if ($s -match '^\d+$' -and [int]$s -le $max) { return [int]$s }
        Write-Host "  請輸入 0 ~ $max 的數字。" -ForegroundColor Yellow
    }
}

Write-Host "==== Prime Stage 選設備 ====" -ForegroundColor Cyan

# ---------- 1) 攝影機（問引擎要清單）----------
Write-Host "`n[攝影機] 掃描中..." -ForegroundColor Cyan
$engine = @(
    $EnginePath,
    "$env:ProgramFiles\primelive-filter\primelive_filter.exe",
    "${env:ProgramFiles(x86)}\primelive-filter\primelive_filter.exe",
    (Join-Path $here "engine\primelive_filter.exe"),
    (Join-Path $here "engine\primelive_filter\primelive_filter.exe"),
    "F:\mcp\primelive\obs\engine\dist\primelive_filter\primelive_filter.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
$engArgs = @("--list-cameras")
$engCwd = $here
if (-not $engine) {
    $devDir = "F:\mcp\primelive\obs\engine"; $py = Join-Path $devDir ".venv\Scripts\python.exe"
    if ((Test-Path $py) -and (Test-Path (Join-Path $devDir "primelive_engine.py"))) {
        $engine = $py; $engArgs = @("primelive_engine.py","--list-cameras"); $engCwd = $devDir
    }
}
$camName = ""
if ($engine) {
    Push-Location $engCwd
    $out = & $engine @engArgs 2>&1 | Out-String
    Pop-Location
    $cams = @()
    foreach ($line in ($out -split "`r?`n")) {
        if ($line -match '^\s*(\d+):\s*(.+?)(\s+<-.*)?\s*$') { $cams += ,@([int]$matches[1], $matches[2].Trim()) }
    }
    if ($cams.Count -gt 0) {
        Write-Host "請選你的攝影機："
        foreach ($c in $cams) { Write-Host ("   {0}: {1}" -f $c[0], $c[1]) }
        Write-Host "   -1: 不指定(讓引擎自動挑)"
        $sel = Read-Host "輸入編號"
        if ($sel -match '^\d+$') {
            $picked = $cams | Where-Object { $_[0] -eq [int]$sel } | Select-Object -First 1
            if ($picked) { $camName = $picked[1]; Write-Host ("  已選攝影機：{0}" -f $camName) -ForegroundColor Green }
        } else { Write-Host "  不指定，引擎會自動挑。" }
    } else {
        Write-Host "  抓不到攝影機清單(輸出如下)，先跳過，引擎會自動挑：" -ForegroundColor Yellow
        Write-Host $out
    }
} else {
    Write-Host "  找不到引擎，攝影機先跳過(引擎日後會自動挑)。" -ForegroundColor Yellow
}

# ---------- 2) 麥克風（列 Windows 錄音裝置）----------
Write-Host "`n[麥克風] 掃描中..." -ForegroundColor Cyan
$base = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture"
$fnKey = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"
$mics = @()
Get-ChildItem $base -ErrorAction SilentlyContinue | ForEach-Object {
    $guid = $_.PSChildName
    $state = (Get-ItemProperty $_.PSPath -Name DeviceState -ErrorAction SilentlyContinue).DeviceState
    if ($state -ne 1) { return }   # 只列 Active(接著、可用)的
    $fn = (Get-ItemProperty (Join-Path $_.PSPath "Properties") -Name $fnKey -ErrorAction SilentlyContinue).$fnKey
    $mics += ,@($fn, "{0.0.1.00000000}.$guid")
}
Write-Host "請選麥克風(建議先用 0 系統預設，最保險)："
Write-Host "   0: 系統預設麥克風(最保險，一定有音)"
for ($i = 0; $i -lt $mics.Count; $i++) { Write-Host ("   {0}: {1}" -f ($i+1), $mics[$i][0]) }
$msel = Read-Num "輸入編號" $mics.Count
if ($msel -eq 0) { $micId = "default"; $micName = "系統預設麥克風" }
else { $micId = $mics[$msel-1][1]; $micName = $mics[$msel-1][0] }
Write-Host ("  已選麥克風：{0}" -f $micName) -ForegroundColor Green

# ---------- 3) 存設定 ----------
$cfg = [ordered]@{ cameraName = $camName; micId = $micId; micName = $micName }
[System.IO.File]::WriteAllText($cfgFile, ($cfg | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($false)))
Write-Host "`n已存到 $cfgFile"

# ---------- 4) 若 OBS 場景已存在，直接把麥克風套進去 ----------
$sceneFile = Join-Path $env:APPDATA "obs-studio\basic\scenes\Prime Stage 直式.json"
if (Test-Path $sceneFile) {
    $j = Get-Content $sceneFile -Raw -Encoding UTF8
    $idx = $j.IndexOf('"AuxAudioDevice1"')
    if ($idx -ge 0) {
        $head = $j.Substring(0, $idx); $tail = $j.Substring($idx)
        $tail = ([regex]'"device_id":\s*"[^"]*"').Replace($tail, ('"device_id": "' + ($micId -replace '\\','\\') + '"'), 1)
        [System.IO.File]::WriteAllText($sceneFile, ($head + $tail), (New-Object System.Text.UTF8Encoding($false)))
        Write-Host "已把麥克風套進現有的 OBS 場景。" -ForegroundColor Green
    }
} else {
    Write-Host "(OBS 還沒設定過；下次『一鍵開播』會自動套用你選的麥克風。)"
}
Write-Host "`n完成！可以關掉這個視窗了。" -ForegroundColor Green
