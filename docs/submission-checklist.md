# Submission Checklist

Final quality gate for GitHub release.

## Required (blocking — all must pass)

| Item | Result | Notes |
|---|---|---|
| `pytest` — all tests pass | PASS | 270 passed, 2 skipped (real LLM skip) |
| `python -m compileall src tests scripts` | PASS | No syntax errors |
| git diff --check | PASS | No whitespace errors |
| No API key in source files | PASS | Checked via `scripts\check_secrets.py` |
| No API key in git history | PASS | No commits with secrets |
| No `.env` in commit | PASS | Listed in `.gitignore` |
| No `data/*.db` in commit | PASS | Listed in `.gitignore` |
| No `reports/**/*.db` in commit | PASS | Added to `.gitignore` |
| No `__pycache__` / `.pytest_cache` | PASS | Listed in `.gitignore` |
| README commands executable | PASS | Verified `python -m src.cli --help` |
| Knowledge docs sanitized | PASS | Sensitive content removed; sample docs only |
| Core requirements implemented (25/25) | PASS | See `docs/submission-audit.md` |
| Git remote configured | PASS | `origin → https://github.com/cecilia10445/minimal-agent.git` |
| Branch is `main` | PASS | |

## Non-blocking (advisory)

| Item | Result | Notes |
|---|---|---|
| Real LLM re-run completed | FAIL | DashScope free quota exhausted — code fixes verified, re-run requires quota top-up |
| Context comparison generated | FAIL | Requires fresh runs (quota exhaustion) — see `reports/context-comparison.md` placeholder |
| Semantic probes 10/10 | FAIL | 8/10 from real Hybrid run (2 scorer false negatives fixed) |
| Context baseline metrics accurate | FAIL | Old reports have buggy event counting — code fixed, re-run needed |
| Recording script verified | MANUAL | Follow `docs/recording-script.md` — requires API key |
| .env.example complete | PASS | All env vars documented |

## Final Decision

**All blocking items PASS. Ready to push.**

Non-blocking failures are documented:
1. API quota exhaustion prevents fresh context baselines
2. Old report metrics are preserved but known to have calculation bugs (fixed in current code)
3. README accurately reflects these limitations
