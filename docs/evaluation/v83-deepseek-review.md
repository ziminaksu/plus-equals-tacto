# External DeepSeek review of the v8.3 controller

The user requested a non-OpenAI code correction and explicitly approved sending
the selected eleven code files and P02/P18 traces to DeepSeek V4 Pro through
Hugging Face and DeepInfra. The prepared packet excluded credentials and hidden
benchmark values. A focused request used a subset of that same approved material.

The successful response identified itself as
`deepseek-ai/DeepSeek-V4-Pro-0813`. It returned eight proposed exact source
replacements. These were reconstructed in an ignored candidate directory and
parsed as Python source without importing or executing the project. They were
**not applied to the runtime** because code review found correctness problems.

## Grounded findings

- The final director receives very large boards: about 34k–75k input tokens in
  the latest pair, with many cost cards, variants and historical details.
- The proposer precedes the final director. All three P18 proposer calls timed
  out around 11.2 seconds, consuming part of the shared decision budget without
  providing fresh proposals.
- A more compact representation of negotiating trajectories is a useful design
  direction. Counteroffers' potential later benefits are not explicitly valued
  by the present one-step numerical continuation estimate.

These are supported concerns, not proof that the proposed replacement or a
particular opening price would improve the Arena score.

## Why the returned patch was rejected

1. **Closing actions become invalid.** Its schema requires a non-null
   `continuation_review` whenever any continuing action is available, but its
   validator rejects that field on an accept/walk-away choice. On closing-only
   boards the schema omits the field, while the unchanged exact-key shape check
   still requires it. The proposal therefore breaks final authorization.
2. **The claimed arithmetic correction changes nothing.** With no secured
   improvement, the existing loss term is zero. For valid nonnegative acceptance
   probabilities, the proposed special case computes exactly the same acceptance
   probability times gain. DeepSeek's claim that the existing expression is
   necessarily negative at opening is false.
3. **It discards useful choices arbitrarily.** Keeping the first episode per stage
   and the first two allowed term options is not a measure of relevance or quality.
   It could remove the opening alternatives the last memory change restored.
   Its claimed six-package limit is not actually enforced: history and other seeds
   are added before the conditional that skips some generated variants.
4. **Its timing rewrite does not match its explanation.** It still makes a serial
   proposer call based on remaining seconds, not the claimed board-size/standing-
   offer criteria, and can build the board twice. A broad exception handler hides
   unexpected failures. It does not establish a reliable end-to-end deadline.
5. **Some diagnosis overlooks existing safeguards.** The current board already
   labels historical stage, executable standing offers and hypothetical packages.
   Presentation may still be ineffective; claiming the distinction is absent
   would be inaccurate.

## Provenance and status

The full non-streaming attempt returned HTTP 504. A streamed high-reasoning
attempt exhausted its output budget before producing answer text. A focused
attempt timed out. The final focused direct-output request completed in 128.78
seconds, with 35,497 prompt tokens and 9,709 completion tokens reported by the
provider. There were no additional requests after this successful response.

Full prepared-request SHA-256:
`ed86075ec05587dbcdae43dcdaf386b349c09482faefafd51f0019466d0b3f5a`.

Successful response SHA-256, as recorded by the review client:
`5ba0ab9d7d7de846a49a746548428e9db28a386c31c5365f8e2d6945fef8ad95`.

Raw packets, response and reconstructed patch remain in the ignored local review
directory. No local unit tests, simulations or model replays ran. No additional
Arena sessions were started for this review. The running policy remains
`astra-v83-action-response-memory`, and no score improvement is claimed.

See [the current architecture](../CURRENT_ARCHITECTURE.md) for the implemented
flow and the proposed direction, and [the two Arena results](v83-arena-results.md)
for measured behaviour.
