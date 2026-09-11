param(
    [Parameter(Mandatory=$true, Position=0)][string]$Url,
    [ValidateSet('en','es')][string]$Language = 'en',
    [string]$Slug = ''
)
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw 'Create .venv and install requirements.txt first; see docs/automation.md.'
}
if (-not $Slug) {
    $taskJobMatch = [regex]::Match($Url, '(?:currentJobId=|/jobs/view/(?:[^/?]*-)?)(\d{6,20})')
    $taskPrefix = if ($taskJobMatch.Success) { 'job-' + $taskJobMatch.Groups[1].Value } else { 'job' }
    $Slug = $taskPrefix + '-' + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss')
}
$taskOriginalPath = $env:PATH
try {
    $env:PATH = (Join-Path $PSScriptRoot '.venv\Scripts') + [IO.Path]::PathSeparator + $taskOriginalPath
    Push-Location $PSScriptRoot
    try {
        & $taskPython -m automation.run --url $Url --slug $Slug --language $Language --provider codex
        if ($LASTEXITCODE -ne 0) { throw 'CV generation stopped. Review the stage reported above.' }
    } finally { Pop-Location }
} finally { $env:PATH = $taskOriginalPath }
