"""Borrado robusto de directorios de trabajo.

`shutil.rmtree(..., ignore_errors=True)` no sirve aqui. En Windows los objetos
dentro de `.git` son de solo lectura: el borrado falla a medias **sin avisar**,
y el `git clone` siguiente muere con "destination path already exists and is not
an empty directory". Ademas, si un proceso aun tiene el directorio abierto, es
mejor enterarse que arrastrar un workspace sucio.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import stat
from pathlib import Path


def _forzar_escritura(func, ruta, _exc):
    os.chmod(ruta, stat.S_IWRITE)
    func(ruta)


def wipe_sync(path: Path) -> None:
    """Borra el arbol. Propaga `OSError` si no puede."""
    if not path.exists():
        return
    shutil.rmtree(str(path), onexc=_forzar_escritura)


async def wipe(path: Path, intentos: int = 3) -> None:
    """Como `wipe_sync`, reintentando.

    Un proceso recien matado tarda un instante en soltar los handles; sin el
    reintento, el job siguiente sobre el mismo repo fallaba al limpiar.
    """
    for intento in range(intentos):
        try:
            wipe_sync(path)
            return
        except OSError:
            if intento == intentos - 1:
                raise
            await asyncio.sleep(0.5)
