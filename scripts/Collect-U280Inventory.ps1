[CmdletBinding()]
param(
    [switch]$PrepareOnly,
    [switch]$ToolChecks,
    [switch]$BatchMode,
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$')]
    [string]$RunId = ('u280-inventory-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runDirectory = Join-Path (Join-Path $projectRoot 'results') $RunId
if (Test-Path -LiteralPath $runDirectory) { throw 'Run directory exists; choose a new RunId.' }
$null = New-Item -ItemType Directory -Path $runDirectory
$resultPath = Join-Path $runDirectory 'result.json'
$utf8 = New-Object System.Text.UTF8Encoding($false)
$nonce = [Guid]::NewGuid().ToString('N')
$result = [ordered]@{
    schema_version = 'u280-readonly-inventory-v3'
    started_at = [DateTimeOffset]::Now.ToString('o')
    host = '192.0.2.28'; username = 'u280user'
    status = 'NOT_RUN'; exit_code = $null
    scope = 'Read-only host inventory; visible PCI functions are not allocated cards'
    card_allocation = 'UNCONFIRMED'; device_query = 'NOT_RUN'
    fpga_build = 'NOT_RUN'; board_execution = 'NOT_RUN'
    nonce = $nonce; prepare_only = [bool]$PrepareOnly
    tool_checks_requested = [bool]$ToolChecks
}
try {
    foreach ($name in @('platform_inventory.py', 'wlan_ssh_proxy.py', 'Collect-U280Inventory.ps1')) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $runDirectory
    }
    $collectorPath = Join-Path $runDirectory 'platform_inventory.py'
    $collectorHash = (Get-FileHash -LiteralPath $collectorPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $collector64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($collectorPath))
    # ASCII payload travels over SSH stdin; the password is read separately by OpenSSH.
    # Default: no commercial tools or setup scripts. Optional ToolChecks only
    # starts version/platform-file queries in child shells, never device queries.
    $toolChecksPython = if ($ToolChecks) { 'True' } else { 'False' }
    $payload = @"
import argparse, base64, hashlib, json, os, pwd, sys
source = base64.b64decode('$collector64')
assert hashlib.sha256(source).hexdigest() == '$collectorHash'
namespace = {'__name__': 'inventory_payload'}
exec(compile(source, 'platform_inventory.py', 'exec'), namespace)
report = namespace['collect'](argparse.Namespace(timeout=5, include_device_query=False))
report['transport_identity'] = {'username': pwd.getpwuid(os.getuid()).pw_name, 'uid': os.getuid()}
report['collector_sha256'] = '$collectorHash'
report['nonce'] = '$nonce'
report['rpm_packages'] = namespace['command'](['rpm', '-q', 'xrt', 'xrt-core', 'xrt-dev'], 5)
report['tool_environment'] = {k: os.environ.get(k) for k in ('XILINX_VITIS', 'XILINX_VIVADO', 'XILINX_XRT', 'PLATFORM_REPO_PATHS')}
report['card_allocation'] = 'UNCONFIRMED'
report['personal_resource_quota'] = 'UNCONFIRMED; machine totals are visibility only'
report['glibc_confstr'] = os.confstr('CS_GNU_LIBC_VERSION')
report['documented_tool_paths'] = [namespace['directory'](p) for p in (
    '/apps', '/apps/Xilinx2023', '/apps/Xilinx2023/Vivado/2023.1',
    '/apps/Xilinx2023/Vitis/2023.1', '/apps/Xilinx2023/Vivado/2023.1/bin',
    '/apps/Xilinx2023/Vitis/2023.1/bin', '/opt/rh', '/opt/xilinx/xrt/bin',
    '/opt/xilinx/platforms/xilinx_u280_gen3x16_xdma_1_202211_1')]
report['metadata_files'] = [namespace['read_file'](p) for p in (
    '/opt/xilinx/xrt/version.json',
    '/opt/xilinx/platforms/xilinx_u280_gen3x16_xdma_1_202211_1/xilinx_u280_gen3x16_xdma_1_202211_1.xpfm')]
report['environment_script_identities'] = []
for path in ('/apps/Xilinx2023/Vivado/2023.1/settings64.sh',
             '/apps/Xilinx2023/Vitis/2023.1/settings64.sh', '/opt/xilinx/xrt/setup.sh'):
    item = {'path': path, 'executed': False}
    try:
        with open(path, 'rb') as stream:
            raw = stream.read(1048577)
        item.update(status='PASS', bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        if len(raw) > 1048576:
            item.update(status='FAIL', reason='metadata size limit')
    except OSError as exc:
        item.update(status='BLOCKED', error=str(exc))
    report['environment_script_identities'].append(item)
report['tool_checks'] = {'status': 'NOT_RUN', 'license_acceptance': 'NOT_RUN'}
if $toolChecksPython :
    setup = '. /apps/Xilinx2023/Vitis/2023.1/settings64.sh >/dev/null && . /opt/xilinx/xrt/setup.sh >/dev/null && '
    checks = {}
    for label, command_text in (
        ('vivado_version', 'exec vivado -version'),
        ('vitis_compiler_version', 'exec v++ --version'),
        ('platform_file_info', 'exec platforminfo -p /opt/xilinx/platforms/xilinx_u280_gen3x16_xdma_1_202211_1/xilinx_u280_gen3x16_xdma_1_202211_1.xpfm'),
        ('xrt_version', 'exec /opt/xilinx/xrt/bin/xbutil --version')):
        checks[label] = namespace['command'](['bash', '-c', setup + command_text], 60)
    report['tool_checks'] = {'status': 'PASS' if all(c['status'] == 'PASS' for c in checks.values()) else 'FAIL',
        'scope': 'Version and installed platform-file inspection; no board opened or queried',
        'license_acceptance': 'NOT_RUN', 'commands': checks}
print('U280_INVENTORY_BEGIN_$nonce')
print(json.dumps(report, ensure_ascii=True, indent=2))
print('U280_INVENTORY_END_$nonce')
sys.exit(0 if report['status'] == 'PASS' and report['transport_identity']['username'] == 'u280user' else 2)
"@
    [IO.File]::WriteAllText((Join-Path $runDirectory 'payload.py'), $payload, $utf8)
    $result.collector_sha256 = $collectorHash
    $result.payload_sha256 = (Get-FileHash -LiteralPath (Join-Path $runDirectory 'payload.py') -Algorithm SHA256).Hash.ToLowerInvariant()
    $result.remote_command = 'test "$(id -un)" = u280user && exec python3 -B -'
    if ($PrepareOnly) {
        $result.reason = 'Payload prepared offline; no SSH or inventory executed.'
        $result.exit_code = 0
    } else {
        $sshExecutable = Join-Path $env:WINDIR 'System32/OpenSSH/ssh.exe'
        $pythonExecutable = 'C:/Users/example/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
        $knownHosts = (Join-Path $projectRoot 'environment/server-access/known_hosts').Replace('\', '/')
        if (-not (Test-Path -LiteralPath $knownHosts)) { throw 'Previously verified known_hosts is required.' }
        $addresses = @(Get-NetIPAddress -InterfaceAlias WLAN -AddressFamily IPv4 |
            Where-Object { $_.AddressState -eq 'Preferred' -and $_.IPAddress -notlike '169.254.*' })
        if ($addresses.Count -ne 1) { throw 'Expected exactly one preferred WLAN IPv4 address.' }
        $address = $addresses[0]
        $result.source = $address.IPAddress
        $result.interface_index = $address.InterfaceIndex
        $proxyPath = (Join-Path $runDirectory 'wlan_ssh_proxy.py').Replace('\', '/')
        $proxyOption = 'ProxyCommand={0} -B "{1}" --host %h --port %p --interface {2} --source {3}' -f $pythonExecutable, $proxyPath, $address.InterfaceIndex, $address.IPAddress
        $sshArguments = @('-F', 'none', '-T', '-v', '-E', (Join-Path $runDirectory 'ssh.log'),
            '-o', $proxyOption, '-o', "UserKnownHostsFile=$knownHosts",
            '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10',
            '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=2',
            '-o', 'PreferredAuthentications=password', '-o', 'PubkeyAuthentication=no',
            '-o', 'NumberOfPasswordPrompts=1')
        if ($BatchMode) { $sshArguments += @('-o', 'BatchMode=yes') }
        $sshArguments += @('u280user@192.0.2.28', $result.remote_command)
        $result.argv = @($sshExecutable) + $sshArguments
        $result.status = 'RUNNING'
        $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $resultPath -Encoding UTF8
        Write-Host 'Read-only host inventory. No board opens, programming, resets or installation.'
        if ($ToolChecks) { Write-Host 'Also running tool versions and platform-file inspection in child shells.' }
        if (-not $BatchMode) { Write-Host 'Enter your current password at the SSH prompt. Do not send it to chat.' }
        $stdoutPath = Join-Path $runDirectory 'inventory.stdout'
        $payload | & $sshExecutable @sshArguments > $stdoutPath
        $result.exit_code = $LASTEXITCODE
        $raw = [IO.File]::ReadAllText($stdoutPath)
        $result.stdout_sha256 = (Get-FileHash -LiteralPath $stdoutPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($result.exit_code -ne 0) { throw ('SSH/remote collector exited ' + $result.exit_code) }
        $begin = 'U280_INVENTORY_BEGIN_' + $nonce
        $end = 'U280_INVENTORY_END_' + $nonce
        $start = $raw.IndexOf($begin)
        $finish = $raw.IndexOf($end)
        if ($start -lt 0 -or $finish -le $start) { throw 'Missing inventory framing.' }
        $jsonText = $raw.Substring($start + $begin.Length, $finish - $start - $begin.Length).Trim()
        $inventory = $jsonText | ConvertFrom-Json
        if ($inventory.nonce -ne $nonce -or $inventory.collector_sha256 -ne $collectorHash -or
            $inventory.transport_identity.username -ne 'u280user' -or $inventory.status -ne 'PASS' -or
            $inventory.device_query_requested -ne $false -or $inventory.device_mutations_performed -ne $false) {
            throw 'Inventory identity or scope check failed.'
        }
        [IO.File]::WriteAllText((Join-Path $runDirectory 'inventory.json'), $jsonText + "`n", $utf8)
        $result.status = 'PASS'
        $result.status_scope = 'Authenticated host inventory collection only; component findings remain separate'
        $result.hostname = [string]$inventory.hostname
        $result.inventory_sha256 = (Get-FileHash -LiteralPath (Join-Path $runDirectory 'inventory.json') -Algorithm SHA256).Hash.ToLowerInvariant()
        Write-Host 'U280_READONLY_INVENTORY_PASS'
    }
} catch {
    $result.status = if ($result.status -eq 'RUNNING') { 'FAIL' } else { 'BLOCKED' }
    $result.reason = $_.Exception.Message
    if ($null -eq $result.exit_code -or $result.exit_code -eq 0) { $result.exit_code = 1 }
    Write-Host $result.reason
} finally {
    $result.finished_at = [DateTimeOffset]::Now.ToString('o')
    $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $resultPath -Encoding UTF8
    Write-Host ('Result: ' + $resultPath)
}
exit $result.exit_code
