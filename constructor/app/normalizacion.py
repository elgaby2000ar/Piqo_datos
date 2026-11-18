"""Normalización de nombres de producto y extracción de contenido.

Es el primer paso del matching: "LECHE ENT. LA SERENISIMA 1LT" y
"Leche Entera La Serenísima x 1 l" tienen que terminar pareciéndose.
"""

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import NamedTuple

_ABREVIATURAS = {
    "ent": "entera",
    "desc": "descremada",
    "lch": "leche",
    "gral": "general",
    "bot": "botella",
    "paq": "paquete",
    "sach": "sachet",
    "x": "",
}

# Unidades que se ven en SEPA y en tickets → (unidad canónica, factor).
_UNIDADES: dict[str, tuple[str, Decimal]] = {
    "kg": ("g", Decimal(1000)),
    "kgs": ("g", Decimal(1000)),
    "kilo": ("g", Decimal(1000)),
    "kilos": ("g", Decimal(1000)),
    "g": ("g", Decimal(1)),
    "gr": ("g", Decimal(1)),
    "grs": ("g", Decimal(1)),
    "gramos": ("g", Decimal(1)),
    "l": ("ml", Decimal(1000)),
    "lt": ("ml", Decimal(1000)),
    "lts": ("ml", Decimal(1000)),
    "litro": ("ml", Decimal(1000)),
    "litros": ("ml", Decimal(1000)),
    "ml": ("ml", Decimal(1)),
    "cc": ("ml", Decimal(1)),
    "cm3": ("ml", Decimal(1)),
    "un": ("u", Decimal(1)),
    "u": ("u", Decimal(1)),
    "uni": ("u", Decimal(1)),
    "unid": ("u", Decimal(1)),
    "unidades": ("u", Decimal(1)),
}

# Códigos que aparecen solo en las columnas de unidad de SEPA (relevados del archivo
# real del 16/11/2026): códigos UN/ECE (GRM, KGM, LTR, MLT, CMQ) y abreviaturas.
# No se suman al patrón de descripciones porque "ea" o "pc" darían falsos positivos.
_UNIDADES_SEPA: dict[str, tuple[str, Decimal]] = {
    **_UNIDADES,
    "grm": ("g", Decimal(1)),
    "kgm": ("g", Decimal(1000)),
    "kgr": ("g", Decimal(1000)),
    "ltr": ("ml", Decimal(1000)),
    "mlt": ("ml", Decimal(1)),
    "cmq": ("ml", Decimal(1)),
    "unidad": ("u", Decimal(1)),
    "ud": ("u", Decimal(1)),
    "ea": ("u", Decimal(1)),
    "cu": ("u", Decimal(1)),
    "pc": ("u", Decimal(1)),
    "pck": ("u", Decimal(1)),
}

_ALTERNATIVAS_UNIDAD = "|".join(sorted(_UNIDADES, key=len, reverse=True))
_PATRON_CONTENIDO = re.compile(
    r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s*(" + _ALTERNATIVAS_UNIDAD + r")\b"
)

# "24 x 200 ml" o "3 x 80 gr": un pack de N unidades iguales.
_PATRON_PACK = re.compile(r"(?<![\w.,])(\d{1,3})\s*x\s*$")
_LARGO_MAXIMO = 200


def _sin_exponente(valor: Decimal) -> Decimal:
    """1000 en vez de 1E+3; 1.5 en vez de 1.500."""
    if valor == valor.to_integral_value():
        return valor.quantize(Decimal(1))
    return valor.normalize()


class Contenido(NamedTuple):
    cantidad: Decimal
    unidad: str  # g | ml | u


def sin_tildes(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def normalizar_texto(texto: str) -> str:
    """Minúsculas, sin tildes, sin signos, abreviaturas expandidas, espacios simples."""
    if not texto:
        return ""
    t = sin_tildes(texto[:_LARGO_MAXIMO]).lower()
    t = re.sub(r"[^a-z0-9.,\s]", " ", t)
    # separa número pegado a unidad: "1lt" -> "1 lt"
    t = re.sub(r"(\d)([a-z])", r"\1 \2", t)
    palabras = []
    for palabra in t.replace(".", " ").split():
        palabra = palabra.strip(",")
        if not palabra:
            continue
        reemplazo = _ABREVIATURAS.get(palabra, palabra)
        if reemplazo:
            palabras.append(reemplazo)
    return " ".join(palabras)


def texto_de_busqueda(descripcion: str, marca: str | None) -> str:
    """Nombre normalizado + la marca si no aparece ya en el nombre."""
    nombre = normalizar_texto(descripcion)
    marca_normalizada = normalizar_texto(marca or "")
    if marca_normalizada and marca_normalizada not in nombre:
        nombre = f"{nombre} {marca_normalizada}"
    return nombre[:_LARGO_MAXIMO]


def extraer_contenido(texto: str) -> Contenido | None:
    """Devuelve el contenido en unidades canónicas (g, ml o u), o None si no hay."""
    if not texto:
        return None
    t = sin_tildes(texto[:_LARGO_MAXIMO]).lower()
    t = re.sub(r"(\d)([a-z])", r"\1 \2", t)
    t = re.sub(r"\bx(\d)", r"x \1", t)  # "x40 gr" → "x 40 gr"
    coincidencia = _PATRON_CONTENIDO.search(t)
    if not coincidencia:
        return None
    try:
        numero = Decimal(coincidencia.group(1).replace(",", "."))
    except InvalidOperation:
        return None
    if numero <= 0:
        return None
    unidad, factor = _UNIDADES[coincidencia.group(2)]
    pack = _PATRON_PACK.search(t[: coincidencia.start()])
    if pack is not None and int(pack.group(1)) > 1:
        numero *= int(pack.group(1))
    return Contenido(_sin_exponente(numero * factor), unidad)


def contenido_desde_sepa(cantidad: str, unidad: str) -> Contenido | None:
    """SEPA informa cantidad y unidad por separado (ej. '1.00' y 'lt', '400' y 'GRM')."""
    clave = sin_tildes((unidad or "").strip().lower()).rstrip(".").strip()
    if clave not in _UNIDADES_SEPA:
        return None
    try:
        numero = Decimal((cantidad or "").strip().replace(",", "."))
    except InvalidOperation:
        return None
    if numero <= 0:
        return None
    unidad_canonica, factor = _UNIDADES_SEPA[clave]
    return Contenido(_sin_exponente(numero * factor), unidad_canonica)


_CONTENIDO_MINIMO = Decimal(5)  # gramos o mililitros: menos que eso no se vende suelto


def contenido_de_fila_sepa(
    cantidad: str,
    unidad: str,
    cantidad_referencia: str,
    unidad_referencia: str,
    descripcion: str,
) -> Contenido | None:
    """Elige el mejor contenido disponible para una fila de SEPA.

    Coto informa la presentación real ("500 ml") y una referencia por litro ("1 ltr").
    Carrefour informa la presentación como "1 UNI" y el peso real en la referencia
    ("400 GRM"). Orden: presentación en peso o volumen; referencia en peso o volumen
    que no sea una unidad de precio (1, 100 o 1000 g o ml); lo que diga la
    descripción; y por último la presentación tal cual (unidades)."""
    presentacion = contenido_desde_sepa(cantidad, unidad)
    if presentacion is not None and presentacion.unidad != "u":
        if presentacion.cantidad >= _CONTENIDO_MINIMO:
            return presentacion
        # "1 ml" para una lata de 354 ml: dato de relleno de algunas cadenas (2.572
        # productos en el archivo real). Se busca en la referencia o en la descripción.
        presentacion = None
    referencia = contenido_desde_sepa(cantidad_referencia, unidad_referencia)
    if (
        referencia is not None
        and referencia.unidad != "u"
        and referencia.cantidad not in (Decimal(1), Decimal(100), Decimal(1000))
    ):
        return referencia
    desde_texto = extraer_contenido(descripcion)
    if desde_texto is not None and (
        desde_texto.unidad == "u" or desde_texto.cantidad >= _CONTENIDO_MINIMO
    ):
        return desde_texto
    return presentacion


def es_numero_ascii(texto: str) -> bool:
    """str.isdigit() acepta "²" o dígitos arábigos; acá solo 0-9."""
    return bool(texto) and texto.isascii() and texto.isdigit()


def es_ean_valido(codigo: str) -> bool:
    """EAN-8, UPC-A, EAN-13 o GTIN-14 con dígito verificador correcto."""
    if not es_numero_ascii(codigo) or len(codigo) not in (8, 12, 13, 14):
        return False
    digitos = [int(c) for c in codigo]
    verificador = digitos.pop()
    suma = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(digitos)))
    return (10 - suma % 10) % 10 == verificador


_PREFIJO_DISCO = re.compile(r"^(?:DISC:\s*)+(?:DISC\s+)?", re.IGNORECASE)
# "BOT-2000-ml.", "PZA-1-Kg", "Map-30-un.": código de empaque al final (Jumbo, Vea, Disco)
_CODIGO_EMPAQUE = re.compile(r"\s+[A-Za-z]{2,4}-\d+(?:[.,]\d+)?-[A-Za-z]{1,3}\.?$")


def limpiar_descripcion(texto: str) -> str:
    """Saca lo que las cadenas agregan al nombre y no ayuda a reconocer el producto."""
    limpio = _PREFIJO_DISCO.sub("", texto.strip())
    limpio = _CODIGO_EMPAQUE.sub("", limpio)
    limpio = " ".join(limpio.split())
    return limpio or " ".join(texto.split())
