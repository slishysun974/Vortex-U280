[CmdletBinding()]
param(
    [switch]$PrepareOnly,
    [switch]$TimingOnly,
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$')]
    [string]$RunId = ('u280-readiness-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = 'C:/Users/example/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
$prepareArgs = @('-B', (Join-Path $PSScriptRoot 'prepare_u280_readiness.py'), $RunId)
if ($TimingOnly) { $prepareArgs += '--timing-only' }
& $python @prepareArgs
if ($LASTEXITCODE -ne 0) { throw 'Readiness request preparation failed.' }
$run = Join-Path (Join-Path $projectRoot 'results') $RunId
$resultPath = Join-Path $run 'transport.json'
$result = [ordered]@{
    schema_version='u280-readiness-transport-v1'; run_id=$RunId; status='NOT_RUN'; exit_code=$null
    started_at=[DateTimeOffset]::Now.ToString('o')
    scope='Configure 256 MiB HOST on one currently idle card; audit existing DCPs using two CPUs; no xclbin load or kernel execution'
    authentication_session_recorded=$false
}
if ($TimingOnly) { $result.scope = 'Read-only existing DCP audit using two CPUs; no sudo, HOST change, xclbin load, or kernel execution' }
try {
    if ($PrepareOnly) {
        $result.exit_code = 0
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
        $options = @('-F','none','-o',$proxyOption,'-o',"UserKnownHostsFile=$knownHosts",'-o','StrictHostKeyChecking=yes',
            '-o','ConnectTimeout=10','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=2',
            '-o','PreferredAuthentications=password','-o','PubkeyAuthentication=no','-o','NumberOfPasswordPrompts=1')
        $result.status = 'RUNNING'
        $result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $resultPath -Encoding UTF8
        Write-Host $result.scope
        Write-Host 'Enter SSH password only at password:. Never send passwords to chat.'
        Write-Host 'Timing audit may take up to 30 minutes.'
        $command = [IO.File]::ReadAllText((Join-Path $run 'interactive_command.txt'))
        if ($TimingOnly) {
            & $ssh @options -T 'u280user@192.0.2.28' $command > (Join-Path $run 'probe.stdout')
            $result.operation_ssh_exit_code = $LASTEXITCODE
        } else {
            Write-Host 'sudo may ask for a password next. Collection asks for SSH password again after the audit.'
            # The sudo credential session inherits the visible terminal; never pipe/transcribe it.
            & $ssh @options -tt 'u280user@192.0.2.28' $command
            $result.operation_ssh_exit_code = $LASTEXITCODE
            $result.stage = 'COLLECTING'
            $result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $resultPath -Encoding UTF8
            Write-Host 'Collecting recorded results; enter SSH password at the prompt once more.'
            [IO.File]::ReadAllText((Join-Path $run 'collector.py')) | & $ssh @options -T 'u280user@192.0.2.28' 'exec python3 -B -' > (Join-Path $run 'probe.stdout')
            $result.collection_ssh_exit_code = $LASTEXITCODE
            if ($result.collection_ssh_exit_code -ne 0) { throw ('Result collection SSH exited ' + $result.collection_ssh_exit_code) }
        }
        & $python -B (Join-Path $run 'prepare_u280_probe.py') unpack $RunId
        $result.exit_code = $LASTEXITCODE
        if (Test-Path -LiteralPath (Join-Path $run 'probe.json')) {
            $probe = Get-Content -LiteralPath (Join-Path $run 'probe.json') -Raw | ConvertFrom-Json
            $result.host_configuration = $probe.host_configuration
            $result.timing_collection = $probe.timing_collection
            Write-Host ('HOST: ' + $probe.host_configuration + '; timing collection: ' + $probe.timing_collection)
        }
        $result.status = if ($result.exit_code -eq 0 -and $result.operation_ssh_exit_code -eq 0) { 'PASS' } else { 'FAIL' }
    }
} catch {
    $result.status = 'FAIL'
    $result.error = $_.Exception.Message
    $result.exit_code = 1
} finally {
    $result.finished_at = [DateTimeOffset]::Now.ToString('o')
    $result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $resultPath -Encoding UTF8
    Write-Host ('Result: ' + $resultPath)
}
exit $result.exit_code
