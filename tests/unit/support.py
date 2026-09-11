import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]


def null_review_dependency_stubs():
    """Use the real, database-independent review modules in isolated services."""
    from apps.common import null_review_evidence
    from apps.dx.dx_layer2 import null_review_state
    return {
        'apps.common.null_review_evidence': null_review_evidence,
        'apps.dx.dx_layer2.null_review_state': null_review_state,
    }


def package_stub(name):
    module = ModuleType(name)
    module.__path__ = []
    return module


def module_stub(name, **attributes):
    module = ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


def sem_validation_stub():
    """No-op SEM dependency for isolated legacy Layer 2 service tests."""
    return module_stub(
        'apps.dx.dx_layer2.sem_validation',
        product_line_for=lambda _value: None,
        append_null_stats=lambda *_args, **_kwargs: 0,
        append_format_stats=lambda *_args, **_kwargs: 0,
        append_duplicate_stats=lambda *_args, **_kwargs: 0,
        null_detail=lambda *_args, **_kwargs: {},
        format_detail=lambda *_args, **_kwargs: {},
        duplicate_detail=lambda *_args, **_kwargs: {},
        SEM_SOURCE_CONFIG={},
        SEM_RETAILER='Liverpool',
        get_review_allowed_columns=lambda *_args, **_kwargs: (),
        get_format_rule_details=lambda *_args, **_kwargs: [],
        fetch_review_record=lambda *_args, **_kwargs: None,
    )


def seg_validation_stub():
    """No-op SEG dependency for isolated legacy Layer 2 service tests."""
    return module_stub(
        'apps.dx.dx_layer2.seg_validation',
        product_line_for=lambda _value: None,
        append_null_stats=lambda *_args, **_kwargs: 0,
        append_format_stats=lambda *_args, **_kwargs: 0,
        append_duplicate_stats=lambda *_args, **_kwargs: 0,
        null_detail=lambda *_args, **_kwargs: {},
        format_detail=lambda *_args, **_kwargs: {},
        duplicate_detail=lambda *_args, **_kwargs: {},
        SEG_SOURCE_CONFIG={},
        get_review_allowed_columns=lambda *_args, **_kwargs: (),
        get_format_rule_details=lambda *_args, **_kwargs: [],
        fetch_review_record=lambda *_args, **_kwargs: None,
    )


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
