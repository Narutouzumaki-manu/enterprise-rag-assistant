"""Unit tests for scripts.lint_ratchet using synthetic numbers only."""

from scripts.lint_ratchet import compare_lint_and_type


def test_equal_counts_passes():
    baseline = {
        "ruff_version": "0.17.5",
        "mypy_version": "2.4.1",
        "ruff_rules": {"I001": 50, "B008": 2},
        "mypy_files": {"app/core/config.py": 2, "app/api/main.py": 1},
    }
    current = {
        "ruff_version": "0.17.5",
        "mypy_version": "2.4.1",
        "ruff_rules": {"I001": 50, "B008": 2},
        "mypy_files": {"app/core/config.py": 2, "app/api/main.py": 1},
    }
    passed, errors, improvements = compare_lint_and_type(current, baseline)
    assert passed is True
    assert len(errors) == 0
    assert len(improvements) == 0


def test_rule_count_rise_fails():
    baseline = {
        "ruff_version": "0.17.5",
        "mypy_version": "2.4.1",
        "ruff_rules": {"I001": 50},
        "mypy_files": {},
    }
    current = {
        "ruff_version": "0.17.5",
        "mypy_version": "2.4.1",
        "ruff_rules": {"I001": 51},
        "mypy_files": {},
    }
    passed, errors, _improvements = compare_lint_and_type(current, baseline)
    assert passed is False
    assert any("I001" in e and "increased" in e for e in errors)


def test_rule_count_fall_passes():
    baseline = {
        "ruff_version": "0.17.5",
        "mypy_version": "2.4.1",
        "ruff_rules": {"I001": 50, "B008": 5},
        "mypy_files": {},
    }
    current = {
        "ruff_version": "0.17.5",
        "mypy_version": "2.4.1",
        "ruff_rules": {"I001": 45, "B008": 5},
        "mypy_files": {},
    }
    passed, errors, improvements = compare_lint_and_type(current, baseline)
    assert passed is True
    assert len(errors) == 0
    assert any("I001" in imp and "decreased" in imp for imp in improvements)


def test_new_file_fails():
    baseline = {
        "ruff_version": "0.17.5",
        "mypy_version": "2.4.1",
        "ruff_rules": {},
        "mypy_files": {"app/core/config.py": 1},
    }
    current = {
        "ruff_version": "0.17.5",
        "mypy_version": "2.4.1",
        "ruff_rules": {},
        "mypy_files": {"app/core/config.py": 1, "app/new_file.py": 2},
    }
    passed, errors, _improvements = compare_lint_and_type(current, baseline)
    assert passed is False
    assert any("app/new_file.py" in e and "New file" in e for e in errors)


def test_version_mismatch_fails():
    baseline = {
        "ruff_version": "0.17.5",
        "mypy_version": "2.4.1",
        "ruff_rules": {},
        "mypy_files": {},
    }
    # Ruff mismatch
    current_ruff_diff = {
        "ruff_version": "0.18.0",
        "mypy_version": "2.4.1",
        "ruff_rules": {},
        "mypy_files": {},
    }
    passed, errors, _improvements = compare_lint_and_type(current_ruff_diff, baseline)
    assert passed is False
    assert any("Ruff version mismatch" in e for e in errors)

    # Mypy mismatch
    current_mypy_diff = {
        "ruff_version": "0.17.5",
        "mypy_version": "2.5.0",
        "ruff_rules": {},
        "mypy_files": {},
    }
    passed, errors, _improvements = compare_lint_and_type(current_mypy_diff, baseline)
    assert passed is False
    assert any("Mypy version mismatch" in e for e in errors)


def test_simulate_extra_fails():
    baseline = {
        "ruff_version": "0.17.5",
        "mypy_version": "2.4.1",
        "ruff_rules": {"B008": 2},
        "mypy_files": {},
    }
    current = {
        "ruff_version": "0.17.5",
        "mypy_version": "2.4.1",
        "ruff_rules": {"B008": 2},
        "mypy_files": {},
    }
    passed, errors, _improvements = compare_lint_and_type(
        current, baseline, simulate_extra=1
    )
    assert passed is False
    assert any("B008" in e and "increased" in e for e in errors)
