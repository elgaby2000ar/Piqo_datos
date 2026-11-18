"""Paquete diario de precios: SEPA → archivos estáticos que la app baja de GitHub Pages.

Los precios de SEPA son de solo lectura y cambian una vez por día: no necesitan base de
datos ni servidor. Se arman en streaming (una pasada por el ZIP, sin SQL) y se publican
como JSON. La base (Neon) queda solo para lo de la comunidad, que pesa poco.

Estructura (versión 1), dentro de la carpeta de salida:

    v1/manifiesto.json   fecha, cantidades, fragmentos y la versión del formato
    v1/comercios.json    sucursales: posición = índice que usan los precios
    v1/productos.json    catálogo para buscar: clave, ean, nombre, marca, tipo,
                         contenido, unidad, precio más bajo y sucursales
    v1/leyendas.json     textos de oferta, referenciados por índice
    v1/p/<n>.json        {clave: {"id": uuid, "d": [ean, nombre, marca, tipo, contenido,
                         unidad], "p": [[sucursal, lista, oferta, leyenda], ...]}}

La clave de producto son los primeros 12 dígitos hexadecimales de su UUID: estable día
a día (sirve para links y listas guardadas) y un tercio del largo. Su fragmento es
fragmento_de(clave), así la app y el servidor saben qué archivo pedir sin el catálogo.

Los ids de producto y sucursal son UUID5 deterministas (del EAN o de la clave de SEPA):
el servidor y la app llegan al mismo id sin consultarse, así un reporte de stock de la
comunidad apunta a la misma sucursal todos los días.

Seguridad: el ZIP pasa por los mismos controles que el importador (zip bomb, rutas,
tamaños; OWASP A08) y cada fila por la misma validación. La salida es solo JSON
generado acá: nada del archivo se copia sin validar.
"""

import json
import logging
import uuid
from array import array
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from app.barrios import barrio_caba
from app.categorias import clasificar
from app.normalizacion import normalizar_texto
from app.sepa.cadenas import nombre_cadena
from app.sepa.esquema import (
    COLUMNAS_PRODUCTOS_OBLIGATORIAS,
    FilaInvalida,
    FilaProducto,
    clave_sucursal,
    validar_fila_producto,
)
from app.sepa.lector import ArchivoSepaInvalido, Limites, recorrer_paquetes
from app.sepa.ubicacion import ubicacion_coherente

log = logging.getLogger(__name__)

VERSION = 1
FRAGMENTOS = 512
# Espacio de nombres propio para los UUID5 (no cambiar: los ids quedan guardados).
_ESPACIO = uuid.UUID("6f1d3c52-8e0b-4b8e-9a51-2a7c0b1d9e42")

CAMPOS_COMERCIO = ["id", "cadena", "nombre", "direccion", "barrio", "provincia", "lat", "lon"]
# El UUID completo va solo en el fragmento (lo usa la ficha para hablar con el servidor).
CAMPOS_PRODUCTO = [
    "clave",
    "ean",
    "nombre",
    "marca",
    "categoria",
    "contenido",
    "unidad",
    "minimo",
    "sucursales",
]


def clave_de(producto_id: str) -> str:
    return producto_id.replace("-", "")[:12]


def fragmento_de(clave: str) -> int:
    return int(clave[:6], 16) % FRAGMENTOS


def id_producto(ean: str | None, descripcion: str) -> str:
    clave = f"ean:{ean}" if ean else f"alias:{normalizar_texto(descripcion)}"
    return str(uuid.uuid5(_ESPACIO, clave))


def id_comercio(clave: str) -> str:
    return str(uuid.uuid5(_ESPACIO, f"sepa:{clave}"))


def _centavos(precio: Decimal | None) -> int:
    return 0 if precio is None else int(precio * 100)


def _numero(centavos: int) -> float | int:
    return centavos // 100 if centavos % 100 == 0 else centavos / 100


def _coordenada(valor: str | None, limite: float) -> float | None:
    try:
        numero = float((valor or "").replace(",", "."))
    except ValueError:
        return None
    if numero != numero or abs(numero) > limite or numero == 0:
        return None
    return round(numero, 6)


@dataclass
class _Precios:
    """Columnas compactas: 9 millones de precios entran en ~150 MB de memoria."""

    sucursal: array = field(default_factory=lambda: array("I"))
    lista: array = field(default_factory=lambda: array("q"))
    oferta: array = field(default_factory=lambda: array("q"))
    leyenda: array = field(default_factory=lambda: array("i"))


@dataclass
class Resumen:
    fecha: str
    comercios: int = 0
    productos: int = 0
    precios: int = 0
    filas_leidas: int = 0
    filas_rechazadas: int = 0
    duplicadas: int = 0
    avisos: list[str] = field(default_factory=list)


class Constructor:
    def __init__(self, limites: Limites, provincias: list[str]) -> None:
        self.limites = limites
        self.provincias = {p.upper() for p in provincias}
        self.comercios: list[list] = []
        self._indice_comercio: dict[str, int] = {}
        self.productos: list[list] = []
        self._indice_producto: dict[str, int] = {}
        self.precios: list[_Precios] = []
        self.leyendas: list[str] = []
        self._indice_leyenda: dict[str, int] = {}
        self._vistos: set[int] = set()

    # --- lectura ------------------------------------------------------------------

    def leer(self, archivo: Path | bytes, fecha: date) -> Resumen:
        resumen = Resumen(fecha=fecha.isoformat())
        for paquete in recorrer_paquetes(archivo, self.limites, resumen.avisos):
            encabezado = set(paquete.encabezado_productos())
            faltantes = COLUMNAS_PRODUCTOS_OBLIGATORIAS - encabezado
            if faltantes:
                raise ArchivoSepaInvalido(
                    f"{paquete.origen}: cambió el formato de productos.csv, "
                    f"faltan {sorted(faltantes)}"
                )
            sucursales = self._sucursales(paquete)
            if not sucursales:
                continue  # el comercio no tiene sucursales en la zona: ni se lee productos
            for fila in paquete.filas("productos.csv"):
                resumen.filas_leidas += 1
                try:
                    datos = validar_fila_producto(fila)
                except FilaInvalida:
                    resumen.filas_rechazadas += 1
                    continue
                indice_sucursal = sucursales.get(datos.clave_sucursal)
                if indice_sucursal is None:
                    continue
                self._agregar(datos, indice_sucursal, resumen)
        resumen.comercios = len(self.comercios)
        resumen.productos = len(self.productos)
        resumen.precios = sum(len(p.sucursal) for p in self.precios)
        return resumen

    def _sucursales(self, paquete) -> dict[str, int]:
        banderas = {
            (f.get("id_bandera") or "").strip(): (f.get("comercio_bandera_nombre") or "").strip()
            for f in paquete.filas("comercio.csv")
            if "__error__" not in f
        }
        general = next(iter(banderas.values()), "")
        resultado: dict[str, int] = {}
        for fila in paquete.filas("sucursales.csv"):
            if "__error__" in fila:
                continue
            try:
                clave = clave_sucursal(fila)
            except FilaInvalida:
                continue
            if clave in self._indice_comercio:
                resultado[clave] = self._indice_comercio[clave]
                continue
            declarada = (fila.get("sucursales_provincia") or "").strip().upper()[:10] or None
            ubicacion = ubicacion_coherente(
                declarada,
                _coordenada(fila.get("sucursales_latitud"), 90),
                _coordenada(fila.get("sucursales_longitud"), 180),
                fila.get("sucursales_localidad"),
            )
            if self.provincias and ubicacion.provincia not in self.provincias:
                continue
            bandera = banderas.get((fila.get("id_bandera") or "").strip()) or general
            cadena = nombre_cadena(bandera[:120])
            calle = " ".join(
                p
                for p in (
                    (fila.get("sucursales_calle") or "").strip(),
                    (fila.get("sucursales_numero") or "").strip(),
                )
                if p
            )
            texto_barrio = (fila.get("sucursales_barrio") or "").strip()[:120] or None
            barrio = (
                barrio_caba(ubicacion.latitud, ubicacion.longitud, texto_barrio)
                if ubicacion.provincia == "AR-C"
                else texto_barrio or (fila.get("sucursales_localidad") or "").strip()[:120] or None
            )
            self._indice_comercio[clave] = len(self.comercios)
            self.comercios.append(
                [
                    id_comercio(clave),
                    cadena,
                    ((fila.get("sucursales_nombre") or "").strip() or cadena or clave)[:160],
                    calle[:200] or None,
                    barrio,
                    ubicacion.provincia,
                    ubicacion.latitud,
                    ubicacion.longitud,
                ]
            )
            resultado[clave] = self._indice_comercio[clave]
        return resultado

    def _agregar(self, datos: FilaProducto, sucursal: int, resumen: Resumen) -> None:
        pid = id_producto(datos.ean, datos.descripcion)
        indice = self._indice_producto.get(pid)
        if indice is None:
            indice = len(self.productos)
            self._indice_producto[pid] = indice
            contenido = datos.contenido
            self.productos.append(
                [
                    pid,
                    datos.ean,
                    datos.descripcion,
                    datos.marca,
                    clasificar(datos.descripcion),
                    None if contenido is None else str(contenido.cantidad).removesuffix(".0"),
                    None if contenido is None else contenido.unidad,
                ]
            )
            self.precios.append(_Precios())
        clave = (sucursal << 32) | indice
        if clave in self._vistos:
            resumen.duplicadas += 1
            return
        self._vistos.add(clave)
        p = self.precios[indice]
        p.sucursal.append(sucursal)
        p.lista.append(_centavos(datos.precio_lista))
        p.oferta.append(_centavos(datos.precio_promo))
        if datos.precio_promo is not None and datos.leyenda_promo:
            ley = self._indice_leyenda.get(datos.leyenda_promo)
            if ley is None:
                ley = len(self.leyendas)
                self._indice_leyenda[datos.leyenda_promo] = ley
                self.leyendas.append(datos.leyenda_promo)
            p.leyenda.append(ley)
        else:
            p.leyenda.append(-1)

    # --- escritura ----------------------------------------------------------------

    def escribir(self, salida: Path, resumen: Resumen) -> dict:
        destino = salida / f"v{VERSION}"
        (destino / "p").mkdir(parents=True, exist_ok=True)
        fragmentos: list[dict[str, dict]] = [{} for _ in range(FRAGMENTOS)]
        filas_productos = []
        for producto, p in zip(self.productos, self.precios, strict=True):
            clave = clave_de(producto[0])
            frag = fragmento_de(clave)
            vigentes = [o or li for li, o in zip(p.lista, p.oferta, strict=True)]
            filas_productos.append([clave, *producto[1:], _numero(min(vigentes)), len(vigentes)])
            filas = []
            for s, li, o, ley in zip(p.sucursal, p.lista, p.oferta, p.leyenda, strict=True):
                fila = [s, _numero(li)]
                if o:
                    fila += [_numero(o), ley]
                filas.append(fila)
            filas.sort()
            # "d": los datos del producto, para que el servidor lo dé de alta sin bajar el
            # catálogo entero cuando alguien aporta algo de un producto nuevo.
            fragmentos[frag][clave] = {"id": producto[0], "d": producto[1:], "p": filas}

        def guardar(nombre: str, datos: object) -> None:
            (destino / nombre).write_text(
                json.dumps(datos, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
            )

        guardar("comercios.json", {"campos": CAMPOS_COMERCIO, "filas": self.comercios})
        guardar("productos.json", {"campos": CAMPOS_PRODUCTO, "filas": filas_productos})
        guardar("leyendas.json", self.leyendas)
        for n, frag in enumerate(fragmentos):
            guardar(f"p/{n}.json", frag)
        manifiesto = {
            "version": VERSION,
            "fecha": resumen.fecha,
            "generado": datetime.now(UTC).isoformat(timespec="seconds"),
            "fragmentos": FRAGMENTOS,
            "comercios": resumen.comercios,
            "productos": resumen.productos,
            "precios": resumen.precios,
            "provincias": sorted(self.provincias),
            "fuente": "SEPA (Secretaría de Comercio), datos abiertos",
        }
        # El manifiesto va último: si algo falla antes, no se publica un paquete a medias.
        guardar("manifiesto.json", manifiesto)
        return manifiesto


def construir(
    archivo: Path | bytes, fecha: date, salida: Path, limites: Limites, provincias: list[str]
) -> dict:
    constructor = Constructor(limites, provincias)
    resumen = constructor.leer(archivo, fecha)
    if resumen.precios == 0:
        raise ArchivoSepaInvalido("El ZIP no trajo ningún precio en la zona: no se publica")
    manifiesto = constructor.escribir(salida, resumen)
    log.info("paquete.listo", extra={"resumen": resumen.__dict__})
    return {
        **manifiesto,
        "filas_leidas": resumen.filas_leidas,
        "filas_rechazadas": resumen.filas_rechazadas,
        "duplicadas": resumen.duplicadas,
        "avisos": resumen.avisos[:20],
    }
