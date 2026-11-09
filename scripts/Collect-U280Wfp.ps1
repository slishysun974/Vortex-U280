[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$')]
    [string]$RunId = ('u280-wfp-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$run = Join-Path (Join-Path $root 'results') $RunId
if (Test-Path -LiteralPath $run) { throw 'Existing diagnostic record must be preserved.' }
$null = New-Item -ItemType Directory -Path $run
Copy-Item -LiteralPath $PSCommandPath -Destination (Join-Path $run 'Collect-U280Wfp.ps1')
$result = [ordered]@{
    schema_version='u280-wfp-readonly-v1'; run_id=$RunId
    started_at=[DateTimeOffset]::Now.ToString('o')
    scope='Read-only WFP events for U280 TCP/22 and filters for its IP; no policy, VPN, routing or device changes'
    status='RUNNING'; commands=@(); exit_code=$null
}
$netsh = Join-Path $env:WINDIR 'System32/netsh.exe'
try {
    $items = @(
        @{label='events'; argv=@('wfp','show','netevents',('file=' + (Join-Path $run 'events.xml')),'protocol=6','remoteaddr=192.0.2.28','remoteport=22','timewindow=3600')},
        @{label='filters'; argv=@('wfp','show','filters',('file=' + (Join-Path $run 'filters.xml')),'protocol=6','remoteaddr=192.0.2.28','dir=out','verbose=on')}
    )
    foreach ($item in $items) {
        $arguments = $item.argv
        & $netsh @arguments > (Join-Path $run ($item.label + '.stdout')) 2> (Join-Path $run ($item.label + '.stderr'))
        $result.commands += [ordered]@{label=$item.label;argv=@($netsh)+$arguments;exit_code=$LASTEXITCODE}
    }
    $result.status = if (@($result.commands | Where-Object { $_.exit_code -ne 0 }).Count -eq 0) { 'PASS' } else { 'FAIL' }
    $result.exit_code = if ($result.status -eq 'PASS') { 0 } else { 1 }
} catch {
    $result.status='FAIL'; $result.exit_code=1; $result.error=$_.Exception.Message
} finally {
    $result.finished_at=[DateTimeOffset]::Now.ToString('o')
    $result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $run 'result.json') -Encoding utf8
}
exit $result.exit_code
