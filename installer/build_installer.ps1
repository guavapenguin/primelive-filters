# Build the complete primelive Windows installer (bundles OBS).
# Usage: open PowerShell in obs/installer and run  ./build_installer.ps1
$eng  = 'f:\mcp\primelive\obs\engine'
$iss  = 'f:\mcp\primelive\obs\installer\primelive.iss'
$iscc = @(
  "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
  'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
  'C:\Program Files\Inno Setup 6\ISCC.exe'
) | Where-Object { Test-Path $_ } | Select-Object -First 1

Write-Host '[1/2] Rebuilding engine exe (latest filters / stickers / camera auto-detect)...'
& "$eng\build_exe.ps1"

Write-Host '[2/2] Compiling installer (bundling OBS)...'
if (-not $iscc) { Write-Warning 'ISCC.exe (Inno Setup) not found. Run: winget install JRSoftware.InnoSetup'; return }
& $iscc $iss

$out = 'f:\mcp\primelive\obs\installer\out\primelive_filter_setup.exe'

# ---- 程式碼簽章(消 SmartScreen 警告):設環境變數 PRIMELIVE_SIGN_PFX / PRIMELIVE_SIGN_PWD 後自動啟用 ----
#  EV 憑證(USB token)改用 -sha1 指紋:設 PRIMELIVE_SIGN_SHA1 即可(不需 pfx)
$pfx  = $env:PRIMELIVE_SIGN_PFX
$sha1 = $env:PRIMELIVE_SIGN_SHA1
$signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kitsin\*d\signtool.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
if ((Test-Path $out) -and $signtool -and (($pfx -and (Test-Path $pfx)) -or $sha1)) {
  Write-Host '[sign] signtool 簽章 installer + 引擎 exe...'
  $targets = @($out, 'f:\mcp\primelive\obs\engine\dist\primelive_filter\primelive_filter.exe')
  foreach ($t in $targets) {
    if ($sha1) { & $signtool sign /sha1 $sha1 /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 $t }
    else       { & $signtool sign /f $pfx /p $env:PRIMELIVE_SIGN_PWD /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 $t }
  }
  & $signtool verify /pa /v $out | Select-Object -Last 3
} elseif (Test-Path $out) {
  Write-Host '[sign] 未設憑證(PRIMELIVE_SIGN_PFX 或 PRIMELIVE_SIGN_SHA1),產出未簽章版(SmartScreen 會警告)'
}

if (Test-Path $out) {
  Write-Host ('DONE -> {0}  ({1} MB)' -f $out, [math]::Round((Get-Item $out).Length / 1MB))
} else {
  Write-Warning 'No installer produced; check messages above.'
}
