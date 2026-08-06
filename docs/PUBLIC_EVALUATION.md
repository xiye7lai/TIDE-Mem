# Public Retrieval Evaluation

This report records a development proxy, not an official Agent Memory
Challenge leaderboard score. The challenge-fixed submission configuration
still uses `gpt-4o-mini`; the alternate model below was used only because it
was the available development endpoint.

## Setup

- Dataset: LoCoMo-Refined public textual subset
- Sample: first 50 eligible questions from `conv-26`
- Scored questions: 49 (one question has no textual evidence label)
- Model: `gpt-5.6-luna` through an OpenAI-compatible Chat Completions endpoint
- Memory view: `full`
- Retrieval top-k: 100
- Rerank candidates: 20
- Reasoning effort: `none`
- Add protocol: at most 20 messages and 2,000 words per synchronous request
- Search concurrency: 4

No provider credential, response payload, or private endpoint is stored in the
repository.

## Tuned result

| Metric | Value |
|---|---:|
| MRR | 0.764519 |
| NDCG@10 | 0.736880 |
| Evidence Recall@10 | 0.785714 |
| Evidence Recall@100 | 0.862245 |
| RecallAny@100 | 0.897959 |
| RecallAll@100 | 0.816327 |
| Search p50 | 10.630 s |
| Search p95 | 22.966 s |

The candidate-generation change increased normalized RecallAll@100 from
0.775510 to 0.816327 on the same 50-question slice. Category-1
RecallAll@100 increased from 0.40 to 0.70. MRR varied from 0.769682 to
0.764519 across the two Luna runs, which is within the observed stochastic
reranking variation.

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

- The 50 questions come from one conversation, so this is a regression and
  tuning slice rather than a representative benchmark estimate.
- Answer generation and judge scoring were not run.
- The alternate-model result is not challenge-compliant and must not be
  reported as an official score.
- A final submission should be rebuilt and smoke-tested with the
  challenge-required model and platform concurrency.
