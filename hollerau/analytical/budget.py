"""One monotonic budget shared by preparation, proposer, final choice and execution."""

import time
from dataclasses import dataclass

# Arena allows 60 seconds from receipt. Leave five seconds outside this controller
# for validation/dispatch and network overhead; attachments consume this budget too.
TURN_SECONDS = 55.0
PROPOSER_SECONDS = 20.0
FINAL_RESERVE_SECONDS = 24.0
BOARD_RESERVE_SECONDS = 3.0
EXECUTION_RESERVE_SECONDS = 2.0
MIN_PROPOSER_SECONDS = 8.0


@dataclass(frozen=True)
class TurnBudget:
    deadline: float

    def proposer_deadline(self):
        now = time.monotonic()
        return min(now + PROPOSER_SECONDS,
                   self.deadline - FINAL_RESERVE_SECONDS - BOARD_RESERVE_SECONDS - EXECUTION_RESERVE_SECONDS)

    def can_propose(self):
        return self.proposer_deadline() - time.monotonic() >= MIN_PROPOSER_SECONDS

    def final_deadline(self):
        return self.deadline - EXECUTION_RESERVE_SECONDS

    def snapshot(self):
        now = time.monotonic()
        return {"remaining_seconds": round(max(0.0, self.deadline - now), 3),
                "proposer_available_seconds": round(max(0.0, self.proposer_deadline() - now), 3),
                "final_reserve_seconds": FINAL_RESERVE_SECONDS,
                "board_reserve_seconds": BOARD_RESERVE_SECONDS,
                "execution_reserve_seconds": EXECUTION_RESERVE_SECONDS}
