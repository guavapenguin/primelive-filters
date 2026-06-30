# 把 primelive 濾鏡引擎打包成獨立 .exe（PyInstaller onedir）
# 用法：在 obs/engine 開 PowerShell 執行  ./build_exe.ps1
$eng = Split-Path -Parent $MyInvocation.MyCommand.Path
$pp = Join-Path $eng ".venv\Scripts\python.exe"

Write-Host "[1/3] 安裝 PyInstaller..."
& $pp -m pip install pyinstaller --disable-pip-version-check --no-input

Write-Host "[2/3] 打包（--collect-all mediapipe 收集模型圖檔；含 pygrabber/comtypes 供名稱選鏡頭）..."
Push-Location $eng
& $pp -m PyInstaller --noconfirm --onedir --name primelive_filter --collect-all mediapipe --collect-all comtypes --hidden-import pygrabber.dshow_graph primelive_engine.py
Pop-Location

Write-Host "[3/3] 複製模型 / 設定 / 素材到 exe 旁..."
$dist = Join-Path $eng "dist\primelive_filter"
Copy-Item (Join-Path $eng "face_landmarker.task")  $dist -Force
Copy-Item (Join-Path $eng "selfie_segmenter.task") $dist -Force
Copy-Item (Join-Path $eng "filters.json")          $dist -Force
Copy-Item (Join-Path (Split-Path $eng) "assets")   (Join-Path $dist "assets") -Recurse -Force
Write-Host "完成 -> $dist\primelive_filter.exe"
