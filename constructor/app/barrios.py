"""Barrio oficial de CABA a partir de las coordenadas.

En SEPA, el 39 % de las sucursales de CABA dicen solo "Capital Federal" o "Ciudad
Autónoma de Buenos Aires", y el resto escribe el barrio a su manera ("Pompeya",
"Once", "Barrio Norte", "v illa lugano"). Con eso no se puede filtrar por barrio.

Los límites salen del dataset "Barrios" del Gobierno de la Ciudad
(data.buenosaires.gob.ar/dataset/barrios, CC BY 2.5 AR), simplificados a unos 15 m:
48 polígonos en app/datos/barrios_caba.json. Formato compacto: por barrio
[nombre, comuna, anillos]; cada anillo es el primer punto en diezmilésimas de grado
(lon, lat) y después diferencias.

Una sucursal sobre una avenida que separa dos barrios puede caer de cualquier lado
(las coordenadas de SEPA tienen su propio error); se acepta.
"""

import json
from functools import lru_cache
from pathlib import Path

from app.normalizacion import normalizar_texto

ARCHIVO = Path(__file__).parent / "datos" / "barrios_caba.json"

# El dataset escribe sin tildes; así se muestran.
NOMBRE_OFICIAL = {
    "Agronomia": "Agronomía", "Constitucion": "Constitución", "Nuñez": "Núñez",
    "San Cristobal": "San Cristóbal", "San Nicolas": "San Nicolás",
    "Velez Sarsfield": "Vélez Sarsfield", "Villa Del Parque": "Villa del Parque",
    "Villa Gral. Mitre": "Villa General Mitre", "Villa Ortuzar": "Villa Ortúzar",
    "Villa Pueyrredon": "Villa Pueyrredón", "Paternal": "La Paternal",
}

# Nombres populares o variantes que se escriben en SEPA → barrio oficial.
ALIAS = {
    "once": "Balvanera", "abasto": "Balvanera", "congreso": "Balvanera",
    "barrio norte": "Recoleta", "tribunales": "San Nicolás", "microcentro": "San Nicolás",
    "pompeya": "Nueva Pompeya", "lugano": "Villa Lugano", "v illa lugano": "Villa Lugano",
    "devoto": "Villa Devoto", "santa rita": "Villa Santa Rita", "paternal": "La Paternal",
    "belgrano r": "Belgrano", "flores sur": "Flores", "naon": "Mataderos",
    "villa general mitre": "Villa General Mitre", "villa gral mitre": "Villa General Mitre",
}

Anillo = list[tuple[float, float]]


@lru_cache(maxsize=1)
def poligonos() -> list[tuple[str, int, list[Anillo]]]:
    datos = json.loads(ARCHIVO.read_text(encoding="utf-8"))
    resultado = []
    for nombre, comuna, anillos in datos:
        decodificados = []
        for plano in anillos:
            x = y = 0
            puntos = []
            for i in range(0, len(plano), 2):
                x += plano[i]
                y += plano[i + 1]
                puntos.append((x / 1e4, y / 1e4))
            decodificados.append(puntos)
        resultado.append((NOMBRE_OFICIAL.get(nombre, nombre), int(comuna), decodificados))
    return resultado


def _adentro(lon: float, lat: float, anillo: Anillo) -> bool:
    """Ray casting: cuántas veces cruza el borde una semirrecta hacia el este."""
    dentro = False
    j = len(anillo) - 1
    for i in range(len(anillo)):
        xi, yi = anillo[i]
        xj, yj = anillo[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            dentro = not dentro
        j = i
    return dentro


def barrio_de(latitud: float | None, longitud: float | None) -> str | None:
    """Barrio oficial de CABA que contiene el punto, o None si cae fuera de la Ciudad."""
    if latitud is None or longitud is None:
        return None
    if not (-34.71 < latitud < -34.52 and -58.54 < longitud < -58.33):
        return None
    for nombre, _, anillos in poligonos():
        exterior, *huecos = anillos
        if _adentro(longitud, latitud, exterior) and not any(
            _adentro(longitud, latitud, h) for h in huecos
        ):
            return nombre
    return None


@lru_cache(maxsize=1)
def _por_clave() -> dict[str, str]:
    claves = {normalizar_texto(n): n for n, _, _ in poligonos()}
    claves.update({normalizar_texto(k): v for k, v in ALIAS.items()})
    return claves


def barrio_escrito(texto: str | None) -> str | None:
    """El barrio oficial que corresponde a lo que dice SEPA ("PALERMO", "Once"), o None
    si no nombra un barrio ("Capital Federal")."""
    if not texto:
        return None
    return _por_clave().get(normalizar_texto(texto))


def barrio_caba(latitud: float | None, longitud: float | None, texto: str | None) -> str | None:
    """Primero las coordenadas (son lo único que no depende de cómo lo escribió cada
    cadena); si no hay o caen fuera, lo que diga el texto."""
    return barrio_de(latitud, longitud) or barrio_escrito(texto)


def recalcular_barrios(sesion) -> int:  # noqa: ANN001 (Session; import tardío evita ciclos)
    """Corrige el barrio de los comercios de CABA según las coordenadas. Devuelve cuántos
    cambiaron. Se corre una vez después de actualizar (las importaciones nuevas ya lo
    hacen solas)."""
    from sqlalchemy import select

    from app.models import Comercio

    cambios = 0
    for comercio in sesion.scalars(select(Comercio).where(Comercio.provincia == "AR-C")):
        nuevo = barrio_caba(comercio.latitud, comercio.longitud, comercio.barrio)
        if nuevo and nuevo != comercio.barrio:
            comercio.barrio = nuevo
            cambios += 1
    sesion.commit()
    return cambios
