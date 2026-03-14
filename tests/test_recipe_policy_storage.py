"""Tests for recipe, policy, and rule suggestion storage operations."""

import pytest

from foxhound.storage.database import (
    Database,
    PolicyStore,
    RecipeStore,
    RuleSuggestionStore,
)


@pytest.fixture()
def db() -> Database:
    return Database(":memory:")


class TestRecipeStore:
    """Test recipe version persistence."""

    def test_save_and_get(self, db: Database) -> None:
        store = RecipeStore(db)
        store.save("test_recipe", "1.0.0", "abc123", "builtin", "/path/to/recipe.yaml")
        result = store.get("test_recipe", "1.0.0")
        assert result is not None
        assert result["name"] == "test_recipe"
        assert result["version"] == "1.0.0"
        assert result["content_hash"] == "abc123"
        assert result["source_scope"] == "builtin"

    def test_get_nonexistent(self, db: Database) -> None:
        store = RecipeStore(db)
        assert store.get("nope", "1.0.0") is None

    def test_get_latest(self, db: Database) -> None:
        store = RecipeStore(db)
        store.save("recipe", "1.0.0", "hash1", "builtin")
        store.save("recipe", "2.0.0", "hash2", "builtin")
        result = store.get_latest("recipe")
        assert result is not None
        assert result["version"] == "2.0.0"

    def test_list_all(self, db: Database) -> None:
        store = RecipeStore(db)
        store.save("alpha", "1.0.0", "h1", "builtin")
        store.save("beta", "1.0.0", "h2", "repo")
        results = store.list_all()
        assert len(results) == 2
        names = {r["name"] for r in results}
        assert names == {"alpha", "beta"}

    def test_upsert_same_version(self, db: Database) -> None:
        store = RecipeStore(db)
        store.save("recipe", "1.0.0", "hash1", "builtin")
        store.save("recipe", "1.0.0", "hash2", "repo")
        result = store.get("recipe", "1.0.0")
        assert result is not None
        assert result["content_hash"] == "hash2"


class TestPolicyStore:
    """Test policy version persistence."""

    def test_save_and_get(self, db: Database) -> None:
        store = PolicyStore(db)
        store.save("default", "1.0.0", "def123", "builtin")
        result = store.get("default", "1.0.0")
        assert result is not None
        assert result["name"] == "default"
        assert result["content_hash"] == "def123"

    def test_get_nonexistent(self, db: Database) -> None:
        store = PolicyStore(db)
        assert store.get("nope", "1.0.0") is None

    def test_get_latest(self, db: Database) -> None:
        store = PolicyStore(db)
        store.save("policy", "1.0.0", "h1")
        store.save("policy", "2.0.0", "h2")
        result = store.get_latest("policy")
        assert result is not None
        assert result["version"] == "2.0.0"

    def test_list_all(self, db: Database) -> None:
        store = PolicyStore(db)
        store.save("p1", "1.0.0", "h1")
        store.save("p2", "1.0.0", "h2")
        results = store.list_all()
        assert len(results) == 2


class TestRuleSuggestionStore:
    """Test rule suggestion persistence."""

    def test_save_and_get(self, db: Database) -> None:
        store = RuleSuggestionStore(db)
        store.save(
            suggestion_id="rs_001",
            rule_name="new_rule",
            rule_type="soft",
            condition="pattern detected",
            action="require approval",
            repo_id="repo_1",
            evidence="seen in 5 runs",
            confidence=0.85,
        )
        result = store.get("rs_001")
        assert result is not None
        assert result["rule_name"] == "new_rule"
        assert result["confidence"] == 0.85
        assert result["state"] == "pending_review"

    def test_get_nonexistent(self, db: Database) -> None:
        store = RuleSuggestionStore(db)
        assert store.get("nope") is None

    def test_list_by_state(self, db: Database) -> None:
        store = RuleSuggestionStore(db)
        store.save("rs_1", "rule1", "hard", "c1", "a1")
        store.save("rs_2", "rule2", "soft", "c2", "a2")
        results = store.list_by_state("pending_review")
        assert len(results) == 2

    def test_update_state(self, db: Database) -> None:
        store = RuleSuggestionStore(db)
        store.save("rs_1", "rule1", "hard", "c1", "a1")
        assert store.update_state("rs_1", "approved", reviewed_by="user")
        result = store.get("rs_1")
        assert result is not None
        assert result["state"] == "approved"
        assert result["reviewed_by"] == "user"
        assert result["reviewed_at"] is not None

    def test_update_nonexistent(self, db: Database) -> None:
        store = RuleSuggestionStore(db)
        assert not store.update_state("nope", "approved")
