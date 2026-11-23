[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidatePattern('^(?:c-v03-u280-|u280-aligned-|iris-board-)[A-Za-z0-9_-]{1,50}$')]
    [string]$RunId,
    [Parameter(Mandatory=$true)]
    [ValidatePattern('^[a-zA-Z0-9.-]+$')]
    [string]$Server,
    [Parameter(Mandatory=$true)]
    [ValidatePattern('^[a-zA-Z0-9_-]+$')]
    [string]$Account
)

$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$run = Join-Path (Join-Path $project 'results') $RunId
$prep = Get-Content -LiteralPath (Join-Path $run 'preparation.json') -Raw | ConvertFrom-Json
$payload = Join-Path $run 'payload.py'
$receiptPath = Join-Path $run 'transport.json'
if ($prep.status -ne 'PASS' -or $prep.run_id -ne $RunId -or
    (Get-FileHash -LiteralPath $payload -Algorithm SHA256).Hash.ToLowerInvariant() -ne $prep.payload_sha256) {
    throw 'Prepared payload identity differs.'
}
if (Test-Path -LiteralPath $receiptPath) { throw 'Transport already attempted; use a fresh run ID.' }

$result = [ordered]@{run_id=$RunId;status='BLOCKED';exit_code=1;ssh_exit_code=$null;started_at=[DateTimeOffset]::Now.ToString('o')}
try {
    $knownHosts = (Join-Path $project 'environment/server-access/known_hosts').Replace('\','/')
    if (-not (Test-Path -LiteralPath $knownHosts)) { throw 'Verified known_hosts required.' }
    $addresses = @(Get-NetIPAddress -InterfaceAlias WLAN -AddressFamily IPv4 | Where-Object { $_.AddressState -eq 'Preferred' -and $_.IPAddress -notlike '169.254.*' })
    if ($addresses.Count -ne 1) { throw 'Expected one preferred WLAN IPv4 address.' }
    $address = $addresses[0]
    $python = (Get-Command python.exe -ErrorAction Stop).Source
    $proxy = (Join-Path $PSScriptRoot 'wlan_ssh_proxy.py').Replace('\','/')
    $proxyOption = 'ProxyCommand={0} -B "{1}" --host %h --port %p --interface {2} --source {3}' -f $python.Replace('\','/'),$proxy,$address.InterfaceIndex,$address.IPAddress
    $ssh = Join-Path $env:WINDIR 'System32/OpenSSH/ssh.exe'
    # ReadAllText is safe here because the prepared payload is ASCII and hash checked.
    $remote = 'set -e; test "$(id -un)" = ' + $Account + ' && . /opt/xilinx/xrt/setup.sh >/dev/null && exec python3 -B -'
    $arguments = @('-F','none','-T','-v','-E',(Join-Path $run 'ssh.log'),'-o',$proxyOption,
        '-o',"UserKnownHostsFile=$knownHosts",'-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=10',
        '-o','ServerAliveInterval=15','-o','ServerAliveCountMax=2','-o','PreferredAuthentications=password',
        '-o','PubkeyAuthentication=no','-o','NumberOfPasswordPrompts=1',"$Account@$Server",$remote)
    $result.argv = @($ssh) + $arguments
    $result.status = 'RUNNING'
    $result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
    Write-Host 'U280 board run. Enter the account password only at the SSH prompt.'
    [IO.File]::ReadAllText($payload) | & $ssh @arguments > (Join-Path $run 'probe.stdout')
    $result.ssh_exit_code = $LASTEXITCODE
    if ($result.ssh_exit_code -ne 0) { throw "SSH exited $($result.ssh_exit_code); see ssh.log." }
    & $python -B (Join-Path $PSScriptRoot 'c_v03_board_transport.py') unpack $RunId
    $result.exit_code = $LASTEXITCODE
    $receipt = Get-Content -LiteralPath (Join-Path $run 'result.json') -Raw | ConvertFrom-Json
    $result.status = $receipt.status
    $result.board_execution = $receipt.board_execution
} catch {
    $result.status = if ($result.ssh_exit_code -eq 0) { 'FAIL' } else { 'BLOCKED' }
    $result.error = $_.Exception.Message
} finally {
    $result.finished_at = [DateTimeOffset]::Now.ToString('o')
    $result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
    Write-Host ($result.status + ' ' + $receiptPath)
    if ($result.error) { Write-Host $result.error }
}
exit $result.exit_code
