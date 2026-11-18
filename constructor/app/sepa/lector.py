"""Lectura segura de los ZIP diarios de SEPA.

El ZIP del día trae, por cada comercio, otro ZIP con tres archivos separados por "|":
comercio.csv, sucursales.csv y productos.csv. El lector:

- recorre ZIPs anidados hasta una profundidad máxima,
- rechaza rutas peligrosas (absolutas, con "..") y enlaces,
- corta zip bombs (tamaño máximo y ratio de compresión máximo),
- lee en streaming (no carga 12 millones de filas en memoria),
- tolera BOM, líneas en blanco y la línea final "Última actualización: …".

Nota: los nombres de columnas están en esquema.py y se validan contra el encabezado
real de cada archivo. Si SEPA cambia el formato, el importador falla de forma
explícita en vez de cargar datos corridos (OWASP A08 y A10).
"""

import csv
import io
import shutil
import tempfile
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import IO

ARCHIVOS_SEPA = ("comercio.csv", "sucursales.csv", "productos.csv")
# comercio.csv y sucursales.csv pesan KB: se leen a memoria. productos.csv puede pesar
# más de 500 MB descomprimido (DIA, Carrefour): se lee siempre en streaming.
ARCHIVOS_EN_MEMORIA = ("comercio.csv", "sucursales.csv")
_MEMORIA_ZIP_INTERNO = 32 << 20  # más que esto, el ZIP interno va a un temporal en disco


class ArchivoSepaInvalido(Exception):
    """El archivo no tiene la forma esperada o es potencialmente malicioso."""


@dataclass
class Limites:
    max_bytes_miembro: int
    max_ratio_compresion: int
    max_profundidad: int
    max_miembros: int


@dataclass
class PaqueteComercio:
    """Los tres CSV de un comercio. productos.csv se abre en streaming al leerlo."""

    origen: str
    archivos: dict[str, bytes] = field(default_factory=dict)
    abrir_productos: Callable[[], IO[bytes]] | None = None

    def filas(self, nombre: str) -> Iterator[dict[str, str]]:
        if nombre == "productos.csv" and self.abrir_productos is not None:
            return _filas_con_cierre(self.abrir_productos, f"{self.origen}/{nombre}")
        contenido = self.archivos.get(nombre)
        if contenido is None:
            return iter(())
        return leer_csv_sepa(contenido, f"{self.origen}/{nombre}")

    def encabezado_productos(self) -> list[str]:
        if self.abrir_productos is None:
            return encabezado_de(self.archivos.get("productos.csv", b""))
        with self.abrir_productos() as flujo:
            return encabezado_de(flujo.read(64 << 10))


def _filas_con_cierre(abrir: Callable[[], IO[bytes]], origen: str) -> Iterator[dict[str, str]]:
    with abrir() as flujo:
        yield from leer_csv_sepa(flujo, origen)


class _FlujoAcotado(io.RawIOBase):
    """Envuelve un miembro del ZIP y corta si el contenido real supera el límite:
    no se confía en el tamaño declarado en el encabezado (zip bomb)."""

    def __init__(self, origen: IO[bytes], limite: int, nombre: str) -> None:
        self._origen = origen
        self._restante = limite
        self._nombre = nombre

    def readable(self) -> bool:
        return True

    def readinto(self, destino: bytearray | memoryview) -> int:  # type: ignore[override]
        datos = self._origen.read(len(destino))
        self._restante -= len(datos)
        if self._restante < 0:
            raise ArchivoSepaInvalido(f"El contenido real excede el límite: {self._nombre!r}")
        destino[: len(datos)] = datos
        return len(datos)

    def close(self) -> None:
        self._origen.close()
        super().close()


def _abrir_acotado(zf: zipfile.ZipFile, info: zipfile.ZipInfo, limite: int) -> IO[bytes]:
    return io.BufferedReader(_FlujoAcotado(zf.open(info), limite, info.filename), 1 << 20)


def _ruta_segura(nombre: str) -> bool:
    if not nombre or "\x00" in nombre or "\\" in nombre:
        return False
    ruta = PurePosixPath(nombre)
    return not ruta.is_absolute() and ".." not in ruta.parts


def _validar_miembro(info: zipfile.ZipInfo, limites: Limites) -> None:
    if not _ruta_segura(info.filename):
        raise ArchivoSepaInvalido(f"Ruta no permitida dentro del ZIP: {info.filename!r}")
    # Bit de enlace simbólico en atributos Unix.
    if (info.external_attr >> 16) & 0o170000 == 0o120000:
        raise ArchivoSepaInvalido(f"Enlace simbólico no permitido: {info.filename!r}")
    if info.file_size > limites.max_bytes_miembro:
        raise ArchivoSepaInvalido(f"Archivo demasiado grande: {info.filename!r}")
    if info.compress_size > 0:
        ratio = info.file_size / info.compress_size
        if ratio > limites.max_ratio_compresion:
            raise ArchivoSepaInvalido(f"Ratio de compresión sospechoso: {info.filename!r}")
    elif info.file_size > 0:
        raise ArchivoSepaInvalido(f"Tamaño comprimido inválido: {info.filename!r}")


def recorrer_paquetes(
    datos_zip: bytes | Path | IO[bytes],
    limites: Limites,
    avisos: list[str] | None = None,
) -> Iterator[PaqueteComercio]:
    """Devuelve un PaqueteComercio por cada carpeta o ZIP interno que tenga CSV de SEPA.

    Cada paquete es válido hasta pedir el siguiente (productos.csv se lee del ZIP abierto).
    Un ZIP interno vacío o roto se saltea y se anota en `avisos`: SEPA publica a veces
    el archivo de una cadena en cero bytes, y eso no debe frenar el resto. Un ZIP externo
    roto o cualquier señal de ataque (rutas, enlaces, bombas) sí corta todo.
    """
    contador = {"miembros": 0}
    avisos = avisos if avisos is not None else []
    if isinstance(datos_zip, Path):
        with datos_zip.open("rb") as archivo:
            yield from _recorrer(archivo, "", 1, limites, contador, avisos)
    else:
        yield from _recorrer(datos_zip, "", 1, limites, contador, avisos)


def _recorrer(
    datos_zip: bytes | IO[bytes],
    origen: str,
    profundidad: int,
    limites: Limites,
    contador: dict[str, int],
    avisos: list[str],
) -> Iterator[PaqueteComercio]:
    fuente = io.BytesIO(datos_zip) if isinstance(datos_zip, bytes) else datos_zip
    try:
        zf = zipfile.ZipFile(fuente)
    except zipfile.BadZipFile as error:
        if profundidad > 1:
            avisos.append(f"ZIP interno vacío o corrupto, se omite: {origen}")
            return
        raise ArchivoSepaInvalido(f"ZIP corrupto en {origen or 'raíz'}") from error

    with zf:
        internos: list[zipfile.ZipInfo] = []
        csv_por_carpeta: dict[str, dict[str, zipfile.ZipInfo]] = {}
        for info in zf.infolist():
            if info.is_dir():
                continue
            contador["miembros"] += 1
            if contador["miembros"] > limites.max_miembros:
                raise ArchivoSepaInvalido("Demasiados archivos dentro del ZIP")
            _validar_miembro(info, limites)
            ruta = PurePosixPath(info.filename)
            nombre = ruta.name.lower()
            if nombre.endswith(".zip"):
                if profundidad >= limites.max_profundidad:
                    raise ArchivoSepaInvalido("Demasiados niveles de ZIP anidados")
                internos.append(info)
            elif nombre in ARCHIVOS_SEPA:
                carpeta = f"{origen}/{ruta.parent}".strip("/.") or "raiz"
                csv_por_carpeta.setdefault(carpeta, {})[nombre] = info
            # Cualquier otro archivo se ignora.

        for carpeta, miembros in csv_por_carpeta.items():
            if "productos.csv" not in miembros:
                continue
            paquete = PaqueteComercio(origen=carpeta)
            for nombre in ARCHIVOS_EN_MEMORIA:
                if nombre in miembros:
                    with _abrir_acotado(zf, miembros[nombre], limites.max_bytes_miembro) as f:
                        paquete.archivos[nombre] = f.read()
            info_productos = miembros["productos.csv"]
            paquete.abrir_productos = (
                lambda i=info_productos: _abrir_acotado(zf, i, limites.max_bytes_miembro)
            )
            yield paquete

        for info in internos:
            ruta_interna = f"{origen}/{info.filename}".strip("/")
            if info.file_size == 0:
                avisos.append(f"ZIP interno vacío, se omite: {ruta_interna}")
                continue
            with tempfile.SpooledTemporaryFile(max_size=_MEMORIA_ZIP_INTERNO) as temporal:
                with _abrir_acotado(zf, info, limites.max_bytes_miembro) as flujo:
                    shutil.copyfileobj(flujo, temporal, 1 << 20)
                temporal.seek(0)
                yield from _recorrer(
                    temporal, ruta_interna, profundidad + 1, limites, contador, avisos
                )


_MAX_RENGLONES_POR_FILA = 3


def leer_csv_sepa(contenido: bytes | IO[bytes], origen: str) -> Iterator[dict[str, str]]:
    """Filas del CSV como diccionarios.

    Repara las filas partidas: en el archivo real de Coto (16/11/2026) algunas
    descripciones traen un salto de línea adentro y la fila llega en dos renglones
    ("12|1|108|7792180145963|1|" y "PREMEZCLA … |400|grm|…"). Si renglones cortos
    consecutivos suman exactamente las columnas del encabezado, se unen con un espacio.
    Si no cierran, cada renglón cuenta como error y no se inventa nada."""
    binario = io.BytesIO(contenido) if isinstance(contenido, bytes) else contenido
    texto = io.TextIOWrapper(binario, encoding="utf-8-sig", errors="replace", newline="")
    lector = csv.reader(texto, delimiter="|", quoting=csv.QUOTE_NONE)
    encabezado: list[str] | None = None
    partida: list[str] | None = None
    renglones_partida: list[int] = []

    def descartar_partida() -> Iterator[dict[str, str]]:
        for renglon in renglones_partida:
            yield {"__error__": f"{origen}:{renglon}: cantidad de columnas incorrecta"}

    for numero, fila in enumerate(lector, start=1):
        if not fila or all(not c.strip() for c in fila):
            continue
        if encabezado is None:
            encabezado = [c.strip().lower() for c in fila]
            continue
        if len(fila) == 1 and "actualiz" in fila[0].lower():
            continue  # línea final informativa ("Ultima actualización: …")
        columnas = len(encabezado)

        if partida is not None:
            unida = [*partida[:-1], f"{partida[-1]} {fila[0]}".strip(), *fila[1:]]
            if len(unida) == columnas:
                partida, renglones_partida = None, []
                yield {k: v.strip() for k, v in zip(encabezado, unida, strict=True)}
                continue
            if len(unida) < columnas and len(renglones_partida) < _MAX_RENGLONES_POR_FILA:
                partida = unida
                renglones_partida.append(numero)
                continue
            yield from descartar_partida()
            partida, renglones_partida = None, []

        if len(fila) == columnas:
            yield {k: v.strip() for k, v in zip(encabezado, fila, strict=True)}
        elif len(fila) < columnas:
            partida, renglones_partida = fila, [numero]
        else:
            yield {"__error__": f"{origen}:{numero}: cantidad de columnas incorrecta"}
    if partida is not None:
        yield from descartar_partida()
    texto.detach()


def encabezado_de(contenido: bytes) -> list[str]:
    texto = contenido.decode("utf-8-sig", errors="replace")
    primera = next((linea for linea in texto.splitlines() if linea.strip()), "")
    return [c.strip().lower() for c in primera.split("|")]
