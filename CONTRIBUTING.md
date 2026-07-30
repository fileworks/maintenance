# Contributing

This package is imported as `maintenance.*` from the directory that contains it,
alongside the repositories it evaluates. Clone it into a workspace that looks
like this:

```
fileworks/
├── maintenance/        ← this repository
├── media-sorter/
├── immich-export/
├── paperless-export/
├── unpacksort/
└── homebrew-tap/
```

Run everything from the **parent** directory, not from inside this repository:

```sh
cd maintenance && uv sync --locked --all-groups && cd ..

uv run --project maintenance ruff format --check maintenance/
uv run --project maintenance ruff check maintenance/
uv run --project maintenance mypy --strict --config-file maintenance/pyproject.toml maintenance/
uv run --project maintenance python -m pytest maintenance/tests
uv run --project maintenance python -m maintenance.cli --matrix
```

CI reproduces this by checking out into a `maintenance/` subdirectory.

## What belongs here

Cross-repository rules, as **executable checks**. A rule that lives only in a
README is a rule that drifts. If you find yourself writing "every repository
should…" in prose, write it as a control in `policy.py` and a gate in `gates.py`
instead.

Project-specific facts belong in the repository that owns them, never here.

## Conventions

- Conventional Commits, imperative and scoped. No AI or agent attribution.
- Types strict: `mypy --strict` and `ruff` must both be clean.
- The two branding tests need `librsvg2-bin` and Pillow. They skip locally
  without them; the `branding` CI job installs both and fails if they skip.
- Nothing here may write to a sibling repository as a side effect of being
  tested. Tests that exercise the branding generator copy it into `tmp_path`
  first.
- Remote settings are never written by a test, and never by `cli.py`. Only
  `maintenance.reconcile` writes, only from an explicit plan.
