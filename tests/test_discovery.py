"""Tests for discovery scanners and DiscoveryWorker."""

import tempfile
from pathlib import Path

import pytest

from foxhound.core.models import (
    ExecutionMode,
    ExecutionSnapshot,
    ExecutionStrategy,
    PolicyRef,
    RecipeRef,
    RiskLevel,
    TaskEnvelope,
    TrustLevel,
    WorkItemKind,
    WorkItemState,
)
from foxhound.discovery.scanners import (
    SKIP_DIRS,
    SOURCE_PATTERNS,
    TAG_CONFIDENCE,
    TAG_RISK,
    DependencyAlertScanner,
    ScannerRegistry,
    ScanResult,
    TodoScanner,
    _should_skip,
    scan_result_to_work_item,
)
from foxhound.discovery.worker import DiscoveryWorker
from foxhound.harness.runtime import Harness
from foxhound.harness.worker_protocol import (
    Capability,
    RuntimeHandle,
    WorkerClass,
    WorkerOutput,
)


@pytest.fixture()
def repo_dir():
    """Create a temporary repo directory with sample files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)

        # Python file with TODOs
        src = repo / "src"
        src.mkdir()
        (src / "main.py").write_text(
            "def run():\n"
            "    # TODO: add error handling\n"
            "    pass\n"
            "\n"
            "def other():\n"
            "    # FIXME: this is broken\n"
            "    return None\n"
            "\n"
            "# HACK: workaround for upstream bug\n"
            "x = 42\n"
        )

        # JS file with XXX using // comment
        (src / "app.js").write_text(
            "// XXX: critical performance issue\n"
            "function slow() { return true; }\n"
        )

        # File in skip directory (should be ignored)
        cache = repo / "__pycache__"
        cache.mkdir()
        (cache / "junk.py").write_text("# TODO: this should be skipped\n")

        # Requirements with vulnerability annotation
        (repo / "requirements.txt").write_text(
            "flask==2.3.0\n"
            "requests==2.28.0  # CVE-2023-xxxx\n"
            "pydantic==2.0.0\n"
        )

        yield repo


@pytest.fixture()
def execution_snapshot():
    """Create a minimal execution snapshot for tests."""
    return ExecutionSnapshot(
        recipe_ref=RecipeRef(
            name="test", version="1.0.0", content_hash="abc123"
        ),
        policy_ref=PolicyRef(
            name="test", version="1.0.0", content_hash="def456"
        ),
        execution_strategy=ExecutionStrategy.ONE_SHOT,
        model_tier="balanced",
        config_hash="test_hash",
    )


@pytest.fixture()
def task_envelope(repo_dir, execution_snapshot):
    """Create a task envelope pointing at the temp repo."""
    return TaskEnvelope(
        task_id="task_001",
        job_id="job_001",
        run_id="run_001",
        repo_id="repo_test",
        execution_snapshot=execution_snapshot,
        execution_mode=ExecutionMode.READ_ONLY,
        input_payload={"repo_path": str(repo_dir)},
    )


def _make_runtime(
    caps: set[Capability] | None = None,
    budget: float = 1.0,
) -> RuntimeHandle:
    """Create a runtime handle with given capabilities."""
    if caps is None:
        caps = {Capability.REPO_READ, Capability.SPAWN}
    return RuntimeHandle(
        execution_mode=ExecutionMode.READ_ONLY,
        capabilities=caps,
        budget_remaining=budget,
        timeout_remaining=300.0,
    )


# ============================================================================
# ScanResult
# ============================================================================


class TestScanResult:
    def test_fingerprint_is_deterministic(self):
        r1 = ScanResult(
            source_type="todo_todo",
            title="test",
            description="desc",
            file_path="src/main.py",
            evidence={},
        )
        r2 = ScanResult(
            source_type="todo_todo",
            title="test",
            description="different desc",
            file_path="src/main.py",
            evidence={},
        )
        assert r1.fingerprint == r2.fingerprint

    def test_fingerprint_varies_by_source_type(self):
        r1 = ScanResult(
            source_type="todo_todo",
            title="test",
            description="",
            file_path="x.py",
            evidence={},
        )
        r2 = ScanResult(
            source_type="todo_fixme",
            title="test",
            description="",
            file_path="x.py",
            evidence={},
        )
        assert r1.fingerprint != r2.fingerprint

    def test_fingerprint_varies_by_file_path(self):
        r1 = ScanResult(
            source_type="todo_todo",
            title="test",
            description="",
            file_path="a.py",
            evidence={},
        )
        r2 = ScanResult(
            source_type="todo_todo",
            title="test",
            description="",
            file_path="b.py",
            evidence={},
        )
        assert r1.fingerprint != r2.fingerprint

    def test_fingerprint_varies_by_title(self):
        r1 = ScanResult(
            source_type="t",
            title="alpha",
            description="",
            file_path="x.py",
            evidence={},
        )
        r2 = ScanResult(
            source_type="t",
            title="beta",
            description="",
            file_path="x.py",
            evidence={},
        )
        assert r1.fingerprint != r2.fingerprint

    def test_fingerprint_length(self):
        r = ScanResult(
            source_type="t",
            title="t",
            description="",
            file_path="x.py",
            evidence={},
        )
        assert len(r.fingerprint) == 16

    def test_default_values(self):
        r = ScanResult(
            source_type="t",
            title="t",
            description="d",
            file_path="x.py",
            evidence={"k": "v"},
        )
        assert r.confidence == 0.5
        assert r.risk == RiskLevel.LOW
        assert r.recipe_name is None
        assert r.line_number is None

    def test_all_fields_set(self):
        r = ScanResult(
            source_type="todo_fixme",
            title="Fix it",
            description="Needs fixing",
            file_path="src/foo.py",
            line_number=42,
            evidence={"tag": "fixme"},
            confidence=0.9,
            risk=RiskLevel.HIGH,
            recipe_name="fix_recipe",
        )
        assert r.source_type == "todo_fixme"
        assert r.line_number == 42
        assert r.confidence == 0.9
        assert r.risk == RiskLevel.HIGH
        assert r.recipe_name == "fix_recipe"


# ============================================================================
# _should_skip
# ============================================================================


class TestShouldSkip:
    def test_skips_git(self):
        assert _should_skip(Path(".git/config"))

    def test_skips_node_modules(self):
        assert _should_skip(Path("node_modules/package/index.js"))

    def test_skips_pycache(self):
        assert _should_skip(Path("src/__pycache__/mod.pyc"))

    def test_skips_venv(self):
        assert _should_skip(Path(".venv/lib/python3.13/site.py"))

    def test_skips_foxhound(self):
        assert _should_skip(Path(".foxhound/artifacts/x"))

    def test_skips_egg_info(self):
        assert _should_skip(Path("foo.egg-info/PKG-INFO"))

    def test_allows_normal_paths(self):
        assert not _should_skip(Path("src/main.py"))
        assert not _should_skip(Path("lib/utils/helpers.js"))

    def test_skips_nested_skip_dir(self):
        assert _should_skip(Path("project/node_modules/pkg/file.js"))

    def test_skip_dirs_constant_has_expected_entries(self):
        assert ".git" in SKIP_DIRS
        assert "node_modules" in SKIP_DIRS
        assert "__pycache__" in SKIP_DIRS
        assert ".foxhound" in SKIP_DIRS


# ============================================================================
# TodoScanner
# ============================================================================


class TestTodoScanner:
    def test_finds_all_four_tags(self, repo_dir):
        scanner = TodoScanner()
        results = scanner.scan(repo_dir)
        tags = {r.evidence["tag"] for r in results}
        assert tags == {"todo", "fixme", "hack", "xxx"}

    def test_correct_count(self, repo_dir):
        scanner = TodoScanner()
        results = scanner.scan(repo_dir)
        assert len(results) == 4

    def test_skips_pycache(self, repo_dir):
        scanner = TodoScanner()
        results = scanner.scan(repo_dir)
        assert not any("__pycache__" in r.file_path for r in results)

    def test_risk_mapping(self, repo_dir):
        scanner = TodoScanner()
        results = scanner.scan(repo_dir)
        by_tag = {r.evidence["tag"]: r for r in results}
        assert by_tag["todo"].risk == RiskLevel.LOW
        assert by_tag["fixme"].risk == RiskLevel.MEDIUM
        assert by_tag["hack"].risk == RiskLevel.MEDIUM
        assert by_tag["xxx"].risk == RiskLevel.HIGH

    def test_confidence_mapping(self, repo_dir):
        scanner = TodoScanner()
        results = scanner.scan(repo_dir)
        by_tag = {r.evidence["tag"]: r for r in results}
        assert by_tag["todo"].confidence == TAG_CONFIDENCE["todo"]
        assert by_tag["fixme"].confidence == TAG_CONFIDENCE["fixme"]
        assert by_tag["hack"].confidence == TAG_CONFIDENCE["hack"]
        assert by_tag["xxx"].confidence == TAG_CONFIDENCE["xxx"]

    def test_fingerprint_deterministic(self, repo_dir):
        scanner = TodoScanner()
        fps1 = {r.fingerprint for r in scanner.scan(repo_dir)}
        fps2 = {r.fingerprint for r in scanner.scan(repo_dir)}
        assert fps1 == fps2

    def test_fingerprints_are_unique(self, repo_dir):
        scanner = TodoScanner()
        results = scanner.scan(repo_dir)
        fps = [r.fingerprint for r in results]
        assert len(fps) == len(set(fps))

    def test_line_numbers_correct(self, repo_dir):
        scanner = TodoScanner()
        results = scanner.scan(repo_dir)
        for r in results:
            assert r.line_number is not None
            assert r.line_number > 0

    def test_evidence_structure(self, repo_dir):
        scanner = TodoScanner()
        results = scanner.scan(repo_dir)
        for r in results:
            assert "tag" in r.evidence
            assert "message" in r.evidence
            assert "line" in r.evidence
            assert "file" in r.evidence
            assert "line_number" in r.evidence
            assert r.evidence["line_number"] == r.line_number

    def test_source_type_includes_tag(self, repo_dir):
        scanner = TodoScanner()
        results = scanner.scan(repo_dir)
        for r in results:
            assert r.source_type.startswith("todo_")
            assert r.evidence["tag"] in r.source_type

    def test_title_format(self, repo_dir):
        scanner = TodoScanner()
        results = scanner.scan(repo_dir)
        for r in results:
            tag_upper = r.evidence["tag"].upper()
            assert r.title.startswith(f"[{tag_upper}]")

    def test_relative_file_paths(self, repo_dir):
        scanner = TodoScanner()
        results = scanner.scan(repo_dir)
        for r in results:
            assert not r.file_path.startswith("/")
            assert r.file_path.startswith("src/")

    def test_empty_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert TodoScanner().scan(Path(tmpdir)) == []

    def test_case_insensitive_tags(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "f.py").write_text(
                "# todo: lowercase\n"
                "# Todo: titlecase\n"
                "# TODO: uppercase\n"
            )
            results = TodoScanner().scan(repo)
            assert len(results) == 3
            assert all(r.evidence["tag"] == "todo" for r in results)

    def test_tag_without_message_uses_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "f.py").write_text("# TODO:\n# FIXME\n")
            results = TodoScanner().scan(repo)
            for r in results:
                msg = r.evidence["message"]
                assert "found" in msg.lower() or len(msg) > 0

    def test_long_message_truncated_in_title(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            long_msg = "x" * 200
            (repo / "f.py").write_text(f"# TODO: {long_msg}\n")
            results = TodoScanner().scan(repo)
            assert len(results[0].title) <= 90  # [TODO] + space + 80 chars

    def test_multiple_todos_in_same_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "f.py").write_text(
                "# TODO: first\n"
                "# TODO: second\n"
                "# TODO: third\n"
            )
            results = TodoScanner().scan(repo)
            assert len(results) == 3
            lines = [r.line_number for r in results]
            assert lines == [1, 2, 3]

    def test_hash_comment_style(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "f.py").write_text("# TODO: python style\n")
            results = TodoScanner().scan(repo)
            assert len(results) == 1

    def test_double_slash_comment_style(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "f.js").write_text("// TODO: js style\n")
            results = TodoScanner().scan(repo)
            assert len(results) == 1

    def test_skips_git_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            git = repo / ".git"
            git.mkdir()
            (git / "config.py").write_text("# TODO: should skip\n")
            results = TodoScanner().scan(repo)
            assert len(results) == 0

    def test_skips_node_modules(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            nm = repo / "node_modules" / "pkg"
            nm.mkdir(parents=True)
            (nm / "index.js").write_text("// TODO: skip this\n")
            results = TodoScanner().scan(repo)
            assert len(results) == 0

    def test_skips_venv_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            venv = repo / ".venv" / "lib"
            venv.mkdir(parents=True)
            (venv / "site.py").write_text("# TODO: venv skip\n")
            results = TodoScanner().scan(repo)
            assert len(results) == 0

    def test_nested_source_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            deep = repo / "a" / "b" / "c"
            deep.mkdir(parents=True)
            (deep / "mod.py").write_text("# FIXME: deep nested\n")
            results = TodoScanner().scan(repo)
            assert len(results) == 1
            assert "a/b/c/mod.py" in results[0].file_path

    def test_scanner_name(self):
        assert TodoScanner().scanner_name == "todo_scanner"

    def test_source_patterns_has_common_extensions(self):
        assert "**/*.py" in SOURCE_PATTERNS
        assert "**/*.js" in SOURCE_PATTERNS
        assert "**/*.ts" in SOURCE_PATTERNS
        assert "**/*.rs" in SOURCE_PATTERNS
        assert "**/*.go" in SOURCE_PATTERNS

    def test_tag_risk_mapping_complete(self):
        assert set(TAG_RISK.keys()) == {"todo", "fixme", "hack", "xxx"}

    def test_tag_confidence_mapping_complete(self):
        assert set(TAG_CONFIDENCE.keys()) == {"todo", "fixme", "hack", "xxx"}


# ============================================================================
# DependencyAlertScanner
# ============================================================================


class TestDependencyAlertScanner:
    def test_finds_cve_annotation(self, repo_dir):
        scanner = DependencyAlertScanner()
        results = scanner.scan(repo_dir)
        assert len(results) == 1
        assert "requests" in results[0].title
        assert results[0].risk == RiskLevel.HIGH

    def test_cve_result_evidence(self, repo_dir):
        scanner = DependencyAlertScanner()
        results = scanner.scan(repo_dir)
        r = results[0]
        assert r.evidence["package"] == "requests"
        assert r.evidence["version"] == "2.28.0"
        assert r.evidence["file"] == "requirements.txt"
        assert "CVE" in r.evidence["line"]

    def test_cve_result_metadata(self, repo_dir):
        scanner = DependencyAlertScanner()
        results = scanner.scan(repo_dir)
        r = results[0]
        assert r.source_type == "dependency_alert"
        assert r.confidence == 0.8
        assert r.recipe_name == "dependency_update"
        assert r.file_path == "requirements.txt"
        assert r.line_number == 2

    def test_no_lockfiles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert DependencyAlertScanner().scan(Path(tmpdir)) == []

    def test_clean_requirements_no_alerts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "requirements.txt").write_text(
                "flask==2.3.0\nrequests==2.31.0\n"
            )
            results = DependencyAlertScanner().scan(repo)
            assert len(results) == 0

    def test_multiple_cve_annotations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "requirements.txt").write_text(
                "flask==2.3.0  # CVE-2023-1111\n"
                "requests==2.28.0  # CVE-2023-2222\n"
                "pydantic==1.0.0  # security issue\n"
            )
            results = DependencyAlertScanner().scan(repo)
            assert len(results) == 3

    def test_vuln_annotation_case_insensitive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "requirements.txt").write_text(
                "pkg==1.0.0  # cve-2023-1234\n"
            )
            results = DependencyAlertScanner().scan(repo)
            assert len(results) == 1

    def test_requirements_dev_scanned(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "requirements-dev.txt").write_text(
                "pytest==7.0.0  # CVE-2023-test\n"
            )
            results = DependencyAlertScanner().scan(repo)
            assert len(results) == 1
            assert results[0].file_path == "requirements-dev.txt"

    def test_non_requirements_lockfile_no_cve_check(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            # poetry.lock is in LOCKFILE_NAMES but doesn't start
            # with "requirements", so CVE pattern check is skipped
            (repo / "poetry.lock").write_text(
                "pkg==1.0.0  # CVE-2023-xxxx\n"
            )
            results = DependencyAlertScanner().scan(repo)
            assert len(results) == 0

    def test_scanner_name(self):
        assert DependencyAlertScanner().scanner_name == "dependency_alert_scanner"

    def test_fingerprint_includes_file_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "requirements.txt").write_text(
                "pkg==1.0.0  # CVE-test\n"
            )
            results = DependencyAlertScanner().scan(repo)
            fp = results[0].fingerprint
            assert len(fp) == 16


# ============================================================================
# ScannerRegistry
# ============================================================================


class TestScannerRegistry:
    def test_register_defaults(self):
        reg = ScannerRegistry()
        reg.register_defaults()
        assert len(reg.scanners) == 2
        names = [s.scanner_name for s in reg.scanners]
        assert "todo_scanner" in names
        assert "dependency_alert_scanner" in names

    def test_scan_all(self, repo_dir):
        reg = ScannerRegistry()
        reg.register_defaults()
        results = reg.scan_all(repo_dir)
        assert len(results) == 5  # 4 TODOs + 1 dep alert

    def test_empty_registry(self, repo_dir):
        reg = ScannerRegistry()
        assert reg.scan_all(repo_dir) == []

    def test_register_custom_scanner(self, repo_dir):
        class StubScanner:
            scanner_name = "stub"

            def scan(self, repo_path):
                return [
                    ScanResult(
                        source_type="stub",
                        title="stub finding",
                        description="",
                        file_path="x.py",
                        evidence={},
                    )
                ]

        reg = ScannerRegistry()
        reg.register(StubScanner())
        assert len(reg.scanners) == 1
        assert reg.scanners[0].scanner_name == "stub"
        results = reg.scan_all(repo_dir)
        assert len(results) == 1

    def test_register_defaults_replaces_previous(self):
        reg = ScannerRegistry()
        reg.register_defaults()
        reg.register_defaults()
        assert len(reg.scanners) == 2

    def test_scanners_returns_copy(self):
        reg = ScannerRegistry()
        reg.register_defaults()
        scanners = reg.scanners
        scanners.clear()
        assert len(reg.scanners) == 2


# ============================================================================
# scan_result_to_work_item
# ============================================================================


class TestScanResultToWorkItem:
    def test_basic_conversion(self, repo_dir):
        scanner = TodoScanner()
        results = scanner.scan(repo_dir)
        item = scan_result_to_work_item(results[0], "repo_1", "wi_001")

        assert item.work_item_id == "wi_001"
        assert item.repo_id == "repo_1"
        assert item.state == WorkItemState.DISCOVERED
        assert item.trust_level == TrustLevel.SEMI_TRUSTED
        assert item.kind == WorkItemKind.EXECUTION

    def test_title_mapped(self, repo_dir):
        r = ScanResult(
            source_type="test",
            title="My Title",
            description="My Desc",
            file_path="x.py",
            evidence={},
        )
        item = scan_result_to_work_item(r, "repo_1", "wi_1")
        assert item.title == "My Title"
        assert item.description == "My Desc"

    def test_fingerprint_mapped(self):
        r = ScanResult(
            source_type="t",
            title="t",
            description="d",
            file_path="x.py",
            evidence={},
        )
        item = scan_result_to_work_item(r, "repo_1", "wi_1")
        assert item.source_fingerprint == r.fingerprint

    def test_confidence_mapped(self):
        r = ScanResult(
            source_type="t",
            title="t",
            description="d",
            file_path="x.py",
            evidence={},
            confidence=0.95,
        )
        item = scan_result_to_work_item(r, "repo_1", "wi_1")
        assert item.confidence == 0.95

    def test_risk_mapped(self):
        r = ScanResult(
            source_type="t",
            title="t",
            description="d",
            file_path="x.py",
            evidence={},
            risk=RiskLevel.HIGH,
        )
        item = scan_result_to_work_item(r, "repo_1", "wi_1")
        assert item.risk == RiskLevel.HIGH

    def test_recipe_name_mapped(self):
        r = ScanResult(
            source_type="dep",
            title="t",
            description="d",
            file_path="x.py",
            evidence={},
            recipe_name="dependency_update",
        )
        item = scan_result_to_work_item(r, "repo_1", "wi_1")
        assert item.recipe_name == "dependency_update"

    def test_recipe_name_none_when_absent(self):
        r = ScanResult(
            source_type="t",
            title="t",
            description="d",
            file_path="x.py",
            evidence={},
        )
        item = scan_result_to_work_item(r, "repo_1", "wi_1")
        assert item.recipe_name is None

    def test_evidence_mapped(self):
        r = ScanResult(
            source_type="t",
            title="t",
            description="d",
            file_path="x.py",
            evidence={"key": "value", "nested": {"a": 1}},
        )
        item = scan_result_to_work_item(r, "repo_1", "wi_1")
        assert item.evidence == {"key": "value", "nested": {"a": 1}}

    def test_likely_files_from_file_path(self):
        r = ScanResult(
            source_type="t",
            title="t",
            description="d",
            file_path="src/foo/bar.py",
            evidence={},
        )
        item = scan_result_to_work_item(r, "repo_1", "wi_1")
        assert item.likely_files == ["src/foo/bar.py"]

    def test_source_type_mapped(self):
        r = ScanResult(
            source_type="todo_fixme",
            title="t",
            description="d",
            file_path="x.py",
            evidence={},
        )
        item = scan_result_to_work_item(r, "repo_1", "wi_1")
        assert item.source_type == "todo_fixme"


# ============================================================================
# DiscoveryWorker
# ============================================================================


class TestDiscoveryWorker:
    # --- Worker metadata ---

    def test_worker_name(self):
        w = DiscoveryWorker()
        assert w.worker_name == "discovery_worker"

    def test_worker_class(self):
        w = DiscoveryWorker()
        assert w.worker_class == WorkerClass.ROOT

    def test_capabilities(self):
        w = DiscoveryWorker()
        assert w.capabilities == {Capability.REPO_READ, Capability.SPAWN}

    def test_no_write_capability(self):
        w = DiscoveryWorker()
        assert Capability.REPO_WRITE not in w.capabilities

    def test_no_shell_capability(self):
        w = DiscoveryWorker()
        assert Capability.SHELL not in w.capabilities

    def test_allowed_spawn_targets(self):
        w = DiscoveryWorker()
        assert "security_review_worker" in w.allowed_spawn_targets

    def test_default_timeout(self):
        assert DiscoveryWorker().default_timeout_seconds == 300

    def test_default_budget(self):
        assert DiscoveryWorker().default_budget == 1.0

    # --- Custom scanner registry ---

    def test_custom_scanner_registry(self, task_envelope):
        reg = ScannerRegistry()
        reg.register(TodoScanner())
        worker = DiscoveryWorker(scanner_registry=reg)

        runtime = _make_runtime()
        output = worker.execute(task_envelope, runtime)
        # Only TodoScanner, no DependencyAlertScanner
        assert "todo_scanner" in output.payload["scanners_run"]
        assert "dependency_alert_scanner" not in output.payload["scanners_run"]

    def test_empty_registry_gets_defaults(self):
        reg = ScannerRegistry()
        worker = DiscoveryWorker(scanner_registry=reg)
        assert len(worker._registry.scanners) == 2

    # --- validate_input ---

    def test_validate_input_valid(self, task_envelope):
        result = DiscoveryWorker().validate_input(task_envelope)
        assert result.valid
        assert result.errors == []

    def test_validate_input_missing_repo_path(self, execution_snapshot):
        task = TaskEnvelope(
            task_id="t1",
            job_id="j1",
            run_id="r1",
            repo_id="repo_1",
            execution_snapshot=execution_snapshot,
            execution_mode=ExecutionMode.READ_ONLY,
            input_payload={},
        )
        result = DiscoveryWorker().validate_input(task)
        assert not result.valid
        assert any("repo_path" in e for e in result.errors)

    def test_validate_input_bad_path(self, execution_snapshot):
        task = TaskEnvelope(
            task_id="t1",
            job_id="j1",
            run_id="r1",
            repo_id="repo_1",
            execution_snapshot=execution_snapshot,
            execution_mode=ExecutionMode.READ_ONLY,
            input_payload={"repo_path": "/nonexistent/path/xyz"},
        )
        result = DiscoveryWorker().validate_input(task)
        assert not result.valid
        assert any("not a valid directory" in e for e in result.errors)

    def test_validate_input_warns_non_readonly_mode(
        self, execution_snapshot, repo_dir
    ):
        task = TaskEnvelope(
            task_id="t1",
            job_id="j1",
            run_id="r1",
            repo_id="repo_1",
            execution_snapshot=execution_snapshot,
            execution_mode=ExecutionMode.FULL_EXECUTE,
            input_payload={"repo_path": str(repo_dir)},
        )
        result = DiscoveryWorker().validate_input(task)
        assert result.valid  # valid, but warnings
        assert len(result.warnings) == 1
        assert "read_only" in result.warnings[0]

    def test_validate_input_plan_only_no_warning(
        self, execution_snapshot, repo_dir
    ):
        task = TaskEnvelope(
            task_id="t1",
            job_id="j1",
            run_id="r1",
            repo_id="repo_1",
            execution_snapshot=execution_snapshot,
            execution_mode=ExecutionMode.PLAN_ONLY,
            input_payload={"repo_path": str(repo_dir)},
        )
        result = DiscoveryWorker().validate_input(task)
        assert result.valid
        assert result.warnings == []

    # --- build_context ---

    def test_build_context_pack(self, task_envelope):
        ctx = DiscoveryWorker().build_context(task_envelope)
        assert ctx.context_pack["repo_id"] == "repo_test"
        assert "repo_path" in ctx.context_pack
        assert isinstance(ctx.context_pack["scanners"], list)
        assert len(ctx.context_pack["scanners"]) == 2

    def test_build_context_hash(self, task_envelope):
        ctx = DiscoveryWorker().build_context(task_envelope)
        assert ctx.context_hash == "discovery_repo_test"

    def test_build_context_trust_labels(self, task_envelope):
        ctx = DiscoveryWorker().build_context(task_envelope)
        assert ctx.trust_labels == {
            "repo_files": TrustLevel.SEMI_TRUSTED.value
        }

    def test_build_context_no_files_included(self, task_envelope):
        ctx = DiscoveryWorker().build_context(task_envelope)
        assert ctx.files_included == []

    # --- execute ---

    def test_execute_finds_items(self, task_envelope):
        output = DiscoveryWorker().execute(task_envelope, _make_runtime())
        items = output.payload["work_items"]
        assert len(items) == 5  # 4 TODOs + 1 dep alert
        assert output.payload["unique_findings"] == 5
        assert output.payload["total_findings"] == 5
        assert output.payload["duplicates_skipped"] == 0

    def test_execute_work_item_structure(self, task_envelope):
        output = DiscoveryWorker().execute(task_envelope, _make_runtime())
        item = output.payload["work_items"][0]
        assert "work_item_id" in item
        assert "repo_id" in item
        assert "state" in item
        assert "trust_level" in item
        assert "source_fingerprint" in item

    def test_execute_dedup_known_fingerprints(self, task_envelope, repo_dir):
        reg = ScannerRegistry()
        reg.register_defaults()
        results = reg.scan_all(repo_dir)
        known = [r.fingerprint for r in results[:2]]

        task_envelope.input_payload["known_fingerprints"] = known
        output = DiscoveryWorker().execute(task_envelope, _make_runtime())
        assert output.payload["duplicates_skipped"] >= 2
        assert output.payload["unique_findings"] <= 3

    def test_execute_dedup_all_known(self, task_envelope, repo_dir):
        reg = ScannerRegistry()
        reg.register_defaults()
        results = reg.scan_all(repo_dir)
        known = [r.fingerprint for r in results]

        task_envelope.input_payload["known_fingerprints"] = known
        output = DiscoveryWorker().execute(task_envelope, _make_runtime())
        assert output.payload["unique_findings"] == 0
        assert output.payload["work_items"] == []

    def test_execute_internal_dedup(self, task_envelope):
        """Results within a scan are deduplicated by fingerprint."""
        output = DiscoveryWorker().execute(task_envelope, _make_runtime())
        fps = [
            item["source_fingerprint"]
            for item in output.payload["work_items"]
        ]
        assert len(fps) == len(set(fps))

    def test_execute_requires_repo_read(self, task_envelope):
        runtime = _make_runtime(caps=set())
        with pytest.raises(RuntimeError, match="REPO_READ"):
            DiscoveryWorker().execute(task_envelope, runtime)

    def test_execute_scanners_run_field(self, task_envelope):
        output = DiscoveryWorker().execute(task_envelope, _make_runtime())
        scanners = output.payload["scanners_run"]
        assert "todo_scanner" in scanners
        assert "dependency_alert_scanner" in scanners

    def test_execute_empty_repo(self, execution_snapshot):
        with tempfile.TemporaryDirectory() as tmpdir:
            task = TaskEnvelope(
                task_id="t1",
                job_id="j1",
                run_id="r1",
                repo_id="repo_empty",
                execution_snapshot=execution_snapshot,
                execution_mode=ExecutionMode.READ_ONLY,
                input_payload={"repo_path": tmpdir},
            )
            output = DiscoveryWorker().execute(task, _make_runtime())
            assert output.payload["work_items"] == []
            assert output.payload["total_findings"] == 0

    def test_execute_output_metadata(self, task_envelope):
        output = DiscoveryWorker().execute(task_envelope, _make_runtime())
        assert output.commands_run == []
        assert output.files_changed == []
        assert output.cost == 0.0

    # --- sanitize_output ---

    def test_sanitize_preserves_payload(self):
        worker = DiscoveryWorker()
        raw = WorkerOutput(
            payload={"key": "value"},
            commands_run=["cmd1"],
            files_changed=["f.py"],
            cost=0.5,
            artifact_paths=["a.txt"],
        )
        sanitized = worker.sanitize_output(raw)
        assert sanitized.payload == {"key": "value"}
        assert sanitized.commands_run == ["cmd1"]
        assert sanitized.files_changed == ["f.py"]
        assert sanitized.cost == 0.5
        assert sanitized.redactions_applied == []

    # --- evaluate_output ---

    def test_evaluate_with_findings(self):
        worker = DiscoveryWorker()
        from foxhound.harness.worker_protocol import SanitizedOutput

        output = SanitizedOutput(
            payload={"work_items": [{"id": 1}], "total_findings": 1}
        )
        result = worker.evaluate_output(output)
        assert result.passed
        assert result.confidence == 0.8

    def test_evaluate_no_findings(self):
        worker = DiscoveryWorker()
        from foxhound.harness.worker_protocol import SanitizedOutput

        output = SanitizedOutput(
            payload={"work_items": [], "total_findings": 0}
        )
        result = worker.evaluate_output(output)
        assert result.passed
        assert result.confidence == 0.5

    def test_evaluate_large_scan_warning(self):
        worker = DiscoveryWorker()
        from foxhound.harness.worker_protocol import SanitizedOutput

        output = SanitizedOutput(
            payload={"work_items": [], "total_findings": 200}
        )
        result = worker.evaluate_output(output)
        assert result.passed
        assert any("Large scan" in f for f in result.safety_flags)
        assert any("200" in f for f in result.safety_flags)

    def test_evaluate_normal_count_no_warning(self):
        worker = DiscoveryWorker()
        from foxhound.harness.worker_protocol import SanitizedOutput

        output = SanitizedOutput(
            payload={"work_items": [{"id": 1}], "total_findings": 50}
        )
        result = worker.evaluate_output(output)
        assert result.safety_flags == []

    def test_evaluate_has_notes(self):
        worker = DiscoveryWorker()
        from foxhound.harness.worker_protocol import SanitizedOutput

        output = SanitizedOutput(
            payload={"work_items": [{"id": 1}], "total_findings": 3}
        )
        result = worker.evaluate_output(output)
        assert len(result.evaluator_notes) == 1
        assert "1 unique" in result.evaluator_notes[0]
        assert "3 total" in result.evaluator_notes[0]

    # --- finalize ---

    def test_finalize_success(self):
        from foxhound.harness.worker_protocol import EvaluationResult

        result = DiscoveryWorker().finalize(
            EvaluationResult(passed=True, confidence=0.8)
        )
        assert result.status.value == "success"
        assert result.confidence == 0.8
        assert result.recommended_next_action == "advance_to_suggested"

    def test_finalize_failure(self):
        from foxhound.harness.worker_protocol import EvaluationResult

        result = DiscoveryWorker().finalize(
            EvaluationResult(passed=False, confidence=0.3)
        )
        assert result.status.value == "failed"
        assert result.recommended_next_action is None

    def test_finalize_preserves_safety_flags(self):
        from foxhound.harness.worker_protocol import EvaluationResult

        result = DiscoveryWorker().finalize(
            EvaluationResult(
                passed=True,
                confidence=0.7,
                safety_flags=["flag1", "flag2"],
            )
        )
        assert result.safety_flags == ["flag1", "flag2"]

    # --- Full lifecycle ---

    def test_full_six_method_lifecycle(self, task_envelope):
        """End-to-end test of the complete 6-method contract."""
        worker = DiscoveryWorker()

        validation = worker.validate_input(task_envelope)
        assert validation.valid

        context = worker.build_context(task_envelope)
        assert context.context_pack["repo_id"] == "repo_test"

        raw = worker.execute(task_envelope, _make_runtime())
        assert len(raw.payload["work_items"]) == 5

        sanitized = worker.sanitize_output(raw)
        assert sanitized.payload == raw.payload

        evaluation = worker.evaluate_output(sanitized)
        assert evaluation.passed
        assert evaluation.confidence == 0.8

        envelope = worker.finalize(evaluation)
        assert envelope.status.value == "success"
        assert envelope.recommended_next_action == "advance_to_suggested"

    def test_harness_integration(self, task_envelope):
        """DiscoveryWorker runs successfully through the harness."""
        harness = Harness()
        worker = DiscoveryWorker()
        result = harness.run(worker, task_envelope)

        assert result.stage_reached == "finalize"
        assert result.result_envelope.status.value == "success"
        assert result.validation.valid
        assert result.context is not None
        assert result.raw_output is not None
        assert result.sanitized_output is not None
        assert result.evaluation is not None
        assert result.evaluation.passed
