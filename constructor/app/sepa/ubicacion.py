"""Coherencia entre la provincia declarada y las coordenadas de cada sucursal.

En el archivo real del 16/11/2026, 37 sucursales declaran una provincia que no
coincide con sus coordenadas (Carrefour publica sucursales de Córdoba, Mendoza y
Trelew como AR-C). Sin este control, una sucursal de Córdoba aparecería en el mapa
de CABA. Reglas, en orden:

1. Sin coordenadas: se confía en la provincia declarada.
2. Coordenadas dentro de la caja de la provincia declarada: todo bien.
3. Latitud y longitud invertidas que sí caen en la caja: se corrigen.
4. Declara CABA y la localidad lo confirma ("Capital Federal", "CABA"…), pero las
   coordenadas están afuera: la provincia se respeta y las coordenadas se descartan.
5. Coordenadas dentro de otra provincia conocida: se reasigna a esa provincia.
6. Ninguna de las anteriores: provincia desconocida (queda fuera de los filtros).
"""

from dataclasses import dataclass

from app.normalizacion import normalizar_texto

# (lat_min, lat_max, lon_min, lon_max). CABA va primero porque está contenida en la
# caja de Buenos Aires; solo se usa para validar lo declarado, nunca para pasar de
# AR-B a AR-C (la caja rectangular de CABA incluye partes del conurbano).
CAJAS_PROVINCIA: dict[str, tuple[float, float, float, float]] = {
    "AR-C": (-34.71, -34.52, -58.54, -58.33),
    "AR-B": (-41.10, -33.20, -63.50, -56.60),
}

_LOCALIDADES_CABA = ("capital federal", "caba", "ciudad autonoma", "c a b a", "cdad aut")


@dataclass(frozen=True)
class UbicacionSucursal:
    provincia: str | None
    latitud: float | None
    longitud: float | None
    corregida: bool


def _dentro(provincia: str, lat: float, lon: float) -> bool:
    lat_min, lat_max, lon_min, lon_max = CAJAS_PROVINCIA[provincia]
    return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


def _localidad_es_caba(localidad: str | None) -> bool:
    texto = normalizar_texto(localidad or "")
    return any(t in texto for t in _LOCALIDADES_CABA)


def ubicacion_coherente(
    provincia: str | None, lat: float | None, lon: float | None, localidad: str | None
) -> UbicacionSucursal:
    if lat is None or lon is None:
        return UbicacionSucursal(provincia, None, None, False)
    if provincia not in CAJAS_PROVINCIA:
        # Provincia sin caja definida: no hay contra qué validar.
        return UbicacionSucursal(provincia, lat, lon, False)
    if _dentro(provincia, lat, lon):
        return UbicacionSucursal(provincia, lat, lon, False)
    if _dentro(provincia, lon, lat):
        return UbicacionSucursal(provincia, lon, lat, True)
    if provincia == "AR-C" and _localidad_es_caba(localidad):
        return UbicacionSucursal(provincia, None, None, True)
    for otra in CAJAS_PROVINCIA:
        if otra != "AR-C" and otra != provincia and _dentro(otra, lat, lon):
            return UbicacionSucursal(otra, lat, lon, True)
    return UbicacionSucursal(None, lat, lon, True)
