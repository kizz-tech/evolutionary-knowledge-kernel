# Laya advisory decisions

## D1 — Start with shadow advice

The first capability exposes semantic labels beside the unchanged baseline. It
does not rerank or filter. This makes model error cheap and visible to the agent.

## D2 — Agent recheck is explicit

Every successful advisory envelope states that exact source verification remains
required before reliance. Confidence is model output, not correctness evidence.

## D3 — Authorization precedes model input

Only already authorized candidates may be summarized for the advisor. A model
cannot nominate or retrieve records outside that projection.

## D4 — The kernel has no Laya dependency

The application depends on a small advisor port. A future MLX implementation is
an adapter selected by the host. Unavailable advice leaves existing behavior
unchanged.

## D5 — Training is owner-safe

The initial checkpoint uses synthetic/declassified data. Raw personal and company
records are not mixed. Owner-specific training, if justified later, produces an
owner-specific checkpoint and evaluation.

