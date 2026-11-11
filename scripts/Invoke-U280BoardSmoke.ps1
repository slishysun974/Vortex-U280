[CmdletBinding()]
param(
    [switch]$PrepareOnly,
    [switch]$Regression,
    [switch]$PtxSuite,
    [switch]$PtxRegression,
    [ValidatePattern('^ptx-boundaries-[A-Za-z0-9_.-]{1,64}$')]
    [string]$PtxBoundaryRun,
    [ValidatePattern('^ptx-sequence-[A-Za-z0-9_.-]{1,64}$')]
    [string]$PtxSequenceRun,
    [ValidatePattern('^ptx-copy-[A-Za-z0-9_.-]{1,70}$')]
    [string]$PtxCopyRun,
    [ValidatePattern('^ptx-(copy-trace|arithmetic)-[A-Za-z0-9_.-]{1,64}$')]
    [string]$PtxDeviceRun,
    [ValidateSet('copy_u32','vadd_u32','affine_u32')]
    [string]$PtxEntry,
    [ValidatePattern('^[0-9]{4}$')]
    [string]$PtxCase,
    [ValidatePattern('^u280-board-(smoke|regression|ptx-copy|ptx-device|ptx-suite|ptx-regression|ptx-sequence|ptx-boundaries)-[A-Za-z0-9_.-]{1,70}$')]
    [string]$RunId
)
$ErrorActionPreference = 'Stop'
if (@($Regression, $PtxCopyRun, $PtxDeviceRun, $PtxSuite, $PtxRegression, $PtxSequenceRun, $PtxBoundaryRun).Where({ $_ }).Count -gt 1) { throw 'Choose one board test mode.' }
if (($PtxDeviceRun -and (-not $PtxEntry -or -not $PtxCase)) -or ((-not $PtxDeviceRun) -and ($PtxEntry -or $PtxCase))) {
    throw 'Use PtxDeviceRun, PtxEntry and PtxCase together.'
}
$mode = if ($PtxBoundaryRun) { 'ptx-boundaries' } elseif ($PtxSequenceRun) { 'ptx-sequence' } elseif ($PtxRegression) { 'ptx-regression' } elseif ($PtxSuite) { 'ptx-suite' } elseif ($PtxDeviceRun) { 'ptx-device' } elseif ($PtxCopyRun) { 'ptx-copy' } elseif ($Regression) { 'regression' } else { 'smoke' }
if (-not $RunId) { $RunId = "u280-board-$mode-" + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') }
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = 'C:/Users/example/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
$prepareArgs = @('-B', (Join-Path $PSScriptRoot 'u280_board_smoke.py'), $RunId, '--mode', $mode)
if ($PtxCopyRun) { $prepareArgs += @('--ptx-run', $PtxCopyRun) }
if ($PtxSequenceRun) { $prepareArgs += @('--ptx-run', $PtxSequenceRun) }
if ($PtxBoundaryRun) { $prepareArgs += @('--ptx-run', $PtxBoundaryRun) }
if ($PtxDeviceRun) { $prepareArgs += @('--ptx-run', $PtxDeviceRun, '--ptx-entry', $PtxEntry, '--ptx-case', $PtxCase) }
& $python @prepareArgs
if ($LASTEXITCODE -ne 0) { throw 'Board test input preparation failed.' }
$run = Join-Path (Join-Path $projectRoot 'results') $RunId
if ($PrepareOnly) { return }
$resultPath = Join-Path $run 'transport.json'
$result = [ordered]@{
    run_id = $RunId
    mode = $mode
    status = 'BLOCKED'
    started_at = [DateTimeOffset]::Now.ToString('o')
    ssh_exit_code = $null
    exit_code = 1
}
try {
    $knownHosts = (Join-Path $projectRoot 'environment/server-access/known_hosts').Replace('\','/')
    if (-not (Test-Path -LiteralPath $knownHosts)) { throw 'Verified known_hosts required.' }
    $addresses = @(Get-NetIPAddress -InterfaceAlias WLAN -AddressFamily IPv4 |
        Where-Object { $_.AddressState -eq 'Preferred' -and $_.IPAddress -notlike '169.254.*' })
    if ($addresses.Count -ne 1) { throw 'Expected exactly one preferred WLAN IPv4 address.' }
    $address = $addresses[0]
    $proxy = (Join-Path $run 'wlan_ssh_proxy.py').Replace('\','/')
    $proxyOption = 'ProxyCommand={0} -B "{1}" --host %h --port %p --interface {2} --source {3}' -f $python,$proxy,$address.InterfaceIndex,$address.IPAddress
    $ssh = Join-Path $env:WINDIR 'System32/OpenSSH/ssh.exe'
    $command = 'test "$(id -un)" = u280user && . /opt/xilinx/xrt/setup.sh >/dev/null && exec python3 -B -'
    $argv = @('-F','none','-T','-v','-E',(Join-Path $run 'ssh.log'),
        '-o',$proxyOption,'-o',"UserKnownHostsFile=$knownHosts",'-o','StrictHostKeyChecking=yes',
        '-o','ConnectTimeout=10','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=2',
        '-o','PreferredAuthentications=password','-o','PubkeyAuthentication=no','-o','NumberOfPasswordPrompts=1',
        'u280user@192.0.2.28',$command)
    $result.argv = @($ssh) + $argv
    $result.status = 'RUNNING'
    $result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $resultPath -Encoding UTF8
    $scope = if ($PtxBoundaryRun) { '67 PTX boundary cases, with a fresh idle gate on the same card before each case' } elseif ($PtxSequenceRun) { '30 PTX launches in one device context, buffer reuse/reallocation and 12 pre-submit rejections' } elseif ($PtxRegression) { '15 frozen PTX cases, with a fresh idle gate on the same card before each case' } elseif ($PtxSuite) { 'three PTX cases in order, with a fresh idle gate on the same card before each case' } elseif ($PtxDeviceRun) { "PTX $PtxEntry case $PtxCase" } elseif ($PtxCopyRun) { 'one PTX copy case' } elseif ($Regression) { '152 frozen native cases' } else { 'one native copy case' }
    Write-Host "Enter your U280 password at the native SSH prompt. The probe will use one card and $scope."
    [IO.File]::ReadAllText((Join-Path $run 'payload.py')) | & $ssh @argv > (Join-Path $run 'probe.stdout')
    $result.ssh_exit_code = $LASTEXITCODE
    $raw = [IO.File]::ReadAllText((Join-Path $run 'probe.stdout'))
    if ($result.ssh_exit_code -ne 0) { throw "SSH exited $($result.ssh_exit_code)." }
    $identity = Get-Content -LiteralPath (Join-Path $run 'preparation.json') -Raw | ConvertFrom-Json
    $frame = [regex]::Match($raw, '(?ms)^U280_SMOKE_BEGIN_' + $identity.nonce + '\r?\n(.*?)^U280_SMOKE_END_' + $identity.nonce + '\s*$')
    if (-not $frame.Success) { throw 'Missing remote result framing.' }
    $probe = $frame.Groups[1].Value | ConvertFrom-Json
    if ($probe.run_id -ne $RunId -or $probe.mode -ne $mode -or $probe.nonce -ne $identity.nonce -or $probe.script_sha256 -ne $identity.script_sha256) {
        throw 'Remote result identity mismatch.'
    }
    [IO.File]::WriteAllText((Join-Path $run 'result.json'), $frame.Groups[1].Value, [Text.UTF8Encoding]::new($false))
    $result.status = $probe.status
    $result.exit_code = if ($probe.status -eq 'PASS') { 0 } else { 1 }
    Write-Host ("Board " + $mode + ": " + $probe.status + " " + $probe.selected_bdf + " " + $probe.error)
} catch {
    $result.status = 'BLOCKED'
    $result.error = $_.Exception.Message
    Write-Host $result.error
} finally {
    $result.finished_at = [DateTimeOffset]::Now.ToString('o')
    $result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $resultPath -Encoding UTF8
    Write-Host ('Result: ' + $resultPath)
}
exit $result.exit_code
