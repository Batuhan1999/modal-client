# Modal deployment fingerprint probe

This personal fork adds an **opt-in CLI experiment**, not a production-safe
replacement for Modal's deployment logic. It changes no Modal protocol or
server behavior. On a matching local fingerprint, the CLI returns before
calling the deployment API. On a miss it uses Modal's normal deployment path.
For simple file-based functions, the fork also ports mini-modal's AST-selected
source packaging and local-import discovery into an experimental decorator.

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

## AST-selected artifact follow-up

The `ast_function` decorator in the fork finds same-file globals and helper
functions used by the target, then follows static local imports recursively.
It mounts that reduced source tree at the module path Modal already expects,
with Modal's normal full-file source mount disabled. Use `include_modules` for
local imports made dynamically. The CLI fingerprints the artifact, so editing
an unrelated function in the original file does not trigger deployment:

```sh
./.venv/bin/modal deploy --strategy recreate \
  --fingerprint-cache .venv/ast-fingerprint-probe.json \
  experiments/ast_fingerprint_probe.py

./.venv/bin/python -c 'import modal; print(modal.Function.from_name("mini-modal-ast-fingerprint-probe-20261001", "compute").remote(20))'
```

Observed on 2026-10-01, again as single exploratory runs:

| Action | CLI wall time | Remote result |
| --- | ---: | --- |
| First AST artifact deploy | 3.19 s | `compute(20) == 41` |
| Change only `unrelated` in source | 0.53 s | Deployment API skipped |
| Change referenced helper `FACTOR` from 2 to 3 | 5.09 s | New artifact deployed; `compute(20) == 61` |
| Force deploy unchanged | 1.84 s | Modal reports no changes |

This is deliberately narrow: module-level functions, one AST decorator, no
custom App defaults or classes. The extractor does not prove that arbitrary
Python dynamic behavior, external files, or Modal resources are unchanged.
Additional configuration must be included explicitly with
`--fingerprint-input`, and an out-of-band deployment still requires
`--force-deploy` to refresh the local cache. It is not production-safe yet.

## Boltons OSS workload

The existing Boltons 26.2.0 workload was deployed to two separate disposable
Modal apps on 2026-10-01. The baseline used
`Image.add_local_python_source("boltons", "boltons_workload")`; the experimental
app used `ast_function` around the same `boltons_workload.analyze` call. Both
remote functions returned 40 chunks summing to 499,500 for `range(1000)` with
`chunk_size=25`. The reduced source tree contained five Python files (65,431
source bytes), versus 31 Python files (616,592 source bytes) in the baseline
package plus workload. These are local file counts, not measured Modal upload
bytes.

| Deployment | Baseline CLI wall | AST + fingerprint CLI wall |
| --- | ---: | ---: |
| First deploy | 2.38 s | 2.68 s |
| Unchanged redeploy 1 | 1.86 s | 0.28 s |
| Unchanged redeploy 2 | 1.83 s | 0.29 s |
| Unchanged redeploy 3 | 1.53 s | 0.33 s |
| Unchanged mean | 1.74 s | 0.30 s |

The unchanged pairs alternated order. Modal reported "no changes detected"
for the baseline, but it still contacted the deployment service; the local
AST fingerprint skipped that API call entirely. The single first-deploy pair
does **not** show a cold-deploy improvement. One remote invocation took 3.24 s
for the baseline and 2.97 s for AST, including potential cold-start effects;
this is not enough to infer a runtime difference. Network, server state, and
host load were uncontrolled, so treat all timings as exploratory.

Validation in the fork's isolated environment: the SDK's `dev` dependency
group and the additional `httpx2` package required by the installed Starlette
test client were installed. Protobuf type stubs were generated with
`py/compile_protos.py`. The SDK suite was run in three nonoverlapping parts:
2,721 passed / 6 skipped before `static_types_test.py`, 2 static-types tests
passed, and 286 passed / 1 skipped after it. The terminal-only selector file
was run separately with a TTY and all 21 tests passed. In total: **3,030
passed, 7 skipped**. The segmentation was needed because pytest's normal
capture makes the selector see a non-TTY. Ruff lint and format checks passed.
