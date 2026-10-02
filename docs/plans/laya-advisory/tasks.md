# Laya advisory implementation tasks

| Task | Scope | Depends on | Completion gate |
| --- | --- | --- | --- |
| T0 | Preserve this specification and decisions | — | Reviewable plan exists |
| T1 | Add model-neutral advisor port and pure shadow envelope | T0 | Focused unit tests; no baseline effect |
| T2 | Build a local Laya adapter outside the kernel contract | T1 | Pinned model identity; bounded local call; no EKK writes |
| T3 | Create synthetic/declassified RU/EN evaluation fixtures | T1 | Frozen fixtures and expected labels |
| T4 | Run offline comparison against lexical baseline | T2, T3 | Recall, accuracy, ECE, stability and latency report |
| T5 | Add opt-in shadow reporting to read-only search | T4 | Existing result order unchanged; agent can exact-read |
| T6 | Train and calibrate an EKK-specific checkpoint | T4 | Held-out improvement and owner-safe dataset receipt |
| T7 | Evaluate applied reranking of optional candidates | T5, T6 | Separate approval; no mandatory-record regression |

T1 is the only implementation slice authorized by this initial plan. T2–T7 remain
pending evidence and do not inherit permission for live integration or training on
private data.

