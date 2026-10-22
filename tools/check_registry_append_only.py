#!/usr/bin/env python3
"""Verifica che experiments/registry.jsonl sia solo aggiunto in coda, mai modificato (R3.2).

Uso (dal pre-commit): confronta la versione in HEAD con quella nell'index. Solo stdlib, così l'hook
gira anche senza il venv del progetto.

    python3 tools/check_registry_append_only.py            # HEAD contro index
    python3 tools/check_registry_append_only.py OLD NEW    # due file qualsiasi
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REGISTRY = "experiments/registry.jsonl"


def is_append_only(old: str, new: str) -> bool:
    """True se `new` è `old` con zero o più righe aggiunte in coda."""
    if not old:
        return True
    if not old.endswith("\n"):
        # L'ultima riga vecchia senza a capo non si può estendere senza modificarla.
        return new == old
    return new.startswith(old)


def _git_show(spec: str) -> str | None:
    result = subprocess.run(["git", "show", spec], capture_output=True, text=True, check=False)
    return result.stdout if result.returncode == 0 else None


def main(argv: list[str]) -> int:
    if len(argv) == 2:
        old, new = (Path(p).read_text(encoding="utf-8") for p in argv)
    elif not argv:
        old = _git_show(f"HEAD:{REGISTRY}") or ""
        staged = _git_show(f":{REGISTRY}")
        if staged is None:
            if old:
                print(f"ERRORE: {REGISTRY} rimosso dall'index: il registro non si cancella.", file=sys.stderr)
                return 1
            return 0
        new = staged
    else:
        print(__doc__, file=sys.stderr)
        return 2

    if not is_append_only(old, new):
        print(
            f"ERRORE: {REGISTRY} è append-only: le righe esistenti non si modificano né si cancellano.\n"
            "Per correggere un evento aggiungere una nuova riga che lo rettifica.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
