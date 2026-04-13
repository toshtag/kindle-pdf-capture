# Contributing

## Development setup

```bash
git clone https://github.com/toshtag/kindle-pdf-capture.git
cd kindle-pdf-capture
uv sync
```

## Running tests

```bash
uv run pytest
uv run pytest --cov=kindle_pdf_capture --cov-report=term-missing
```

All tests are hermetic — no macOS permissions or a running Kindle instance are needed.

## Linting and formatting

```bash
uv run ruff check .
uv run ruff format .
```

## Commit conventions

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(scope): add something new
fix(scope): fix a bug
test(scope): add or update tests
docs: update documentation
chore: maintenance tasks
ci: CI/CD changes
refactor(scope): code restructuring without behavior change
```

## Branch and PR workflow

1. Create a branch: `git checkout -b feat/my-feature`
2. Make changes following TDD (test commit first, then implementation)
3. Open a pull request — use the bilingual PR template
4. CI must pass (Python 3.11 and 3.12) before merging
5. Merge with merge commit (squash and rebase are disabled)

## Reporting issues

Use [GitHub Issues](https://github.com/toshtag/kindle-pdf-capture/issues).
For bugs, include your macOS version, Python version, and the full error output.
