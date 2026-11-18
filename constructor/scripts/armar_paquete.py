"""Baja el último ZIP de SEPA y arma el paquete estático de precios.

Lo corre todos los días el repositorio público Piqo_datos (GitHub Actions) y publica la
carpeta de salida en GitHub Pages. También sirve a mano:

    python scripts/armar_paquete.py --salida sitio [--zip archivo.zip --fecha 2026-11-16]

Códigos de salida: 0 bien; 75 SEPA no respondió (reintentar más tarde); 1 el archivo
cambió de formato o vino vacío (hay que mirarlo; se mantiene publicado el de ayer).
"""

import argparse
import json
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.paquete import construir  # noqa: E402
from app.sepa.descarga import URL_RECURSOS, descargar, validar_url  # noqa: E402
from app.sepa.lector import ArchivoSepaInvalido, Limites  # noqa: E402


def hoy_en_argentina() -> date:
    return datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).date()


HOSTS = ["datos.produccion.gob.ar"]
LIMITES = Limites(
    max_bytes_miembro=3_000_000_000,
    max_ratio_compresion=250,
    max_profundidad=2,
    max_miembros=5_000,
)
PROVINCIAS = ["AR-C", "AR-B"]
# Si el portal bloquea la API (pasa con IPs de centros de datos), se usan las URLs fijas
# de cada día: SEPA reemplaza el archivo del mismo día de la semana, con la misma URL.
_BASE = "https://datos.produccion.gob.ar/dataset/6f47ec76-d1ce-4e34-a7e1-621fe9b1d0b5/resource/"
URLS_POR_DIA = {
    0: _BASE + "0a9069a9-06e8-4f98-874d-da5578693290/download/sepa_lunes.zip",
    1: _BASE + "9dc06241-cc83-44f4-8e25-c9b1636b8bc8/download/sepa_martes.zip",
    2: _BASE + "1e92cd42-4f94-4071-a165-62c4cb2ce23c/download/sepa_miercoles.zip",
    3: _BASE + "d076720f-a7f0-4af8-b1d6-1b99d5a90c14/download/sepa_jueves.zip",
    4: _BASE + "91bc072a-4726-44a1-85ec-4a8467aad27e/download/sepa_viernes.zip",
    5: _BASE + "b3c3da5d-213d-41e7-8d74-f23fda0a3c30/download/sepa_sabado.zip",
    6: _BASE + "f8e75128-515a-436e-bf8d-5c63a62f2005/download/sepa_domingo.zip",
}


def ultimo_recurso(cliente: httpx.Client) -> tuple[str, date]:
    """El ZIP más reciente de los siete (uno por día de la semana) y su fecha."""
    respuesta = cliente.get(
        validar_url(URL_RECURSOS, HOSTS), headers={"User-Agent": "PiqoBot/1.0 (+datos abiertos)"}
    )
    try:
        datos = respuesta.json()
    except ValueError as error:
        # Pasa si el portal responde con una página de error o un desafío anti-bots.
        raise ArchivoSepaInvalido(
            f"El portal de datos respondió {respuesta.status_code} sin JSON: "
            f"{respuesta.text[:200]!r}"
        ) from error
    recursos = [
        r
        for r in datos["result"]["resources"]
        if str(r.get("url", "")).endswith(".zip") and r.get("last_modified")
    ]
    if not recursos:
        raise ArchivoSepaInvalido("SEPA no lista ningún ZIP")
    mas_nuevo = max(recursos, key=lambda r: r["last_modified"])
    return mas_nuevo["url"], date.fromisoformat(mas_nuevo["last_modified"][:10])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--salida", required=True)
    parser.add_argument("--zip", help="usar un ZIP ya descargado")
    parser.add_argument("--fecha", help="fecha de los datos (con --zip)")
    args = parser.parse_args()

    try:
        if args.zip:
            archivo = Path(args.zip)
            fecha = date.fromisoformat(args.fecha) if args.fecha else date.today()
            resultado = construir(archivo, fecha, Path(args.salida), LIMITES, PROVINCIAS)
        else:
            with httpx.Client(
                timeout=httpx.Timeout(30.0, read=180.0),
                headers={"User-Agent": "PiqoBot/1.0 (+datos abiertos)"},
            ) as cliente:
                try:
                    url, fecha = ultimo_recurso(cliente)
                except ArchivoSepaInvalido as error:
                    print(f"{error}; se usa la URL fija del día", file=sys.stderr)
                    fecha = hoy_en_argentina()
                    url = URLS_POR_DIA[fecha.weekday()]
                with tempfile.TemporaryDirectory() as tmp:
                    bajado = descargar(url, Path(tmp) / "sepa.zip", HOSTS, cliente)
                    resultado = construir(
                        bajado.ruta, fecha, Path(args.salida), LIMITES, PROVINCIAS
                    )
    except httpx.HTTPError as error:
        print(f"SEPA no respondió: {type(error).__name__}", file=sys.stderr)
        return 75
    except ArchivoSepaInvalido as error:
        print(f"Archivo inválido: {error}", file=sys.stderr)
        return 1
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
