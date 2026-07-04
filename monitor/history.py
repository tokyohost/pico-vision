"""Maintain fixed-length metric histories on a wall-clock-independent second grid."""

import time


def update_per_second(history, value, state, now=None):
    """Update one history point per monotonic second and fill skipped seconds."""
    second = int(time.monotonic() if now is None else now)
    previous_second = state.get("second")
    previous_value = state.get("value", value)

    if previous_second is None:
        history.append(value)
    elif second <= previous_second:
        value = max(previous_value, value)
        if history:
            history[-1] = value
        else:
            history.append(value)
    else:
        elapsed = min(second - previous_second, history.maxlen or second - previous_second)
        for _ in range(max(0, elapsed - 1)):
            history.append(previous_value)
        history.append(value)

    state["second"] = max(second, previous_second if previous_second is not None else second)
    state["value"] = value
