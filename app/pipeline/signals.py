"""Should the extractor learn timers and sub-processes? Let the meetings decide.

Counts how many uploaded meetings describe waiting periods / deadlines (BPMN timer events) and
separate sub-processes, with example lines. Rules only, no AI. Decision rule (README): add an
element once real meetings mention it often enough to matter (≥ 20% of at least 10 meetings).
"""

import re
from dataclasses import dataclass, field

_N = r"(\d+|a|an|one|two|three|four|five|six|seven|ten|fourteen|thirty|a couple of|a few)"
_UNIT = r"(minute|hour|day|business day|working day|week|month)s?"
TIMER = re.compile(
    rf"\b(wait(s|ing)?|after|within|every|takes?|up to|at least|no later than)\b[^.?!]{{0,40}}\b{_N}\s+{_UNIT}\b"
    rf"|\b(every|each)\s+(day|morning|week|month|monday|tuesday|wednesday|thursday|friday)\b"
    rf"|\b(deadline|overdue|reminder|escalat\w*|sla|chase|cut-?off)\b"
    rf"|\bby (the )?end of (the )?(day|week|month)\b",
    re.I,
)
SUBPROCESS = re.compile(
    r"\b(sub-?process|separate process|its own process|own workflow|another process|a whole (other )?process"
    r"|different process|handled (by|in) (a |the )?(separate|other|another)|that'?s (a )?(whole )?separate)\b",
    re.I,
)


@dataclass
class Evidence:
    meetings: int = 0
    with_timers: int = 0
    with_subprocesses: int = 0
    timer_examples: list[str] = field(default_factory=list)
    subprocess_examples: list[str] = field(default_factory=list)

    def add(self, lines: list[str], keep: int = 5) -> None:
        self.meetings += 1
        timers = [x for x in lines if TIMER.search(x)]
        subs = [x for x in lines if SUBPROCESS.search(x)]
        self.with_timers += bool(timers)
        self.with_subprocesses += bool(subs)
        self.timer_examples = (self.timer_examples + timers[:1])[:keep]
        self.subprocess_examples = (self.subprocess_examples + subs[:1])[:keep]
