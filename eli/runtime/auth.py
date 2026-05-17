# eli/runtime/auth.py
# AuthManager was an incomplete multi-user auth skeleton (login() was `pass`,
# missing import time, and ELI is a single-user assistant).
# Removed. Authority and security are handled by:
#   eli/runtime/authority_gate.py  — action allow/check gate
#   eli/runtime/security.py        — SecurityManager (path/command sandboxing)
#   eli/runtime/identity_guard.py  — persona lock
