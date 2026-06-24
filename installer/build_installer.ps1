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
if (Test-Path $out) {
  Write-Host ('DONE -> {0}  ({1} MB)' -f $out, [math]::Round((Get-Item $out).Length / 1MB))
} else {
  Write-Warning 'No installer produced; check messages above.'
}
