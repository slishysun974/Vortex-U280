[CmdletBinding()]
param(
    [switch]$BatchMode,
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$')]
    [string]$RunId = ('u280-account-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$serverAddress = '192.0.2.28'
$username = 'u280user'
$sshExecutable = Join-Path $env:WINDIR 'System32/OpenSSH/ssh.exe'
$pythonExecutable = 'C:/Users/example/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
$proxyScript = (Join-Path $PSScriptRoot 'wlan_ssh_proxy.py').Replace('\', '/')
$accessDirectory = Join-Path $projectRoot 'environment/server-access'
$knownHosts = (Join-Path $accessDirectory 'known_hosts').Replace('\', '/')
$runDirectory = Join-Path (Join-Path $projectRoot 'results') $RunId
if (Test-Path -LiteralPath $runDirectory) { throw 'Run directory exists; choose a new RunId.' }
$null = New-Item -ItemType Directory -Path $runDirectory
$null = New-Item -ItemType Directory -Path $accessDirectory -Force
$resultPath = Join-Path $runDirectory 'result.json'
$result = [ordered]@{
    schema_version = 'u280-account-check-v1'
    started_at = [DateTimeOffset]::Now.ToString('o')
    host = $serverAddress
    username = $username
    transport = 'WLAN-bound SSH; no global route or VPN changes'
    batch_mode = [bool]$BatchMode
    authentication = 'NOT_RUN'
    remote_command = 'id -un && hostname'
    board = 'NOT_RUN'
    scope = 'Login and account/host identification only; no tool install, device query or programming'
    exit_code = $null
}
$result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $resultPath -Encoding UTF8
try {
    $addresses = @(Get-NetIPAddress -InterfaceAlias WLAN -AddressFamily IPv4 |
        Where-Object { $_.AddressState -eq 'Preferred' -and $_.IPAddress -notlike '169.254.*' })
    if ($addresses.Count -ne 1) { throw 'Expected exactly one preferred WLAN IPv4 address.' }
    $address = $addresses[0]
    $result.source = $address.IPAddress
    $result.interface_index = $address.InterfaceIndex
    $proxyOption = 'ProxyCommand={0} -B "{1}" --host %h --port %p --interface {2} --source {3}' -f `
        $pythonExecutable, $proxyScript, $address.InterfaceIndex, $address.IPAddress
    $sshLog = Join-Path $runDirectory 'ssh.log'
    $sshArguments = @('-F', 'none', '-T', '-v', '-E', $sshLog,
        '-o', $proxyOption, '-o', "UserKnownHostsFile=$knownHosts",
        '-o', 'StrictHostKeyChecking=accept-new', '-o', 'ConnectTimeout=10',
        '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=2',
        '-o', 'PreferredAuthentications=password', '-o', 'PubkeyAuthentication=no',
        '-o', 'NumberOfPasswordPrompts=1')
    if ($BatchMode) { $sshArguments += @('-o', 'BatchMode=yes') }
    $sshArguments += @("$username@$serverAddress", $result.remote_command)
    $result.argv = @($sshExecutable) + $sshArguments
    $result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $resultPath -Encoding UTF8
    Write-Host 'Testing u280user on the documented U280 server. Only id/hostname will run.'
    if (-not $BatchMode) { Write-Host 'Enter your U280 account password at the SSH prompt; it is not logged.' }
    & $sshExecutable @sshArguments > (Join-Path $runDirectory 'identity.stdout')
    $sshExit = $LASTEXITCODE
    $result.exit_code = $sshExit
    # Read a plain string: Windows PowerShell 5.1 serializes Get-Content metadata too.
    $identity = [System.IO.File]::ReadAllText((Join-Path $runDirectory 'identity.stdout'))
    $result.identity_output = $identity
    if ($sshExit -eq 0 -and $identity -match '(?m)^u280user\s*$') {
        $result.authentication = 'PASS'
        Write-Host 'U280_ACCOUNT_LOGIN_PASS'
        Write-Host $identity
    } else {
        $result.authentication = if ($BatchMode) { 'BLOCKED' } else { 'FAIL' }
        $result.reason = if ($BatchMode) { 'No password submitted; interactive credential required if transport/host key succeeded.' } else { 'See ssh.log for actual failure; no retry performed.' }
    }
} catch {
    $result.error = $_.Exception.Message
    $result.exit_code = 1
    $result.authentication = 'BLOCKED'
} finally {
    $result.finished_at = [DateTimeOffset]::Now.ToString('o')
    $result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $resultPath -Encoding UTF8
    Write-Host ('Result: ' + $resultPath)
}
exit $result.exit_code
