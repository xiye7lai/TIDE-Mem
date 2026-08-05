# Changelog

## 0.1.0-amc2026 — 2026-08-05

Initial Agent Memory Challenge 2026 submission candidate.

- synchronous, idempotent Add API;
- evidence-only Search API with exact `user_id` isolation;
- immutable raw evidence and `gpt-4o-mini` structured memory cards;
- event-time-aware mutable-state ledger;
- FTS5/exact/temporal retrieval with reciprocal-rank fusion;
- evidence-ID-only LLM reranking and coverage-aware selection;
- Token, Bearer, and X-Api-Key authentication;
- public health endpoint and 30-day TTL cleanup;
- Docker/Compose and Render Blueprint deployment, CI/GHCR workflows with provenance and immutable digest publication, isolated account handoff, Smoke/load clients, application generation, scheduled health monitoring, and security policy;
- fifteen local tests including a mocked full API-mode chain and application-generator validation.
