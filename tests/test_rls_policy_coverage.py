from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


_RLS_SQL_PATHS = (
    _repo_root() / "scripts" / "supabase_rls_policies.sql",
    _repo_root() / "supabase" / "migrations" / "20260405180000_foxhound_rls_policies.sql",
)


@pytest.mark.parametrize("sql_path", _RLS_SQL_PATHS, ids=["scripts", "supabase_migration"])
def test_rls_script_covers_fox106_tables(sql_path: Path) -> None:
    sql = sql_path.read_text()

    for table in (
        "dossiers",
        "foxhound_briefs",
        "agent_activities",
        "watchdog_checks",
        "recon_dossiers",
        "tinyfish_brief_cache",
    ):
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;" in sql

    for policy in (
        'CREATE POLICY "users_read_own_dossiers" ON dossiers',
        'CREATE POLICY "users_read_own_briefs" ON foxhound_briefs',
        'CREATE POLICY "users_read_own_activities" ON agent_activities',
        'CREATE POLICY "users_read_own_watchdog_checks" ON watchdog_checks',
        'CREATE POLICY "users_read_own_recon_dossiers" ON recon_dossiers',
        'CREATE POLICY "users_read_own_tinyfish_cache" ON tinyfish_brief_cache',
    ):
        assert policy in sql


def test_init_db_includes_inline_rls_migration() -> None:
    source = (_repo_root() / "app" / "db" / "session.py").read_text()
    assert "Inline RLS migration (FOX-106)" in source
    assert "ALTER TABLE dossiers ENABLE ROW LEVEL SECURITY" in source
    assert "ALTER TABLE tinyfish_brief_cache ENABLE ROW LEVEL SECURITY" in source
    assert "CREATE POLICY users_read_own_dossiers ON dossiers" in source
    assert "CREATE POLICY users_read_own_watchdog_checks ON watchdog_checks" in source
    assert "CREATE POLICY users_read_own_recon_dossiers ON recon_dossiers" in source
    assert "CREATE POLICY users_read_own_tinyfish_cache ON tinyfish_brief_cache" in source
