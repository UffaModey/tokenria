# Contributing to Tokenria

Thanks for considering contributing. This is an early-stage, solo-maintained project, so the
process is intentionally lightweight.

## Getting set up

See [DEV.md](DEV.md) for the full local setup walkthrough — virtual environment, dependencies,
ingesting sample data, and running the server.

## Before opening a pull request

```bash
ruff check .      # lint
ruff format .     # format
pytest            # tests must pass
```

All three run in CI on every pull request; a PR won't be merged with a red build.

## Guidelines

- **Open an issue before a large change.** For anything beyond a small fix, open an issue first to
  discuss the approach — this project follows a fairly specific build order and design philosophy
  (see the README's Design Principles section), and it's better to align before you spend time on
  an implementation.
- **Keep changes scoped.** Small, focused PRs are much easier to review than large ones that mix
  unrelated changes.
- **Add or update tests** for any behavior change — see `tests/` for the existing patterns
  (fixture-based JSONL parsing tests, FastAPI `TestClient` route tests).
- **No unrelated formatting churn.** Please don't run a formatter across files you didn't
  otherwise touch.

## Reporting bugs

Open a GitHub issue with steps to reproduce. If it's a security issue, see
[SECURITY.md](SECURITY.md) instead of filing a public issue.

## Code of Conduct

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md) — please read it before
participating.
