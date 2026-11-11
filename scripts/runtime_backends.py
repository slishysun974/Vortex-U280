"""Explicit simulation backends; the physical XRT backend is not enabled here."""
from ptx_module import COMMIT

BACKENDS = {
    'simx': ('simx', 'libvortex-simx.so', 'libsimx.so'),
    'rtlsim': ('rtlsim', 'libvortex-rtlsim.so', 'librtlsim.so'),
    'xrtsim': ('xrt', 'libvortex-xrt.so', 'libxrtsim.so'),
}


def validate_native(summary, backend, lock_hash):
    if backend not in BACKENDS:
        raise ValueError('unsupported simulation backend')
    commands = summary.get('commands', [])
    if (summary.get('status') != 'PASS' or summary.get('demo_execution') != 'PASS'
            or summary.get('backend') != backend or summary.get('check_only') is not False
            or summary.get('source', {}).get('source_commit') != COMMIT
            or summary.get('config_file_sha256', {}).get('target_lock.json') != lock_hash
            or not commands or not any(c.get('label') == 'demo_run' for c in commands)
            or any(c.get('returncode') != 0 or c.get('timed_out') is not False for c in commands)):
        raise ValueError('requires successful native execution for this backend and target')
    if backend in ('rtlsim', 'xrtsim'):
        config = summary.get('effective_backend_configuration', {})
        if not {'-DSIMULATION', '-DSV_DPI'} <= set(config.get('raw_configs', '').split()):
            raise ValueError('missing mandatory RTL simulation defines')
        if backend == 'xrtsim' and set(config.get('simulation_controls', [])) != {'NOXRT', 'XRTSIM', 'TARGET=xrtsim'}:
            raise ValueError('AFU binding requires the NOXRT/XRTSIM model')
