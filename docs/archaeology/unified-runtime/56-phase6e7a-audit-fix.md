# 56a — Phase 6-E.7.1 Audit Recovery

> 阶段：Phase 6-E.7.1（E.7 provenance audit 的 recovery；不重复失败的
> provenance patch）。
> 约束：无 live provider call；无阈值 / prompt / parser / contract / retry /
> production runtime 变更；无 E.8；无 promotion；无 commit / push。

## Status

```text
GATE = HOLD
E.6 = REGRESSION_SAFETY_CONFIRMED
E.7 evidence artifacts unchanged from 22890c1
registered policy byte-identical to ca06a9a
threshold diff = NONE
```

## Previous attempt violations (why this recovery exists)

1. `promotion-policy.json` was edited in place after E.7 registration.
2. manifest attributed the edited bytes to `ca06a9a`.
3. no immutable registered/final policy artifacts existed.
4. `promotion-matrix.json` was rewritten (`run_git_commit` changed).
5. `promotion-stats.json` was rewritten.
6. `promotion-gate.json` was rewritten (rules/reason/blocking_conditions added).
7. provenance tests validated disk-vs-manifest instead of
   registered bytes == `git show ca06a9a`.
8. policy lifecycle documentation was missing.

## Recovery

- Restored E.7 evidence byte-for-byte from `22890c1`:
  `promotion-matrix.json`, `promotion-stats.json`, `promotion-gate.json`,
  `promotion-runs.jsonl`; per-attempt raw JSON were already unchanged.
- Restored `promotion-policy.json`, `provider_probe.py`,
  `tests/test_promotion_gate.py` from `ca06a9a` (registered runtime baseline).
- Registered policy archived immutably:
  `promotion-policy-e7-v1-registered.json`
  SHA256 `d7a75b97165f6b628d9edd25afd96aa68af31ebeb4c78a11736f19dfcbf97ddb`
- Final audited policy:
  `promotion-policy-e7-v1-final.json`
  SHA256 `d4c66daae751869405569cd4a06ba2b7c187f963525a6174027102c133e252ea`
- Manifest rebuilt (`promotion-gate-e7-manifest-2`) with explicit
  `registered_policy` / `final_policy` sections;
  `audit_revision_commit = NOT_AVAILABLE_YET`（不 invent commit hash）。

## Why

- registered policy cannot be overwritten;
- final policy must be versioned separately;
- E.7 raw evidence must remain immutable;
- audit changes must never rewrite experiment evidence.

## Registered -> final differences (complete list)

1. `policy_id`: `promotion-policy-e7-v1` -> `promotion-policy-e7-v1-final`
2. `statistical_method.rate`:
   `success_count / n_target rounds` -> `success_count / n_contract`
3. `rate_rules`: added explicit `target_fix_absent`
   (`case_set=target, arm=B-prime, metric=inc_count, op=ge, threshold=5`)

No other differences: thresholds, sample sizes, transport limits, Wilson z,
decision semantics, fixed conditions, and all other rules are unchanged.

## Policy loading semantics (`provider_probe.py`)

- `_load_promotion_policy_version(version)` loads immutable revisions
  (`registered`, `final`) from `artifacts/promotion-gate/`.
- `_policy_manifest()` emits `registered_policy` / `final_policy` provenance;
  live gate logic is unchanged and still compares the mutable
  `promotion-policy.json` against `promotion_policy()` (registered semantics).
- historical E.7 evidence refers to registered policy (`policy_ref =
  promotion-policy-e7-v1`, `run_git_commit = ca06a9a` in committed bytes);
  audit/final validation refers to the final policy file.
- final policy must prove threshold/semantic equivalence to registered policy
  (enforced by provenance tests); no live provider invocation is needed.

## Verification

```text
promotion gate offline tests  = 19 passed（tests/test_promotion_gate.py）
全量 evaluation tests         = 255 passed, 11 skipped, 8 subtests passed
py_compile                    = compileall OK（provider_probe / judge_provider /
                                phase6e_matrix / calibration / tests）
secret scan                   = artifacts/promotion-gate/ -> 0 命中
summarize reproduction        = temp-dir --summarize-promotion-gate：
                                GATE=HOLD, policy_frozen=True,
                                e6=REGRESSION_SAFETY_CONFIRMED；
                                gate.json byte-identical to 22890c1；
                                matrix/stats 仅 run_git_commit 不同（当前 HEAD）
```
