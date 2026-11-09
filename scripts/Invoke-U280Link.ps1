[CmdletBinding()]
param(
    [ValidateSet('Start','Status','Archive')]
    [string]$Mode = 'Start',
    [string]$BuildRun,
    [switch]$PrepareOnly,
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$')]
    [string]$RunId = ('u280-link-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = 'C:/Users/example/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if ($Mode -eq 'Start' -and -not $BuildRun) { $BuildRun = $RunId }
if (-not $BuildRun) { throw 'Status requires -BuildRun with the existing job run ID.' }
& $python -B (Join-Path $PSScriptRoot 'prepare_u280_link.py') $RunId --mode $Mode.ToLowerInvariant() --build-run $BuildRun
if ($LASTEXITCODE -ne 0) { throw 'Link request preparation failed.' }
$run = Join-Path (Join-Path $projectRoot 'results') $RunId
$resultPath = Join-Path $run 'transport.json'
$result = [ordered]@{
    schema_version='u280-link-transport-v1'; run_id=$RunId; build_run=$BuildRun; mode=$Mode
    host='192.0.2.28'; username='u280user'; status='NOT_RUN'; exit_code=$null
    started_at=[DateTimeOffset]::Now.ToString('o')
    scope=$(if ($Mode -eq 'Start') { 'Approved detached link: 2 CPUs, nice +10, 6-hour v++ timeout; no RAM hard cap; no card loading or HOST changes' } elseif ($Mode -eq 'Archive') { 'Archive completed D10 xclbin/reports and inspect installed runtime prerequisites; no card loading or HOST changes' } else { 'Read-only observation of the existing link job; no new build' })
}
try {
    if ($PrepareOnly) {
        $result.exit_code = 0
        $result.reason = 'Prepared offline; SSH and link NOT_RUN.'
    } else {
        $knownHosts = (Join-Path $projectRoot 'environment/server-access/known_hosts').Replace('\','/')
        if (-not (Test-Path -LiteralPath $knownHosts)) { throw 'Verified known_hosts required.' }
        $addresses = @(Get-NetIPAddress -InterfaceAlias WLAN -AddressFamily IPv4 |
            Where-Object { $_.AddressState -eq 'Preferred' -and $_.IPAddress -notlike '169.254.*' })
        if ($addresses.Count -ne 1) { throw 'Expected exactly one WLAN IPv4 address.' }
        $address = $addresses[0]
        $proxy = (Join-Path $run 'wlan_ssh_proxy.py').Replace('\','/')
        $proxyOption = 'ProxyCommand={0} -B "{1}" --host %h --port %p --interface {2} --source {3}' -f $python,$proxy,$address.InterfaceIndex,$address.IPAddress
        $ssh = Join-Path $env:WINDIR 'System32/OpenSSH/ssh.exe'
        $command = 'test "$(id -un)" = u280user && exec python3 -B -'
        $argv = @('-F','none','-T','-v','-E',(Join-Path $run 'ssh.log'),
            '-o',$proxyOption,'-o',"UserKnownHostsFile=$knownHosts",'-o','StrictHostKeyChecking=yes',
            '-o','ConnectTimeout=10','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=2',
            '-o','PreferredAuthentications=password','-o','PubkeyAuthentication=no','-o','NumberOfPasswordPrompts=1',
            'u280user@192.0.2.28',$command)
        $result.argv = @($ssh) + $argv
        $result.status = 'RUNNING'
        $result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $resultPath -Encoding UTF8
        Write-Host $result.scope
        Write-Host 'Enter current SSH password locally; do not send it to chat. No password is saved.'
        [IO.File]::ReadAllText((Join-Path $run 'payload.py')) | & $ssh @argv > (Join-Path $run 'probe.stdout')
        $result.ssh_exit_code = $LASTEXITCODE
        if ($result.ssh_exit_code -ne 0) { throw ('SSH exited ' + $result.ssh_exit_code) }
        & $python -B (Join-Path $run 'prepare_u280_probe.py') unpack $RunId
        $result.exit_code = $LASTEXITCODE
        $probePath = Join-Path $run 'probe.json'
        if (Test-Path -LiteralPath $probePath) {
            $probe = Get-Content -LiteralPath $probePath -Raw | ConvertFrom-Json
            $result.build_status = $probe.build_status
            $result.status_scope = $probe.status_scope
            Write-Host ('Build ' + $BuildRun + ': ' + $result.build_status + ' (transport success is not build completion)')
        }
        $result.status = if ($result.exit_code -eq 0) { 'PASS' } else { 'FAIL' }
    }
} catch {
    $result.status = if ($result.status -eq 'RUNNING') { 'FAIL' } else { 'BLOCKED' }
    $result.error = $_.Exception.Message
    $result.exit_code = 1
} finally {
    $result.finished_at = [DateTimeOffset]::Now.ToString('o')
    $result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $resultPath -Encoding UTF8
    Write-Host ('Result: ' + $resultPath)
}
exit $result.exit_code
