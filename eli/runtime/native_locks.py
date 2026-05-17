from __future__ import annotations

import threading


# llama.cpp is native code and ELI can host more than one Llama context in one
# process: the main GGUF model and the embedding model. Keep all llama.cpp entry
# points behind one process-local lock to avoid cross-context heap corruption.
LLAMA_CPP_NATIVE_LOCK = threading.RLock()

# FAISS index cloning/writing is also native code. Keep disk persistence out of
# concurrent clone/write races while searches/adds use the VectorStore lock.
FAISS_IO_LOCK = threading.RLock()

