#Requires -Version 5.1
<#
.SYNOPSIS
  Deletes career memory rows (documents, facts, questions, timeline, discovery profile) for one tenant.

.DESCRIPTION
  Uses PostgreSQL client ``psql`` when it is on PATH; otherwise runs
  ``scripts/clear_career_memory_tenant.py`` with ``backend\.venv\Scripts\python.exe``
  (SQLAlchemy + psycopg — same as the app).

  URL resolution order: non-empty ``-DatabaseUrl``, then ``ATLAS_DATABASE_URL`` from
  ``-EnvFile`` (last assignment wins), then ``$env:ATLAS_DATABASE_URL``. Use ``-EnvFile``
  when your shell still has an old connection string.

.EXAMPLE
  $env:ATLAS_DATABASE_URL = 'postgresql://user:pass@127.0.0.1:5432/atlas'
  .\scripts\clear-career-memory-tenant.ps1

.EXAMPLE
  .\scripts\clear-career-memory-tenant.ps1 -EnvFile .env -UserId 'YOUR-USER-UUID'
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [string]$UserId = 'd713ee46-77c9-50cb-ac74-17fa99329375',

    [string]$DatabaseUrl = '',

    [string]$EnvFile = '',

    [switch]$SkipHostnamePlaceholderCheck
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$resolvedDb = ($DatabaseUrl | ForEach-Object { $_.Trim() }) -join ''
if (-not $resolvedDb -and $EnvFile) {
    if (-not (Test-Path -LiteralPath $EnvFile)) {
        throw "Env file not found: $EnvFile"
    }
    foreach ($line in Get-Content -LiteralPath $EnvFile) {
        $t = $line.Trim()
        if ($t -eq '' -or $t.StartsWith('#')) { continue }
        if ($t -match '^\s*ATLAS_DATABASE_URL\s*=\s*(.+)\s*$') {
            # Last assignment wins (matches common .env expectations).
            $resolvedDb = $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
}
if (-not $resolvedDb) {
    $resolvedDb = $env:ATLAS_DATABASE_URL
}
if (-not $resolvedDb) {
    throw 'Pass -DatabaseUrl, set $env:ATLAS_DATABASE_URL, or use -EnvFile with ATLAS_DATABASE_URL.'
}

$guid = [guid]::Parse($UserId)

if (-not $PSCmdlet.ShouldProcess("tenant $guid", 'Delete career memory rows')) {
    return
}

$psql = Get-Command psql -ErrorAction SilentlyContinue
$backendRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $backendRoot '.venv\Scripts\python.exe'
$pyScript = Join-Path $PSScriptRoot 'clear_career_memory_tenant.py'

if ($psql) {
    $sql = @"
BEGIN;

DELETE FROM career_profile_questions
WHERE user_id = '$guid';

DELETE FROM career_facts
WHERE user_id = '$guid';

DELETE FROM career_timeline_entries
WHERE user_id = '$guid';

DELETE FROM career_discovery_profiles
WHERE user_id = '$guid';

DELETE FROM career_documents
WHERE user_id = '$guid';

COMMIT;
"@
    $sql | & $psql.Source $resolvedDb -v ON_ERROR_STOP=1

    if ($LASTEXITCODE -ne 0) {
        throw "psql exited with code $LASTEXITCODE"
    }
    Write-Host "Career memory cleared for user_id=$guid"
}
elseif (Test-Path -LiteralPath $venvPython) {
    $pyArgs = @(
        $pyScript
        '--user-id'
        $guid
        '--database-url'
        $resolvedDb
    )
    if ($SkipHostnamePlaceholderCheck) {
        $pyArgs += '--skip-hostname-placeholder-check'
    }
    & $venvPython @pyArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Python clear script exited with code $LASTEXITCODE"
    }
}
else {
    throw @(
        'Neither psql nor backend\.venv\Scripts\python.exe was found.'
        ' Install PostgreSQL client tools, or create the backend venv (`python -m venv .venv` + pip install -r requirements.txt).'
    ) -join ' '
}
