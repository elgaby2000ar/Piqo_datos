"""Nombres de cadena como los dice la gente.

SEPA informa la "bandera" tal como la carga cada empresa: Carrefour publica sus
formatos como "Express", "Market" y "Maxi" a secas, y otras usan la razón social.
Relevado del archivo real del 16/11/2026.
"""

from app.normalizacion import normalizar_texto

_LEGIBLES = {
    "express": "Carrefour Express",
    "market": "Carrefour Market",
    "maxi": "Carrefour Maxi",
    "hipermercado carrefour": "Carrefour",
    "coto cicsa": "Coto",
    "supermercados dia": "DIA",
    "deheza s a i c f e i": "Deheza",
    "estacion lima s a": "Estación Lima",
    "farmacity": "Farmacity",
    "superchangomas": "Changomas",
    "hiperchangomas": "Changomas",
    "sup unicoop": "Unicoop",
    "cooperativa obrera limitada de consumo y vivienda": "Cooperativa Obrera",
}


def nombre_cadena(bandera: str | None) -> str | None:
    if not bandera or not bandera.strip():
        return None
    limpia = " ".join(bandera.split())
    return _LEGIBLES.get(normalizar_texto(limpia), limpia)
