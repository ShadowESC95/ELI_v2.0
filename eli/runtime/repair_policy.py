"""Policy separating proposal layers from source-mutation layers."""
from eli.core.architecture_contracts import (
    PROPOSAL_ONLY_MODULE_PREFIXES,
    REPAIR_OWNER_MODULE,
    SOURCE_MUTATION_OWNER_MODULES,
)


def is_source_mutation_allowed(module_name: str) -> bool:
    return module_name in SOURCE_MUTATION_OWNER_MODULES


def is_proposal_only(module_name: str) -> bool:
    return any(module_name.startswith(prefix) for prefix in PROPOSAL_ONLY_MODULE_PREFIXES)


__all__ = [
    'REPAIR_OWNER_MODULE',
    'SOURCE_MUTATION_OWNER_MODULES',
    'PROPOSAL_ONLY_MODULE_PREFIXES',
    'is_source_mutation_allowed',
    'is_proposal_only',
]
