param(
    [Parameter(Mandatory=$true, Position=0)][string]$Url,
    [ValidateSet('en','es')][string]$Language = 'en',
    [string]$Slug = '',
    [ValidateSet('codex','openai','compatible')][string]$Provider = '',
    [string]$Model = '',
    [string]$Config = '',
    [string]$BaseUrl = '',
    [string]$ApiKeyEnv = '',
    [string]$JobText = '',
    [switch]$Resume
)
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw 'Create .venv and install requirements.txt first; see docs/automation.md.'
}
if (-not $Slug) {
    if ($Resume) { throw 'Specify -Slug when using -Resume.' }
    $taskJobMatch = [regex]::Match($Url, '(?:currentJobId=|/jobs/view/(?:[^/?]*-)?)(\d{6,20})')
    $taskPrefix = if ($taskJobMatch.Success) { 'job-' + $taskJobMatch.Groups[1].Value } else { 'job' }
    $Slug = $taskPrefix + '-' + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss')
}
$taskOriginalPath = $env:PATH
try {
    $env:PATH = (Join-Path $PSScriptRoot '.venv\Scripts') + [IO.Path]::PathSeparator + $taskOriginalPath
    Push-Location $PSScriptRoot
    try {
        $taskArguments = @('-m','automation.run','--url',$Url,'--slug',$Slug,'--language',$Language)
        foreach ($taskOption in @(@('--provider',$Provider), @('--model',$Model), @('--config',$Config),
                                  @('--base-url',$BaseUrl), @('--api-key-env',$ApiKeyEnv), @('--job-text',$JobText))) {
            if ($taskOption[1]) { $taskArguments += $taskOption }
        }
        if ($Resume) { $taskArguments += '--resume' }
        & $taskPython @taskArguments
        if ($LASTEXITCODE -ne 0) { throw 'CV generation stopped. Review the stage reported above.' }
    } finally { Pop-Location }
} finally { $env:PATH = $taskOriginalPath }
