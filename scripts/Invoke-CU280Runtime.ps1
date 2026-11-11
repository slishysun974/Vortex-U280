[CmdletBinding()]
param(
    [switch]$PrepareOnly,
    [switch]$Prepared,
    [ValidatePattern('^c-runtime-merge-[A-Za-z0-9_.-]{1,70}$')]
    [string]$SourceRun,
    [ValidatePattern('^c-u280-runtime-[A-Za-z0-9_.-]{1,70}$')]
    [string]$RunId = ('c-u280-runtime-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff')),
    [ValidateSet('0000:b1:00.1','0000:b4:00.1','0000:3d:00.1','0000:40:00.1','0000:41:00.1')]
    [string]$Bdf = '0000:b1:00.1'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = 'C:/Users/example/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
$run = Join-Path (Join-Path $projectRoot 'results') $RunId
if (-not $Prepared) {
    if (-not $SourceRun) { throw 'SourceRun is required for fresh preparation.' }
    & $python -B (Join-Path $PSScriptRoot 'c_runtime_board.py') prepare $RunId --source-run $SourceRun --bdf $Bdf
    if ($LASTEXITCODE -ne 0) { throw 'C runtime board preparation failed.' }
}
$identity = Get-Content -LiteralPath (Join-Path $run 'preparation.json') -Raw | ConvertFrom-Json
if ($identity.run_id -ne $RunId -or $identity.bdf -ne $Bdf) { throw 'Prepared run identity/BDF differs.' }
$payloadPath = Join-Path $run 'payload.py'
if ((Get-FileHash -LiteralPath $payloadPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $identity.payload_sha256) {
    throw 'Prepared payload bytes changed.'
}
if ($PrepareOnly) { return }
$transportPath = Join-Path $run 'transport.json'
if (Test-Path -LiteralPath $transportPath) { throw 'Transport already attempted; create a new run.' }
$result = [ordered]@{run_id=$RunId;status='BLOCKED';exit_code=1;ssh_exit_code=$null;started_at=[DateTimeOffset]::Now.ToString('o')}
try {
    $knownHosts = (Join-Path $projectRoot 'environment/server-access/known_hosts').Replace('\','/')
    if (-not (Test-Path -LiteralPath $knownHosts)) { throw 'Verified known_hosts required.' }
    $addresses = @(Get-NetIPAddress -InterfaceAlias WLAN -AddressFamily IPv4 | Where-Object { $_.AddressState -eq 'Preferred' -and $_.IPAddress -notlike '169.254.*' })
    if ($addresses.Count -ne 1) { throw 'Expected one preferred WLAN IPv4 address.' }
    $address = $addresses[0]
    $proxy = (Join-Path $run 'wlan_ssh_proxy.py').Replace('\','/')
    $proxyOption = 'ProxyCommand={0} -B "{1}" --host %h --port %p --interface {2} --source {3}' -f $python,$proxy,$address.InterfaceIndex,$address.IPAddress
    $ssh = Join-Path $env:WINDIR 'System32/OpenSSH/ssh.exe'
    $remoteCommand = 'test "$(id -un)" = u280user && . /opt/xilinx/xrt/setup.sh >/dev/null && exec python3 -B -'
    $argv = @('-F','none','-T','-v','-E',(Join-Path $run 'ssh.log'),'-o',$proxyOption,
        '-o',"UserKnownHostsFile=$knownHosts",'-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=10',
        '-o','ServerAliveInterval=15','-o','ServerAliveCountMax=2','-o','PreferredAuthentications=password',
        '-o','PubkeyAuthentication=no','-o','NumberOfPasswordPrompts=1','u280user@192.0.2.28',$remoteCommand)
    $result.argv = @($ssh) + $argv
    $result.status = 'RUNNING'
    $result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $transportPath -Encoding UTF8
    Write-Host 'Enter the U280 password only at the SSH password prompt. Do not send it to chat.'
    Write-Host "Runs the merged C runtime on ${Bdf}: 41 valid launches in three contexts, with fresh open/close gates. No fault injection or system changes."
    [IO.File]::ReadAllText($payloadPath) | & $ssh @argv > (Join-Path $run 'probe.stdout')
    $result.ssh_exit_code = $LASTEXITCODE
    if ($result.ssh_exit_code -ne 0) { throw "SSH exited $($result.ssh_exit_code)." }
    & $python -B (Join-Path $run 'c_runtime_board.py') unpack $RunId
    $result.exit_code = $LASTEXITCODE
    $received = Get-Content -LiteralPath (Join-Path $run 'result.json') -Raw | ConvertFrom-Json
    $result.status = $received.status
    Write-Host ("C Runtime U280: " + $received.status + ' ' + $received.error)
} catch {
    $result.status = if ($result.ssh_exit_code -eq 0) { 'FAIL' } else { 'BLOCKED' }
    $result.error = $_.Exception.Message
    Write-Host $result.error
} finally {
    $result.finished_at = [DateTimeOffset]::Now.ToString('o')
    $result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $transportPath -Encoding UTF8
    Write-Host ('Result: ' + $transportPath)
}
exit $result.exit_code
