"""Columnas de SEPA y validación de cada fila.

Los nombres de columnas siguen el formato publicado por SEPA (Anexo II de la
Res. 678/2020). IMPORTANTE: verificar contra un archivo real antes del primer
import productivo; el importador compara estos nombres con el encabezado y falla
si faltan columnas obligatorias.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.normalizacion import (
    Contenido,
    contenido_de_fila_sepa,
    es_ean_valido,
    es_numero_ascii,
    limpiar_descripcion,
)

COLUMNAS_PRODUCTOS_OBLIGATORIAS = {
    "id_comercio",
    "id_bandera",
    "id_sucursal",
    "id_producto",
    "productos_descripcion",
    "productos_precio_lista",
}

COLUMNAS_SUCURSALES_OBLIGATORIAS = {"id_comercio", "id_bandera", "id_sucursal"}

# Valores que las cadenas ponen en productos_marca cuando no informan marca.
MARCAS_VACIAS = {
    "", ".", "-", "--", "s/d", "sd", "s/m", "sin marca", "sin datos", "n/a", "na", "generico",
    "generica",
}

PRECIO_MAXIMO = Decimal("100000000")  # 100 millones: cualquier cosa arriba es un error


@dataclass(frozen=True)
class FilaProducto:
    clave_sucursal: str
    id_producto: str
    ean: str | None
    descripcion: str
    marca: str | None
    contenido: Contenido | None
    precio_lista: Decimal
    precio_promo: Decimal | None
    leyenda_promo: str | None


class FilaInvalida(ValueError):
    pass


def _precio(valor: str | None, obligatorio: bool) -> Decimal | None:
    if valor is None or valor.strip() == "":
        if obligatorio:
            raise FilaInvalida("precio vacío")
        return None
    texto = valor.strip()
    # Formato con coma decimal y punto de miles: "1.234,50"
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        precio = Decimal(texto)
    except InvalidOperation as error:
        raise FilaInvalida(f"precio inválido: {valor[:20]!r}") from error
    if not precio.is_finite() or precio <= 0 or precio > PRECIO_MAXIMO:
        if obligatorio:
            raise FilaInvalida(f"precio fuera de rango: {valor[:20]!r}")
        return None
    return precio.quantize(Decimal("0.01"))


def _ean_de(id_producto: str, columna_ean: str) -> str | None:
    """SEPA puede informar `productos_ean` como indicador (1/0) o como el código mismo.
    Se prueban los candidatos y se devuelve el primero con dígito verificador válido,
    normalizado a 13 dígitos cuando corresponde."""
    columna_ean = (columna_ean or "").strip()
    if columna_ean == "0":
        return None
    candidatos = [id_producto]
    if len(columna_ean) > 1:
        candidatos.insert(0, columna_ean)
    for candidato in candidatos:
        if not es_numero_ascii(candidato):
            continue
        if len(candidato) <= 13 and es_ean_valido(candidato.zfill(13)):
            return candidato.zfill(13)
        if es_ean_valido(candidato):
            return candidato
    return None


def clave_sucursal(fila: dict[str, str]) -> str:
    partes = [fila.get("id_comercio", ""), fila.get("id_bandera", ""), fila.get("id_sucursal", "")]
    if not all(p.strip() for p in partes):
        raise FilaInvalida("faltan identificadores de sucursal")
    return "-".join(p.strip()[:20] for p in partes)


def validar_fila_producto(fila: dict[str, str]) -> FilaProducto:
    if "__error__" in fila:
        raise FilaInvalida(fila["__error__"])
    faltantes = COLUMNAS_PRODUCTOS_OBLIGATORIAS - fila.keys()
    if faltantes:
        raise FilaInvalida(f"faltan columnas: {sorted(faltantes)}")

    descripcion = limpiar_descripcion(fila["productos_descripcion"])[:200]
    if not descripcion:
        raise FilaInvalida("descripción vacía")

    id_producto = fila["id_producto"].strip()[:40]
    if not id_producto:
        raise FilaInvalida("id de producto vacío")
    ean = _ean_de(id_producto, fila.get("productos_ean", ""))

    precio_lista = _precio(fila["productos_precio_lista"], obligatorio=True)
    assert precio_lista is not None
    precio_promo = _precio(fila.get("productos_precio_unitario_promo1"), obligatorio=False)
    if precio_promo is not None and precio_promo >= precio_lista:
        precio_promo = None  # una "promo" que no baja el precio no es promo

    leyenda = (fila.get("productos_leyenda_promo1") or "").strip()[:200] or None
    marca = (fila.get("productos_marca") or "").strip()[:120]
    if marca.lower() in MARCAS_VACIAS:
        marca = ""

    return FilaProducto(
        clave_sucursal=clave_sucursal(fila),
        id_producto=id_producto,
        ean=ean,
        descripcion=descripcion,
        marca=marca or None,
        contenido=contenido_de_fila_sepa(
            fila.get("productos_cantidad_presentacion", ""),
            fila.get("productos_unidad_medida_presentacion", ""),
            fila.get("productos_cantidad_referencia", ""),
            fila.get("productos_unidad_medida_referencia", ""),
            descripcion,
        ),
        precio_lista=precio_lista,
        precio_promo=precio_promo,
        leyenda_promo=leyenda if precio_promo is not None else None,
    )
