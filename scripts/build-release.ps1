param(
    [string]$PythonExe = 'python',
    [switch]$InstallMissingDeps,
    [switch]$SkipInstaller,
    [switch]$OfflineOcr,
    [string]$OfflineOcrSource
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$packagingDir = Join-Path $repoRoot 'packaging'
$specPath = Join-Path $packagingDir 'transprot.spec'
$buildDir = Join-Path $repoRoot 'build'
$distDir = Join-Path $repoRoot 'dist'
$appDistDir = Join-Path $distDir 'TransProt'
$installerOutputDir = Join-Path $repoRoot 'installer-output'
$tempRoot = Join-Path $repoRoot '.tmp-build'
$tempAppData = Join-Path $tempRoot 'appdata'
$tempLocalAppData = Join-Path $tempRoot 'localappdata'
$offlineOcrStageDir = Join-Path $tempRoot 'offline-ocr-models'

function Write-Step([string]$Message) {
    Write-Host "[TransProt Build] $Message" -ForegroundColor Cyan
}

function Assert-CommandSuccess {
    param(
        [int]$ExitCode,
        [string]$Action
    )

    if ($ExitCode -ne 0) {
        throw "$Action failed with exit code $ExitCode."
    }
}

function Test-PythonModule {
    param(
        [string]$PythonCommand,
        [string]$ModuleName
    )

    & $PythonCommand -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$ModuleName') else 1)" | Out-Null
    return $LASTEXITCODE -eq 0
}

function Resolve-InnoCompiler {
    $pathHit = Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue
    if ($pathHit) {
        return $pathHit.Source
    }

    $candidates = @(
        'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
        'C:\Program Files\Inno Setup 6\ISCC.exe'
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    return $null
}

function Test-ReadableModelDirectory {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return $false
    }
    try {
        return (Get-ChildItem -Path $Path -Recurse -File -ErrorAction Stop | Measure-Object).Count -gt 0
    }
    catch {
        return $false
    }
}

function Copy-ModelDirectory {
    param(
        [string]$Source,
        [string]$Destination
    )

    Remove-Item -LiteralPath $Destination -Recurse -Force -ErrorAction SilentlyContinue
    Copy-Item -Path $Source -Destination $Destination -Recurse -Force -ErrorAction Stop
}

function Download-MobileOcrModels {
    param(
        [string]$PythonCommand,
        [string]$StageRoot,
        [string]$TempRoot
    )

    $downloadRoot = Join-Path $TempRoot 'mobile-ocr-download'
    Remove-Item -LiteralPath $downloadRoot -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $downloadRoot | Out-Null

    $env:PADDLE_PDX_CACHE_HOME = $downloadRoot
    $env:PADDLE_HOME = Join-Path $downloadRoot 'paddle-home'
    $env:XDG_CACHE_HOME = Join-Path $downloadRoot 'cache'
    $env:TEMP = Join-Path $downloadRoot 'temp'
    $env:TMP = $env:TEMP
    New-Item -ItemType Directory -Force -Path $env:PADDLE_HOME, $env:XDG_CACHE_HOME, $env:TEMP | Out-Null

    Write-Step 'Downloading mobile OCR models during build'
    & $PythonCommand -c "from paddleocr import PaddleOCR; PaddleOCR(lang='ch', ocr_version='PP-OCRv4', text_detection_model_name='PP-OCRv4_mobile_det', text_recognition_model_name='PP-OCRv4_mobile_rec', text_det_limit_side_len=640, text_det_limit_type='max', use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False, enable_mkldnn=False, cpu_threads=2)"
    Assert-CommandSuccess -ExitCode $LASTEXITCODE -Action 'Mobile OCR model download'

    $sourceRoot = Join-Path $downloadRoot 'official_models'
    if (-not (Test-ReadableModelDirectory (Join-Path $sourceRoot 'PP-OCRv4_mobile_det')) -or -not (Test-ReadableModelDirectory (Join-Path $sourceRoot 'PP-OCRv4_mobile_rec'))) {
        throw 'Downloaded mobile OCR models are incomplete.'
    }

    New-Item -ItemType Directory -Force -Path $StageRoot | Out-Null
    Copy-ModelDirectory -Source (Join-Path $sourceRoot 'PP-OCRv4_mobile_det') -Destination (Join-Path $StageRoot 'PP-OCRv4_mobile_det')
    Copy-ModelDirectory -Source (Join-Path $sourceRoot 'PP-OCRv4_mobile_rec') -Destination (Join-Path $StageRoot 'PP-OCRv4_mobile_rec')
}

function Prepare-MobileOfflineOcrModels {
    param(
        [string]$PythonCommand,
        [string]$SourceRoot,
        [string]$StageRoot,
        [string]$TempRoot
    )

    Remove-Item -LiteralPath $StageRoot -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $StageRoot | Out-Null

    $detSource = if ($SourceRoot) { Join-Path $SourceRoot 'PP-OCRv4_mobile_det' } else { '' }
    $recSource = if ($SourceRoot) { Join-Path $SourceRoot 'PP-OCRv4_mobile_rec' } else { '' }

    if ((Test-ReadableModelDirectory $detSource) -and (Test-ReadableModelDirectory $recSource)) {
        Write-Step "Copying mobile OCR models from: $SourceRoot"
        Copy-ModelDirectory -Source $detSource -Destination (Join-Path $StageRoot 'PP-OCRv4_mobile_det')
        Copy-ModelDirectory -Source $recSource -Destination (Join-Path $StageRoot 'PP-OCRv4_mobile_rec')
        return $StageRoot
    }

    Write-Step 'Local mobile OCR model cache is incomplete; switching to build-time download'
    Download-MobileOcrModels -PythonCommand $PythonCommand -StageRoot $StageRoot -TempRoot $TempRoot
    return $StageRoot
}

Write-Step 'Preparing build directories'
New-Item -ItemType Directory -Force -Path $tempAppData, $tempLocalAppData, $installerOutputDir | Out-Null
Remove-Item -Recurse -Force $buildDir, $distDir, $offlineOcrStageDir -ErrorAction SilentlyContinue

if ($InstallMissingDeps) {
    Write-Step 'Installing build dependencies'
    & $PythonExe -m pip install -e '.[desktop,ocr,build]'
    Assert-CommandSuccess -ExitCode $LASTEXITCODE -Action 'Dependency installation'
}
else {
    Write-Step 'Checking required Python modules'
    $requiredModules = @('PyInstaller', 'PySide6', 'PIL', 'paddle', 'paddleocr')
    $missingModules = @()
    foreach ($moduleName in $requiredModules) {
        if (-not (Test-PythonModule -PythonCommand $PythonExe -ModuleName $moduleName)) {
            $missingModules += $moduleName
        }
    }
    if ($missingModules.Count -gt 0) {
        throw "Missing required modules: $($missingModules -join ', '). Run `pip install -e .[desktop,ocr,build]` first, or rerun this script with -InstallMissingDeps."
    }
}

$env:PYTHONPATH = "$repoRoot\src;$repoRoot\.deps"
$env:APPDATA = $tempAppData
$env:LOCALAPPDATA = $tempLocalAppData
$env:HOME = $tempLocalAppData
$env:USERPROFILE = $tempLocalAppData
$env:XDG_CACHE_HOME = Join-Path $tempLocalAppData 'cache'
$env:PADDLE_HOME = Join-Path $env:XDG_CACHE_HOME 'paddle'
$env:PADDLE_PDX_CACHE_HOME = Join-Path $env:XDG_CACHE_HOME 'paddlex'
$env:TEMP = Join-Path $env:XDG_CACHE_HOME 'temp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:XDG_CACHE_HOME, $env:PADDLE_HOME, $env:PADDLE_PDX_CACHE_HOME, $env:TEMP | Out-Null

if ($OfflineOcr) {
    if (-not $OfflineOcrSource) {
        $OfflineOcrSource = Join-Path $repoRoot '.tmp-runtime\paddlex-cache\official_models'
    }
    Write-Step "Preparing mobile offline OCR bundle"
    $env:TRANSPROT_OFFLINE_OCR_SOURCE = Prepare-MobileOfflineOcrModels -PythonCommand $PythonExe -SourceRoot $OfflineOcrSource -StageRoot $offlineOcrStageDir -TempRoot $tempRoot
}
else {
    Remove-Item Env:TRANSPROT_OFFLINE_OCR_SOURCE -ErrorAction SilentlyContinue
}

Write-Step 'Running environment self-check'
& $PythonExe -m transprot --self-check
Assert-CommandSuccess -ExitCode $LASTEXITCODE -Action 'Environment self-check'

Write-Step 'Building onedir release with PyInstaller'
& $PythonExe -m PyInstaller --noconfirm $specPath
Assert-CommandSuccess -ExitCode $LASTEXITCODE -Action 'PyInstaller build'

if (-not (Test-Path (Join-Path $appDistDir 'TransProt.exe'))) {
    throw 'PyInstaller finished but dist\TransProt\TransProt.exe was not created.'
}

Write-Step "Onedir build ready: $appDistDir"

if ($SkipInstaller) {
    Write-Step 'Installer creation skipped by request'
    exit 0
}

$innoCompiler = Resolve-InnoCompiler
if (-not $innoCompiler) {
    throw 'Inno Setup compiler (ISCC.exe) was not found. Install Inno Setup 6, or rerun with -SkipInstaller to build the green version only.'
}

Write-Step 'Building Windows installer'
$outputBaseFilename = if ($OfflineOcr) { 'TransProt-Mobile-Setup' } else { 'TransProt-Setup' }
& $innoCompiler "/DRepoRoot=$repoRoot" "/DDistDir=$appDistDir" "/DOutputDir=$installerOutputDir" "/DOutputBaseFilename=$outputBaseFilename" (Join-Path $packagingDir 'TransProt.iss')
Assert-CommandSuccess -ExitCode $LASTEXITCODE -Action 'Inno Setup build'

Write-Step "Installer output ready: $installerOutputDir"