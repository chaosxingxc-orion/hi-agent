"""Tests for check_rules.py AST-based Rule 6/13 detection."""
import pathlib
import sys
import textwrap

# Make the detection function importable
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent.parent / "scripts"))


def test_rule6_skips_docstring():
    from check_rules import _find_rule6_violations_ast
    source = textwrap.dedent('''\
        def foo():
            """Inline fallbacks of the shape `x or DefaultX()` are forbidden."""
            pass
    ''')
    violations = _find_rule6_violations_ast(source, "test.py")
    assert violations == [], f"Should skip docstring, got: {violations}"


def test_rule6_skips_exception_handler():
    from check_rules import _find_rule6_violations_ast
    source = textwrap.dedent('''\
        try:
            raise ValueError("x")
        except Exception as e:
            cause = e or RuntimeError("fallback")
    ''')
    violations = _find_rule6_violations_ast(source, "test.py")
    assert violations == [], f"Should skip except handler, got: {violations}"


def test_rule6_detects_shared_state_fallback():
    from check_rules import _find_rule6_violations_ast
    source = textwrap.dedent('''\
        class Foo:
            def __init__(self, bridge=None):
                self._bridge = bridge or AsyncPGBridge(dsn="postgresql://")
    ''')
    violations = _find_rule6_violations_ast(source, "test.py")
    assert len(violations) == 1, f"Should detect AsyncPGBridge fallback, got: {violations}"


def test_rule6_skips_stdlib_path():
    from check_rules import _find_rule6_violations_ast
    source = textwrap.dedent('''\
        from pathlib import Path
        def configure(workspace=None):
            base = workspace or Path(".").resolve()
    ''')
    violations = _find_rule6_violations_ast(source, "test.py")
    assert violations == [], f"Should skip stdlib Path, got: {violations}"


def test_rule6_skips_module_docstring():
    from check_rules import _find_rule6_violations_ast
    source = textwrap.dedent('''\
        """Module doc: inline fallbacks of the shape x or DefaultX() are forbidden."""

        def real_code():
            pass
    ''')
    violations = _find_rule6_violations_ast(source, "test.py")
    assert violations == [], f"Should skip module docstring, got: {violations}"


def test_rule6_skips_stdlib_runtime_error_in_except():
    """Regression: resilient_kernel_adapter.py pattern — last_exc or RuntimeError(...)."""
    from check_rules import _find_rule6_violations_ast
    source = textwrap.dedent('''\
        def run(last_exc=None):
            try:
                do_work()
            except Exception as last_exc:
                cause = last_exc or RuntimeError("unknown failure")
                raise cause
    ''')
    violations = _find_rule6_violations_ast(source, "test.py")
    assert violations == [], f"Should skip RuntimeError in except handler, got: {violations}"


def test_rule13_skips_docstring():
    from check_rules import _find_rule13_violations_ast
    source = textwrap.dedent('''\
        def foo():
            """Use x or SomeStore() only in tests — forbidden in production code."""
            pass
    ''')
    violations = _find_rule13_violations_ast(source, "test.py")
    assert violations == [], f"Should skip docstring, got: {violations}"


def test_rule13_detects_store_fallback():
    from check_rules import _find_rule13_violations_ast
    source = textwrap.dedent('''\
        class Foo:
            def __init__(self, store=None):
                self._store = store or RunStore(dsn="sqlite://")
    ''')
    violations = _find_rule13_violations_ast(source, "test.py")
    assert len(violations) == 1, f"Should detect RunStore fallback, got: {violations}"


def test_rule13_skips_except_handler():
    from check_rules import _find_rule13_violations_ast
    source = textwrap.dedent('''\
        try:
            connect()
        except Exception as e:
            fallback = e or DataManager("default")
    ''')
    violations = _find_rule13_violations_ast(source, "test.py")
    assert violations == [], f"Should skip except handler, got: {violations}"
