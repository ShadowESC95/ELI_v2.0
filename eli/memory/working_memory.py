# Re-export from canonical location.
# The engine imports WorkingMemory from eli.cognition.working_memory.
# This shim ensures any direct import of eli.memory.working_memory still works.
from eli.cognition.working_memory import WorkingMemory, MAX_PINS, MAX_AGE_TURNS, IMPORTANCE_THRESHOLD

__all__ = ["WorkingMemory", "MAX_PINS", "MAX_AGE_TURNS", "IMPORTANCE_THRESHOLD"]
