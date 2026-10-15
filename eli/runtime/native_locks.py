from __future__ import annotations

import threading
from contextlib import contextmanager


# llama.cpp is native code and ELI can host more than one Llama context in one
# process: the main GGUF model and the embedding model. Keep all llama.cpp entry
# points behind one process-local lock to avoid cross-context heap corruption.
LLAMA_CPP_NATIVE_LOCK = threading.RLock()

# Set while the user's turn waits for LLAMA_CPP_NATIVE_LOCK. A background generation holding the lock
# (news synthesis, insights, the morning report) checks it at every token and during prompt
# evaluation and yields (eli.cognition.gguf_inference), so the user's message never queues behind a chore.
FOREGROUND_WAITING = threading.Event()


@contextmanager
def hold_llama_lock(*, foreground: bool):
    """LLAMA_CPP_NATIVE_LOCK for one native call. Foreground work (the user's turn) announces itself
    while it waits, so a background generation holding the lock yields. Until 2.5.17 only
    generations did: embedding a typed "close settings" into memory waited 92 s behind a news
    synthesis."""
    if foreground:
        FOREGROUND_WAITING.set()
    try:
        LLAMA_CPP_NATIVE_LOCK.acquire()
    finally:
        if foreground:
            FOREGROUND_WAITING.clear()
    try:
        yield
    finally:
        LLAMA_CPP_NATIVE_LOCK.release()

# FAISS index cloning/writing is also native code. Keep disk persistence out of
# concurrent clone/write races while searches/adds use the VectorStore lock.
FAISS_IO_LOCK = threading.RLock()

