$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $root ".tmp-runtime"
$profileRoot = Join-Path $runtime "profile"
$appDataRoot = Join-Path $runtime "appdata"
$localAppDataRoot = Join-Path $runtime "localappdata"
$cacheRoot = Join-Path $runtime "cache"
$tempRoot = Join-Path $runtime "temp-work"
$paddleHome = Join-Path $runtime "paddle-home"
$paddlexCache = Join-Path $runtime "paddlex-cache"
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
New-Item -ItemType Directory -Force -Path $profileRoot,$appDataRoot,$localAppDataRoot,$cacheRoot,$tempRoot,$paddleHome,$paddlexCache | Out-Null
$env:PYTHONPATH = "$root\.deps;$root\src"
$env:HOME = $profileRoot
$env:USERPROFILE = $profileRoot
$env:APPDATA = $appDataRoot
$env:LOCALAPPDATA = $localAppDataRoot
$env:XDG_CACHE_HOME = $cacheRoot
$env:TEMP = $tempRoot
$env:TMP = $tempRoot
$env:TMPDIR = $tempRoot
$env:PADDLE_HOME = $paddleHome
$env:PADDLE_PDX_CACHE_HOME = $paddlexCache
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = "True"
python -m transprot --self-check