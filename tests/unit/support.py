import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]


def package_stub(name):
    module = ModuleType(name)
    module.__path__ = []
    return module


def module_stub(name, **attributes):
    module = ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


def load_module(relative_path, module_name, stubs=None):
    path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs or {}):
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    return module


class ScriptedCursor:
    def __init__(self, steps):
        self.steps = iter(steps)
        self.calls = []
        self.current = {}
        self.description = None
        self.rowcount = 0

    def execute(self, sql, params=None):
        normalized_sql = ' '.join(sql.split())
        self.calls.append((normalized_sql, params))
        self.current = next(self.steps)
        self.description = self.current.get('description')
        self.rowcount = self.current.get('rowcount', 0)

    def fetchall(self):
        return self.current.get('fetchall', [])

    def fetchone(self):
        return self.current.get('fetchone')
