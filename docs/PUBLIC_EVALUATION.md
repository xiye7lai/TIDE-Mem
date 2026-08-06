# Public Retrieval Evaluation

This report records a development proxy, not an official Agent Memory
Challenge leaderboard score. The challenge-fixed submission configuration
still uses `gpt-4o-mini`; the alternate model below was used only because it
was the available development endpoint.

## Cross-conversation final proxy

- Dataset: LoCoMo-Refined public textual subset
- Sample: deterministic category-stratified questions across all 10 public
  conversations
- Scored questions: 59 (category counts: 19/12/8/20 for categories 1/2/3/4)
- Model: `gpt-5.6-luna` through an OpenAI-compatible Chat Completions endpoint
- Memory view: `full`
- Retrieval top-k: 100
- Rerank candidates: 20
- Reasoning effort: `none`
- Add protocol: at most 20 messages and 2,000 words per synchronous request
- Search concurrency: 8

No provider credential, response payload, or private endpoint is stored in the
repository.

### Result

| Metric | Baseline | Final tuned |
|---|---:|---:|
| MRR | 0.779266 | 0.758619 |
| NDCG@10 | 0.728091 | 0.731778 |
| Evidence Recall@10 | 0.796610 | 0.810734 |
| Evidence Recall@100 | 0.903955 | 0.923729 |
| RecallAny@100 | 0.949153 | 0.966102 |
| RecallAll@100 | 0.847458 | 0.881356 |
| Category-1 RecallAll@100 | 0.578947 | 0.736842 |
| Search p50 | 11.619 s | 12.837 s |
| Search p95 | 20.002 s | 28.919 s |

The final source-diverse rerank window and bounded session expansion improve
complete multi-evidence coverage, especially on category 1. The small MRR
tradeoff reflects a deliberate preference for returning all supporting
evidence within top 100; Luna reranking also has observed run-to-run variance.
No cold-Add latency is reported because the long run was safely resumed through
idempotent request IDs after the execution environment interrupted it.

## Ablation observations

On the initial fixed 10-question slice, reducing the rerank window from 80 to
20 preserved MRR (1.0) and NDCG@10 (0.922629), while reducing Search p50 from
19.313 seconds to 13.877 seconds. A 40-candidate rerank did not improve the
failed-question subset. The default is therefore 20 candidates.

Structured memory cards carried most of the measured quality on that small
slice. Raw-only retrieval reached MRR 0.82 and NDCG@10 0.746349, while the
full and cards views both reached MRR 1.0 and NDCG@10 0.922629. This is not
enough evidence to remove raw memories from the final method: raw evidence is
still useful for exact wording, provenance, and cases where extraction omits a
detail.

## Limitations

- The stratified 59-question sample is broader than the initial one-conversation
  slice but remains a development proxy rather than the full benchmark.
- Answer generation and judge scoring were not run.
- The alternate-model result is not challenge-compliant and must not be
  reported as an official score.
- A final submission should be rebuilt and smoke-tested with the
  challenge-required model and platform concurrency.
