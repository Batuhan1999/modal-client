# Modal deployment fingerprint probe

This personal fork adds an **opt-in CLI experiment**, not a production-safe
replacement for Modal's deployment logic. It changes no Modal protocol or
server behavior. On a matching local fingerprint, the CLI returns before
calling the deployment API. On a miss it uses Modal's normal deployment path.

The checkout is based on Python SDK `py/v1.5.5`. Run from the repository root
with the isolated editable installation in `.venv`:

```sh
./.venv/bin/modal deploy \
  --fingerprint-cache .venv/fingerprint-probe.json \
  experiments/fingerprint_probe.py

./.venv/bin/python -c 'import modal; print(modal.Function.from_name("mini-modal-fingerprint-probe-20261001", "increment").remote(41))'
```

Repeat the deploy command without changes to exercise the local fast path.
Use `--force-deploy` to contact Modal even when the fingerprint matches. Pass
`--fingerprint-input PATH` once for each additional local file affecting the
app. This prototype accepts script-mode `.py` references only. A cache hit
does not hydrate the local `App`; the example uses `Function.from_name()` for
remote invocation.

The selected files are **not automatically complete**. A changed local module,
image recipe, secret, dependency, remote environment, or deployment from another
machine can leave a matching local cache stale unless its input is included or
the deploy is forced. This cache must not be enabled for a production app as-is.

## Observed on 2026-10-01

Using the disposable app in the `batuhan1999` workspace:

| Action | CLI wall time | Outcome |
| --- | ---: | --- |
| First deploy | 2.28 s | Deployed; remote `increment(41)` returned `42` |
| Repeat unchanged | 0.28 s | Local cache hit; no Modal deployment API call |
| Changed source, rolling deploy | 2.60 s | New app version published; an existing worker initially returned the old value |
| Changed source, recreate deploy | 7.53 s | New worker returned `45` for `increment(41)` |
| Repeat unchanged, recreate strategy | 0.40 s | Local cache hit |
| Force deploy unchanged, recreate strategy | 1.82 s | Contacted Modal; server reported no changes |

These are single exploratory timings, not a benchmark. The old value after a
rolling deploy was resolved by recreating workers; it did not indicate a cache
hit. The local cache only applies to the `modal deploy` CLI, not `App.deploy()`
or function calls. Invocation still contacts Modal normally.
