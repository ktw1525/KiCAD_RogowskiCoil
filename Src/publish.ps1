param(
    [string]$OutputDirectory = (Join-Path (Split-Path -Parent $PSScriptRoot) 'Publish')
)

$ErrorActionPreference = 'Stop'
$temporaryZip = $null
$temporaryDirectory = $null
$keepPackage = $false
try {
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $required = @(
        'metadata.json', 'README_KO.txt',
        'plugins/__init__.py', 'plugins/rogowski_action.py',
        'plugins/geometry.py', 'plugins/preview.py', 'plugins/coil_model.json',
        'plugins/toolbar.png', 'resources/icon.png'
    )
    foreach ($relative in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $relative) -PathType Leaf)) {
            throw "Required package file is missing: $relative"
        }
    }
    $metadata = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'metadata.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $version = [string]$metadata.versions[0].version
    if ($version -notmatch '^\d+\.\d+\.\d+$') {
        throw 'metadata.json must contain a major.minor.patch version.'
    }
    $outputPath = [IO.Path]::GetFullPath($OutputDirectory)
    $destination = Join-Path $outputPath "Rogowski_TI_Gerber_PCM_KiCad10_v$version.zip"
    $files = @('metadata.json', 'README_KO.txt')
    foreach ($folder in @('plugins', 'resources')) {
        $basePath = Join-Path $PSScriptRoot $folder
        foreach ($file in (Get-ChildItem -LiteralPath $basePath -Recurse -File)) {
            $relative = $file.FullName.Substring($PSScriptRoot.Length + 1).Replace('\', '/')
            if ($relative -match '(^|/)__pycache__(/|$)' -or $file.Extension -in @('.pyc', '.pyo', '.bak', '.tmp') -or $file.Name.EndsWith('~')) { continue }
            $files += $relative
        }
    }
    $files = @($files | Sort-Object -Unique)
    $temporaryDirectory = Join-Path ([IO.Path]::GetTempPath()) ('rogowski-' + [guid]::NewGuid().ToString('N'))
    [IO.Directory]::CreateDirectory($temporaryDirectory) | Out-Null
    $temporaryZip = Join-Path $temporaryDirectory ([IO.Path]::GetFileName($destination))
    Write-Host "[1/3] Packing $($files.Count) files (version $version)..."
    $archive = [IO.Compression.ZipFile]::Open($temporaryZip, [IO.Compression.ZipArchiveMode]::Create)
    try {
        foreach ($relative in $files) {
            [IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $archive, (Join-Path $PSScriptRoot $relative), $relative,
                [IO.Compression.CompressionLevel]::Optimal) | Out-Null
        }
    } finally { $archive.Dispose() }
    Write-Host '[2/3] Checking package entries...'
    $archive = [IO.Compression.ZipFile]::OpenRead($temporaryZip)
    try {
        if ($archive.Entries.Count -ne $files.Count) { throw 'Package entry count mismatch.' }
        foreach ($relative in $files) {
            $entry = $archive.GetEntry($relative)
            if ($null -eq $entry) { throw "Package entry missing: $relative" }
            $stream = $entry.Open()
            $buffer = [IO.MemoryStream]::new()
            try {
                $stream.CopyTo($buffer)
                $expected = [Convert]::ToBase64String([IO.File]::ReadAllBytes((Join-Path $PSScriptRoot $relative)))
                if ([Convert]::ToBase64String($buffer.ToArray()) -cne $expected) {
                    throw "Package entry differs from source: $relative"
                }
            } finally { $stream.Dispose(); $buffer.Dispose() }
        }
    } finally { $archive.Dispose() }
    Write-Host '[3/3] Saving to Publish...'
    try {
        if (-not (Test-Path -LiteralPath $outputPath -PathType Container)) {
            New-Item -ItemType Directory -Path $outputPath | Out-Null
        }
        # Replace only the matching version after the temporary ZIP is verified.
        [IO.File]::Copy($temporaryZip, $destination, $true)
    } catch {
        # A valid build must survive a blocked destination (e.g. Windows CFA).
        $keepPackage = $true
        Write-Host '[WARNING] ZIP created and verified, but saving to Publish failed.' -ForegroundColor Yellow
        Write-Host ('Reason: ' + $_.Exception.Message)
        Write-Host "ZIP saved here: $temporaryZip"
        Write-Host "Copy this ZIP into: $outputPath"
        Write-Host 'Use File Explorer to copy the ZIP. The existing package was not intentionally removed.'
        Write-Host 'If Controlled folder access blocked PowerShell, review the Windows Security notification.'
        exit 2
    }
    Write-Host "[OK] $destination"
    exit 0
} catch {
    Write-Host ('[ERROR] ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    if (-not $keepPackage -and $temporaryZip -and [IO.File]::Exists($temporaryZip)) {
        [IO.File]::Delete($temporaryZip)
    }
    if (-not $keepPackage -and $temporaryDirectory -and [IO.Directory]::Exists($temporaryDirectory)) {
        [IO.Directory]::Delete($temporaryDirectory, $false)
    }
}
