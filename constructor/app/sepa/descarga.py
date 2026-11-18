"""Descarga del ZIP diario de SEPA.

Controles:
- Solo https y solo hosts de la lista permitida (anti-SSRF, OWASP A01).
- Las redirecciones se siguen a mano y se vuelven a validar.
- Tamaño máximo y timeout: un servidor lento o un archivo gigante no tumba al worker
  (OWASP A10).
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

URL_RECURSOS = "https://datos.produccion.gob.ar/api/3/action/package_show?id=sepa-precios"
MAX_BYTES = 1_000_000_000  # el archivo real ronda los 320 MB
MAX_REDIRECCIONES = 3


class DescargaNoPermitida(Exception):
    pass


def validar_url(url: str, hosts_permitidos: list[str]) -> str:
    partes = urlparse(url)
    if partes.scheme != "https":
        raise DescargaNoPermitida("Solo se permite https")
    if partes.username or partes.password:
        raise DescargaNoPermitida("La URL no puede tener credenciales")
    host = (partes.hostname or "").lower().rstrip(".")
    if host not in {h.lower() for h in hosts_permitidos}:
        raise DescargaNoPermitida(f"Host no permitido: {host!r}")
    if partes.port not in (None, 443):
        raise DescargaNoPermitida("Puerto no permitido")
    return url


@dataclass
class ArchivoDescargado:
    ruta: Path
    sha256: str
    bytes: int


def descargar(
    url: str,
    destino: Path,
    hosts_permitidos: list[str],
    cliente: httpx.Client | None = None,
    max_bytes: int = MAX_BYTES,
) -> ArchivoDescargado:
    propio = cliente is None
    cliente = cliente or httpx.Client(timeout=httpx.Timeout(30.0, read=120.0))
    try:
        actual = validar_url(url, hosts_permitidos)
        for _ in range(MAX_REDIRECCIONES + 1):
            with cliente.stream("GET", actual, follow_redirects=False) as respuesta:
                if respuesta.is_redirect:
                    siguiente = respuesta.headers.get("location", "")
                    actual = validar_url(str(respuesta.url.join(siguiente)), hosts_permitidos)
                    continue
                respuesta.raise_for_status()
                return _guardar(respuesta, destino, max_bytes)
        raise DescargaNoPermitida("Demasiadas redirecciones")
    finally:
        if propio:
            cliente.close()


def _guardar(respuesta: httpx.Response, destino: Path, max_bytes: int) -> ArchivoDescargado:
    declarado = int(respuesta.headers.get("content-length") or 0)
    if declarado > max_bytes:
        raise DescargaNoPermitida("El archivo declarado excede el máximo")
    hash_ = hashlib.sha256()
    total = 0
    temporal = destino.with_suffix(destino.suffix + ".parcial")
    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        with temporal.open("wb") as salida:
            for bloque in respuesta.iter_bytes(1 << 20):
                total += len(bloque)
                if total > max_bytes:
                    raise DescargaNoPermitida("El archivo excede el máximo")
                hash_.update(bloque)
                salida.write(bloque)
        temporal.replace(destino)
    except BaseException:
        temporal.unlink(missing_ok=True)
        raise
    return ArchivoDescargado(destino, hash_.hexdigest(), total)
