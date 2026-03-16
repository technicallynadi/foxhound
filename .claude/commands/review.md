Review all code changes on the current branch against `main`.

1. Run `git diff main...HEAD --stat` to identify all changed files.
2. Run `git diff main...HEAD` to get the full diff.
3. Read the full code review checklist from `docs/review/foxhound_code_review_prompt.md`.
4. Execute every check in that prompt against the current changes:
   - Architecture rule compliance
   - Code quality
   - Test coverage
   - Acceptance criteria (look up the relevant issues from commit messages)
   - Integration checks (run `uv run pytest tests/`, `uv run ruff check .`, `uv run mypy foxhound/`)
5. Output the review in the format specified in the code review prompt.
6. If the verdict is NEEDS CHANGES, list specific fixes required. Do not proceed with commits or PRs until re-review passes.
