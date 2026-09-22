"""Ubuntu deployment, invoked by deploy.sh. Does not load application settings."""
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

UNIT = 'samsung-dsdx-collection-statistics'


def unit_quote(value):
    value = str(value)
    if '\n' in value or '\r' in value:
        raise ValueError('Unsupported newline in deployment path')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'


def unit_files(root, username, groupname):
    service = f'''[Unit]
Description=Samsung DSDX collection statistics
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User={username}
Group={groupname}
WorkingDirectory={unit_quote(root)}
ExecStart={unit_quote(root / 'venv/bin/python')} {unit_quote(root / 'manage.py')} refresh_collection_statistics --automatic
Nice=10
TimeoutStartSec=30min
'''
    timer = f'''[Unit]
Description=Refresh Samsung DSDX collection statistics every 15 minutes

[Timer]
OnBootSec=2min
OnCalendar=*:0/15
Persistent=true
Unit={UNIT}.service

[Install]
WantedBy=timers.target
'''
    return {f'{UNIT}.service': service, f'{UNIT}.timer': timer}


def deploy(root, username, groupname, run=subprocess.run):
    python = root / 'venv/bin/python'
    manage = root / 'manage.py'
    if not python.is_file() or not manage.is_file():
        raise RuntimeError('Run from a deployment with venv/bin/python and manage.py')

    def command(*args, **options):
        if args[0] == 'sudo':
            args = ('sudo', '-n', *args[1:])
        return run([str(arg) for arg in args], cwd=root, check=True, **options)

    # Validate execution permission, not the sudo password timestamp: sudo -v
    # can require a password even when the effective command rule is NOPASSWD.
    command('sudo', 'true')
    # Stop only our own jobs before changing their schema/code.
    for suffix in ('timer', 'service'):
        name = f'{UNIT}.{suffix}'
        state = run(['systemctl', 'show', name, '--property=LoadState', '--value'],
                    cwd=root, check=False, capture_output=True, text=True)
        if state.stdout.strip() == 'loaded':
            command('sudo', 'systemctl', 'stop', name)
        elif state.stdout.strip() != 'not-found':
            raise RuntimeError('Cannot inspect the statistics job state')

    print('Checking application and preparing collection statistics storage...', flush=True)
    command(python, manage, 'check')
    command(python, manage, 'migrate', 'dx_layer1', '--noinput')
    command(python, manage, 'collectstatic', '--noinput')

    with TemporaryDirectory(prefix='dsdx-deploy-') as temp:
        for name, content in unit_files(root, username, groupname).items():
            source = Path(temp) / name
            source.write_text(content, encoding='utf-8', newline='\n')
            command('sudo', 'install', '-m', '0644', source, f'/etc/systemd/system/{name}')
    command('sudo', 'systemctl', 'daemon-reload')
    command('sudo', 'systemctl', 'restart', 'gunicorn')
    command('systemctl', 'is-active', '--quiet', 'gunicorn')
    command('sudo', 'systemctl', 'enable', '--now', f'{UNIT}.timer')
    command('sudo', 'systemctl', 'start', '--no-block', f'{UNIT}.service')
    print('Deployment complete. Recent counts and history will populate in the background.', flush=True)


def main():
    if sys.platform != 'linux' or os.getuid() == 0:
        print('Run bash scripts/deploy.sh as the regular Ubuntu deployment user, not with sudo.', file=sys.stderr)
        return 1
    import grp
    import pwd
    user = pwd.getpwuid(os.getuid())
    try:
        deploy(Path(__file__).resolve().parents[1], user.pw_name, grp.getgrgid(user.pw_gid).gr_name)
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError):
        print('Deployment stopped at the failed step above. No success was reported.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
