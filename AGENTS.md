# AGENTS.md

## Cursor Cloud specific instructions

### Repository layout / gotcha
- The `main` branch is intentionally near-empty (only `README.md`). The actual product code lives on feature branches. As of this writing the runnable product is on `cursor/iphone-date-alarm-a7c3` (a Chinese-holiday-aware iPhone alarm recommender CLI). If you find no application code on your current branch, that is expected — check out or merge the relevant feature branch.

### Runtime & dependencies
- Pure **Python 3** (standard library only). Python 3.12 is preinstalled in the environment; nothing else is required.
- `requirements.txt` (when present on a branch) is comment-only — there are no third-party packages to install. The startup update script is effectively a no-op.
- There are **no long-running services, databases, or secrets**. The product is a one-shot CLI, so there is nothing to place in `start`/`terminals`.

### Run / test (run from the repo root of a branch that contains the code)
- Tests: `python3 -m unittest discover -s tests -v`
- Run the CLI: `python3 -m alarm_recommender <subcommand>` (e.g. `recommend`, `day`, `holidays`, `guide`). See the branch's `README.md` for full examples, including `--ics` export.
- No linter or build system is configured — the CLI runs directly from source.
