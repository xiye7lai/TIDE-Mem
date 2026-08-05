# Security and evaluation-data handling

## Scope

TIDE-Mem stores conversation evidence only to implement the current memory evaluation. It must not use evaluation data or derived records for training, fine-tuning, product analytics, dataset reconstruction, publication, or sharing.

## Identity isolation

`user_id` is the sole Search scope. The implementation applies the exact requested value to every FTS, exact-match, recency, and ID-fetch query. It does not provide a global-search fallback. `session_id` is provenance metadata and cannot broaden the retrieval boundary.

Tests include a canary secret inserted for one user and verify that a different user receives no copy of it.

## Authentication

- Health is intentionally unauthenticated.
- Add/Search accept `X-Api-Key`, `Authorization: Bearer`, or `Authorization: Token`.
- Comparison uses constant-time `hmac.compare_digest`.
- Missing/invalid credentials return HTTP 401 with no secret material.
- The participant-generated Memory System Key and organizer-issued Eval Key are different secrets.

## Prompt-injection boundary

Source conversations, questions, options, and candidate contents are explicitly labeled untrusted in all LLM system prompts. The LLM is asked for structured extraction, evidence plans, or evidence IDs—not executable instructions and not final answers. JSON outputs are schema-coerced; rerank IDs must already exist in the current user's candidate set.

No prompt-injection defense is absolute. The immutable source view and programmatic identity/ID validation limit the effect of malformed model output.

## Logging

The application logs:

- service/version/model startup metadata;
- request ID and hashed user/session identifiers for successful Add;
- record counts;
- error class and stack traces for operator debugging;
- TTL deletion counts.

It does not intentionally log:

- conversation bodies;
- questions or options;
- retrieved evidence contents;
- authorization headers;
- provider keys;
- Memory System or Eval keys.

Reverse proxies and infrastructure providers should also be configured not to capture request bodies or authentication headers.

## Storage

- SQLite uses WAL mode, foreign keys, parameterized SQL, and a persistent volume.
- Add is an atomic transaction across request identity, memory rows, FTS rows, and state updates.
- Stable record IDs are SHA-256-derived identifiers, not source content.
- The database file and `.env` should be readable only by the service account/operator.
- Disk encryption is recommended for the host and backups.

## Retention and deletion

`TIDE_TTL_DAYS=30` is the default. Cleanup runs at startup and periodically. It removes expired memory and FTS records, then empty request rows. Operational backups and snapshots must be deleted within the same policy window.

## Network

- expose only HTTPS to the public internet;
- keep the raw application port bound to localhost or a private container network;
- do not embed credentials in URLs;
- use a public routable hostname, not a private, loopback, or link-local address;
- restrict SSH and management ports separately;
- keep base images and host security updates current without silently changing the evaluated application behavior.

## Incident response

For suspected key exposure:

1. rotate the Memory System Key immediately;
2. update the controlled competition configuration;
3. restart the service with the new key;
4. inspect access metadata without exposing payloads;
5. notify the organizer through the official contact channel with a redacted description and relevant Job/Test ID;
6. rotate the provider key if it may also have leaked.

For a version-affecting code change before Full, create and disclose a new commit/tag and rerun Smoke. Do not silently mutate the frozen formal version.
