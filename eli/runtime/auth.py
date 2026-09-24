# AuthManager was an unfinished multi-user auth skeleton (login() was `pass`) and ELI is
# single-user, so it's gone. Authority and security live in authority_gate.py (action gate),
# security.py (SecurityManager: path/command sandboxing) and kernel/engine.py
# (verify_persona_lock / repair_persona_lock).
