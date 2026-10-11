# Release 0.10.0: reliable continuation of real work

This increment connects preservation, discovery and exact continuation across
research, design, planning and implementation. See the [release design](releases/0.10/design.md)
and [delivery status](releases/0.10/status.md).

## What changed

- Historical work keeps exact selected bytes and state provenance, with separate
  authorized current navigation. CLI navigation preserves the original route.
- `work find` matches bounded readable linked events, naming current parent and
  exact event with excerpt, reason and coverage. `work show` includes authorized
  event grounds and improvement annotations.
- `retain --manifest FILE [--wait]` freezes explicit files into existing retention.
  Destination and inventory are visible, capacity is preflighted and completion
  requires exact read-back. Queue retries preserve frozen bytes.
- Exact opening receipts carry observed host/session/workspace identity. Only a
  unique exact compatible delivery is linked. Legacy marks and unknown or
  ambiguous identity stay distinct; `observe status` exposes linkage counts.
- `guide show --domain DOMAIN --phase PHASE` offers the four phases independently
  of domain. Existing method packages and the ordinary zero-call path remain.

The canonical format stays 0.1; owner boundaries, acceptance, subject verification
and host trust retain their owners. [Continuous work](continuous-work.md) describes
commands, declared capacity and partial states. Technical delivery and useful
transfer in subsequent real tasks remain separate claims. [Status](releases/0.10/status.md)
records verification and installation; mechanism tests do not establish benefit.
