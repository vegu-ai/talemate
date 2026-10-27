from typing import Literal, get_args

EffortLevel = Literal[
    "default", "none", "minimal", "low", "medium", "high", "xhigh", "max"
]
EFFORT_LEVELS = list(get_args(EffortLevel))
