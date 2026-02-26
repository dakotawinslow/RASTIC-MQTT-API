# RASTIC MQTT API — Claude Code Guide

## Project overview

A single-file Python service (`mqtt_api.py`) that:
1. Connects to an MQTT broker and subscribes to all topics
2. Maintains an in-memory dict of topic → `{name, last_message, timestamp}`
3. Serves that dict as JSON over a Flask HTTPS API at `/mqtt`

## Key files

| File | Purpose |
|---|---|
| `mqtt_api.py` | Entire application — MQTT client, Flask API, cert generation |
| `config.txt` | Runtime configuration (broker credentials, API port, TLS paths) |
| `test_unit.py` | 28 offline unit tests — no broker required |
| `test_config.py` | Config structure validation + live MQTT broker connectivity test |
| `pyproject.toml` | UV project config and dependencies |
| `uv.lock` | Locked dependency versions — commit this, do not edit manually |

## Architecture

- **Global state:** `topics: dict` and `topics_lock: threading.Lock` at module level, shared between the MQTT thread and Flask request handlers
- **MQTT thread:** Started as a daemon thread in `main()`, runs `client.loop_forever()`
- **Flask:** Runs in the main thread with SSL context; uses `app.test_client()` in tests (no real server needed)
- **Cert generation:** Uses the `cryptography` library; only runs if cert/key files are absent

## Package management — UV

This project uses UV. Always use `uv` commands, never bare `pip` or `python`.

```bash
uv sync                        # Install all deps (runtime + dev)
uv add <package>               # Add a runtime dependency
uv add --dev <package>         # Add a dev-only dependency
uv remove <package>            # Remove a dependency
uv run python mqtt_api.py      # Run the app
uv run pytest -v               # Run tests
```

## Running tests

```bash
uv run pytest test_unit.py -v       # Fast, offline — run these often
uv run pytest test_config.py -v     # Requires a live broker
uv run pytest -v                    # Everything
```

## Git workflow

**Commit granularly.** Commit early and often so the tree reads as a clear log of how the project evolved. Each commit should represent one coherent unit of work — a single behaviour change, a new test, a refactor step. Do not bundle unrelated changes into one commit.

**Push selectively.** Pushing upstream on every commit is not required. Push when a feature is ready to merge, when handing off work, or when the user asks.

**Branch for new features.** Any self-contained new feature gets its own branch. The workflow is:
1. `git checkout -b feature/<name>` before starting work
2. Commit incrementally to that branch as the feature develops
3. Merge to `main` only when the user confirms the feature is ready

Large structural changes (e.g. a new module, a significant refactor) should still be broken into a series of small, logical commits even within a single branch — not delivered as one giant commit at the end.

## Key conventions

- Timestamps are always ISO 8601 UTC (`datetime.now(timezone.utc).isoformat()`)
- Binary MQTT payloads that fail UTF-8 decoding are stored as hex strings
- Topic prefix filtering uses `k == filter or k.startswith(filter + "/")` — the trailing slash is intentional to prevent partial-word matches
- `load_config()` calls `sys.exit(1)` on a missing config file; tests cover this with `pytest.raises(SystemExit)`
- The Flask app object is module-level so tests can import it directly via `mqtt_api.app.test_client()`
