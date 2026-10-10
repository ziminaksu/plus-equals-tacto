# Two-case Astra evaluation and controller repair

Exactly one hosted session each was run for P02 and P18 using source commit `72f9d1e6d0e75f69da3a09512973a86e78767003`, policy `bayes-v5-astra`. Both negotiator and independent reviewer used Astra. No replacement sessions were started.

| Case | Previous score | v5 score | Outcome |
|---|---:|---:|---|
| P02 | 0.156989 | 0.156989 | Accepted the same EUR 368.45 unindexed deal |
| P18 | 0.339633 | 0.000000 | Server recorded a buyer timeout, followed by supplier withdrawal |

These results do not show an improvement from replacing the model. P18's zero cannot be attributed solely to negotiation strategy. The complete compact audit is in [the JSON report](v5-results-and-repair.json).

## Why P02 repeated the old decision

The reviewer identified an opportunity to obtain a rebased indexed quote. The controller could only act on complete priced proposals; its review schema had no quote-request action. Advice in an issue explanation did not change the decision. Meanwhile, uncertain supplier-response forecasts gave indexed proposals a much worse ranking than their direct costs suggested. The model had not learned the missing base-price relationship.

For example, the EUR 355 / 14-day unindexed proposal had estimated direct cost EUR 2,233,779 and objective EUR 2,283,522. An Astra proposal at EUR 350 / 30 days with a copper index had direct cost EUR 2,234,503 and objective EUR 2,304,872. The EUR 724 direct-cost difference became an approximately EUR 21,351 objective disadvantage. These are Python estimates, not observed supplier acceptance probabilities or official final costs.

The supplier subsequently said the base price would be recalculated to exclude copper increases. Python still countered without indexation. That was a missing information-gathering action, not evidence that the indexed deal was worse.

## Repair: bayes-v5.1-quote-discovery

- Both Astra roles can propose a source-backed quote request without fabricating a price. A conservative fallback recognises explicit supplier language from the saved P02 replies. This request bypasses price forecasts because its purpose is to obtain the missing price. It does not accept indexation or turn an optional clause into a mandatory condition.
- The request is limited to once per supplier and requires enough moves to compare and close. Final offers and already-priced alternatives block it. A question's response does not train the offer-rejection model.
- Supplier-priced indicative alternatives are compared using their quoted terms and estimated total cost. A cheaper valid alternative gets a request for standing-offer confirmation; an indicative ID cannot be accepted. This is still an estimate, not a guaranteed saving.
- The shared budget starts before attachments and is reduced from 52 to 35 seconds. Calls and attachments have smaller phase timeouts; ranking checks elapsed time; exhausted time closes safely. The redundant pre-accept server read is removed. Astra uses low reasoning to reduce latency.

## Verification and limits

41 focused tests pass across routing and saved P02/P18 states. They check quote discovery on both the openness and rebasing replies, reviewer-originated requests, no repeated question, rejection of unsupported evidence, closing-round guards, exact indicative quote confirmation, and timeout fallback. Model and Arena transport are mocked where needed; these tests spend no practice quota.

No additional hosted sessions were run after this repair. There is no new score, no demonstrated 0.9 result, and no counterfactual assumption that a supplier would have accepted a different offer. Source fixtures contain only public case data and supplier messages; post-session score/oracle data is confined to evaluation reports, never policy inputs. Actual alternative quotes still need confirmation, a question consumes a move, and arbitrary network stalls can still defeat timing margins.
