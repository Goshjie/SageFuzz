from __future__ import annotations

from typing import Optional

from sagefuzz_seedgen.runtime.program_context import ProgramContext


_CTX: Optional[ProgramContext] = None


def set_program_context(ctx: ProgramContext) -> None:
    global _CTX
    _CTX = ctx


def get_program_context() -> ProgramContext:
    if _CTX is None:
        raise RuntimeError("ProgramContext not initialized. Call initialize_program_context() and set_program_context().")
    return _CTX

