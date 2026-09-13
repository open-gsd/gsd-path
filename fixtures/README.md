# GSD Path test fixtures

Static samples for manual exploration and opt-in live tests. The automated
offline gate builds its own throwaway repos in temp directories; these fixtures
are for humans and dogfood-style runs.

| Path | Purpose |
| --- | --- |
| [`minimal-pipeline/`](minimal-pipeline/) | Brownfield widget-counter repo with a define-phase `.project/` state |
| [`tests/test_full_cycle.py`](../tests/test_full_cycle.py) | Programmatic full milestone disk contract (define → ship) |
| [`tests/dogfood.py`](../tests/dogfood.py) | Live host smoke fixture builder |

Copy `minimal-pipeline/` into a fresh git repo to exercise inspect/define handoffs
without running the full test module.
