"""Tests for the scout engine and ScoutWorker."""

import pytest

from foxhound.core.models import (
    ExecutionMode,
    ExecutionSnapshot,
    OpportunityState,
    PolicyRef,
    RecipeRef,
    TaskEnvelope,
)
from foxhound.harness.worker_protocol import (
    Capability,
    RuntimeHandle,
    WorkerClass,
)
from foxhound.scout.engine import (
    ALLOWED_LICENSES,
    ScoutEngine,
    ScoutSource,
    ScoutWorker,
    score_opportunity,
    source_to_opportunity,
)
from foxhound.storage.database import Database


@pytest.fixture
def db() -> Database:
    return Database(":memory:")


@pytest.fixture
def engine(db: Database) -> ScoutEngine:
    return ScoutEngine(db)


def _make_source(
    title: str = "Test Project",
    source_type: str = "github_trending",
    stars: int = 100,
    star_velocity: float = 5.0,
    license_type: str = "mit",
    language: str = "python",
) -> ScoutSource:
    return ScoutSource(
        title=title,
        source_type=source_type,
        source_url=f"https://github.com/test/{title.lower().replace(' ', '-')}",
        stars=stars,
        star_velocity=star_velocity,
        license_type=license_type,
        language=language,
        tags=["python", "cli"],
        evidence={"stars": stars},
    )


class TestScoring:
    def test_score_with_high_velocity(self) -> None:
        source = _make_source(star_velocity=20.0, stars=500)
        scores = score_opportunity(source)
        assert scores["credibility"] > 0.5
        assert scores["business_value"] > 0.3

    def test_score_low_velocity(self) -> None:
        source = _make_source(star_velocity=0.0, stars=5)
        scores = score_opportunity(source)
        assert scores["credibility"] <= 0.5

    def test_score_with_license(self) -> None:
        source = _make_source(license_type="mit")
        scores = score_opportunity(source)
        assert scores["actionability"] >= 0.8

    def test_score_without_license(self) -> None:
        source = _make_source(license_type="proprietary")
        scores = score_opportunity(source)
        assert scores["actionability"] < 0.8


class TestSourceToOpportunity:
    def test_converts_to_opportunity(self) -> None:
        source = _make_source()
        item = source_to_opportunity(source)
        assert item.opportunity_id.startswith("opp_")
        assert item.state == OpportunityState.OBSERVED
        assert item.trust_level.value == "untrusted"
        assert len(item.source_fingerprint) > 0

    def test_fingerprint_deterministic(self) -> None:
        source = _make_source(title="Same Project")
        item1 = source_to_opportunity(source)
        item2 = source_to_opportunity(source)
        assert item1.source_fingerprint == item2.source_fingerprint


class TestScoutEngine:
    def test_process_sources(self, engine: ScoutEngine) -> None:
        sources = [
            _make_source(title="Project A"),
            _make_source(title="Project B"),
        ]
        results = engine.process_sources(sources)
        assert len(results) == 2
        for item in results:
            assert item.state == OpportunityState.SUGGESTED

    def test_deduplicates(self, engine: ScoutEngine) -> None:
        sources = [
            _make_source(title="Same"),
            _make_source(title="Same"),
        ]
        results = engine.process_sources(sources)
        assert len(results) == 1

    def test_filters_disallowed_licenses(self, engine: ScoutEngine) -> None:
        sources = [
            _make_source(title="GPL Project", license_type="gpl-3.0"),
        ]
        results = engine.process_sources(sources)
        assert len(results) == 0

    def test_allows_empty_license(self, engine: ScoutEngine) -> None:
        sources = [
            _make_source(title="No License", license_type=""),
        ]
        results = engine.process_sources(sources)
        assert len(results) == 1

    def test_process_empty_sources(self, engine: ScoutEngine) -> None:
        results = engine.process_sources([])
        assert results == []


class TestScoutWorker:
    def test_worker_attributes(self) -> None:
        db = Database(":memory:")
        worker = ScoutWorker(db)
        assert worker.worker_name == "scout_worker"
        assert worker.worker_class == WorkerClass.ROOT
        assert Capability.NETWORK in worker.capabilities
        assert Capability.REPO_READ not in worker.capabilities
        assert Capability.REPO_WRITE not in worker.capabilities
        assert Capability.SHELL not in worker.capabilities

    def test_validate_input_requires_sources(self) -> None:
        db = Database(":memory:")
        worker = ScoutWorker(db)
        snap = ExecutionSnapshot(
            recipe_ref=RecipeRef(name="r", version="1.0.0", content_hash="h"),
            policy_ref=PolicyRef(name="p", version="1.0.0", content_hash="h"),
            config_hash="ch",
        )
        task = TaskEnvelope(
            task_id="t1", job_id="j1", run_id="r1", repo_id="repo",
            execution_snapshot=snap, input_payload={},
        )
        result = worker.validate_input(task)
        assert result.valid is False

    def test_validate_input_with_sources(self) -> None:
        db = Database(":memory:")
        worker = ScoutWorker(db)
        snap = ExecutionSnapshot(
            recipe_ref=RecipeRef(name="r", version="1.0.0", content_hash="h"),
            policy_ref=PolicyRef(name="p", version="1.0.0", content_hash="h"),
            config_hash="ch",
        )
        task = TaskEnvelope(
            task_id="t1", job_id="j1", run_id="r1", repo_id="repo",
            execution_snapshot=snap,
            input_payload={"sources": []},
        )
        result = worker.validate_input(task)
        assert result.valid is True

    def test_full_lifecycle(self) -> None:
        db = Database(":memory:")
        worker = ScoutWorker(db)
        snap = ExecutionSnapshot(
            recipe_ref=RecipeRef(name="r", version="1.0.0", content_hash="h"),
            policy_ref=PolicyRef(name="p", version="1.0.0", content_hash="h"),
            config_hash="ch",
        )
        sources = [_make_source(title="Worker Test").model_dump()]
        task = TaskEnvelope(
            task_id="t1", job_id="j1", run_id="r1", repo_id="repo",
            execution_snapshot=snap,
            input_payload={"sources": sources},
        )
        runtime = RuntimeHandle(
            execution_mode=ExecutionMode.READ_ONLY,
            capabilities={Capability.NETWORK},
            budget_remaining=1.0, timeout_remaining=300.0,
        )

        v = worker.validate_input(task)
        assert v.valid
        ctx = worker.build_context(task)
        assert ctx.trust_labels["sources"] == "untrusted"
        output = worker.execute(task, runtime)
        assert output.payload["opportunities_found"] == 1
        sanitized = worker.sanitize_output(output)
        evaluation = worker.evaluate_output(sanitized)
        assert evaluation.passed
        result = worker.finalize(evaluation)
        assert result.status.value == "success"


class TestAllowedLicenses:
    def test_mit_allowed(self) -> None:
        assert "mit" in ALLOWED_LICENSES

    def test_apache_allowed(self) -> None:
        assert "apache-2.0" in ALLOWED_LICENSES

    def test_bsd_allowed(self) -> None:
        assert "bsd-3-clause" in ALLOWED_LICENSES
        assert "bsd-2-clause" in ALLOWED_LICENSES
