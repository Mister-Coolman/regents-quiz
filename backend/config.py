"""Switches read from the environment at start-up.

Both ELA switches are meant to be flipped with `fly secrets set`, which
restarts the machine: no rebuild, and the change is live within a minute or
two. Tests patch these attributes directly.
"""
import os


def _flag(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _ids(name):
    out = set()
    for part in (os.getenv(name) or "").replace(" ", ",").split(","):
        if part.strip().isdigit():
            out.add(int(part))
    return frozenset(out)


# Off until launch. While off, no ELA question or passage is served by any
# route, including history and answer checks for sets served earlier.
ELA_ENABLED = _flag("ELA_ENABLED")

# Stimulus ids to stop serving at once, e.g. after a takedown request:
#   fly secrets set WITHDRAWN_STIMULI=12,13
# Joined with stimuli.rights_status = 'withdrawn', which is the durable record
# (set it in the database before the next release).
WITHDRAWN_STIMULI = _ids("WITHDRAWN_STIMULI")
