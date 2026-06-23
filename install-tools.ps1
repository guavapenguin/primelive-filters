# primelive OBS 直播端 — 一鍵安裝工具
# 用法：在本資料夾開 PowerShell 執行  ./install-tools.ps1
# 內容：① OBS Studio ② NVIDIA Broadcast ③ 開 OBSBOT Center 下載頁

$ErrorActionPreference = 'Continue'

Write-Host '== [1/3] 安裝 OBS Studio ==' -ForegroundColor Cyan
winget install --id OBSProject.OBSStudio -e --source winget `
    --accept-source-agreements --accept-package-agreements

Write-Host '== [2/3] 下載並安裝 NVIDIA Broadcast v2.2.0（winget 無此包）==' -ForegroundColor Cyan
$url = 'https://international.download.nvidia.com/Windows/broadcast/2.2.0/NVIDIA_Broadcast_v2.2.0.54169681.exe'
$out = Join-Path $env:TEMP 'NVIDIA_Broadcast_v2.2.0.exe'
$ProgressPreference = 'SilentlyContinue'
try {
    Invoke-WebRequest -Uri $url -OutFile $out
    Write-Host ('  下載完成：{0} MB' -f [math]::Round((Get-Item $out).Length / 1MB))
    Start-Process $out   # 跑安裝精靈（需 RTX GPU + 較新驅動）
} catch {
    Write-Warning "NVIDIA Broadcast 下載失敗，請手動到 https://www.nvidia.com/zh-tw/geforce/broadcasting/broadcast-app/ 下載"
}

Write-Host '== [3/3] OBSBOT Center（winget 無，請手動下載）==' -ForegroundColor Cyan
Start-Process 'https://www.obsbot.com/download'   # 選 Tiny 系列 / OBSBOT Center, Windows 版

Write-Host '完成。OBS 與 OBSBOT Center 可同時開：Center 控相機、OBS 抓畫面。' -ForegroundColor Green
