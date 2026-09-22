"""Deployment orchestration tests; never runs sudo, systemctl, Git or Django commands."""
import subprocess
import sys
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.deploy_monitoring import deploy, unit_files


class DeploymentTests(unittest.TestCase):
    def fixture(self, root):
        (root / 'venv/bin').mkdir(parents=True)
        (root / 'venv/bin/python').touch()
        (root / 'manage.py').touch()

    def test_initial_deploy_migrates_before_restart_and_starts_refresh_without_waiting(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            calls, installed = [], {}
            def fake_run(args, **kwargs):
                calls.append(args)
                if args[:3] == ['sudo', '-n', 'install']:
                    installed[args[-1]] = Path(args[-2]).read_text(encoding='utf-8')
                return subprocess.CompletedProcess(args, 1 if args[0] == 'systemctl' and args[1] == 'show' else 0,
                                                   stdout='not-found\n')
            deploy(root, 'ubuntu', 'ubuntu', run=fake_run)
            migration = next(i for i, args in enumerate(calls) if 'migrate' in args)
            restart = calls.index(['sudo', '-n', 'systemctl', 'restart', 'gunicorn'])
            self.assertLess(migration, restart)
            self.assertEqual(2, len(installed))
            self.assertIn('--automatic', installed['/etc/systemd/system/samsung-dsdx-collection-statistics.service'])
            self.assertIn('OnCalendar=*:0/15', installed['/etc/systemd/system/samsung-dsdx-collection-statistics.timer'])
            self.assertIn(['sudo', '-n', 'systemctl', 'start', '--no-block', 'samsung-dsdx-collection-statistics.service'], calls)
            self.assertEqual(['sudo', '-n', 'true'], calls[0])
            self.assertTrue(all(args[1] == '-n' and '-v' not in args
                                for args in calls if args[0] == 'sudo'))

    def test_unavailable_passwordless_sudo_stops_before_any_deployment_changes(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            calls = []
            def fake_run(args, **kwargs):
                calls.append(args)
                raise subprocess.CalledProcessError(1, args)
            with self.assertRaises(subprocess.CalledProcessError):
                deploy(root, 'ubuntu', 'ubuntu', run=fake_run)
            self.assertEqual([['sudo', '-n', 'true']], calls)

    def test_failed_migration_never_restarts_web_or_installs_jobs(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            calls = []
            def fake_run(args, **kwargs):
                calls.append(args)
                if 'migrate' in args:
                    raise subprocess.CalledProcessError(1, args)
                return subprocess.CompletedProcess(args, 0, stdout='loaded\n')
            with self.assertRaises(subprocess.CalledProcessError):
                deploy(root, 'ubuntu', 'ubuntu', run=fake_run)
            self.assertTrue(any('stop' in args for args in calls))
            self.assertFalse(any('restart' in args or 'install' in args for args in calls))

    def test_unit_paths_are_quoted_and_runtime_user_is_not_root(self):
        service = unit_files(PurePosixPath('/home/ubuntu/project space%'), 'ubuntu', 'ubuntu')['samsung-dsdx-collection-statistics.service']
        self.assertIn('WorkingDirectory="/home/ubuntu/project space%%"', service)
        self.assertIn('User=ubuntu', service)
        self.assertNotIn('User=root', service)
        with self.assertRaises(ValueError):
            unit_files(Path('/tmp/a\nExecStart=other'), 'ubuntu', 'ubuntu')


if __name__ == '__main__':
    unittest.main()
