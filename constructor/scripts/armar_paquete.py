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
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.paquete import construir  # noqa: E402
from app.sepa.descarga import URL_RECURSOS, descargar, validar_url  # noqa: E402
from app.sepa.lector import ArchivoSepaInvalido, Limites  # noqa: E402

HOSTS = ["datos.produccion.gob.ar"]
LIMITES = Limites(
    max_bytes_miembro=3_000_000_000,
    max_ratio_compresion=250,
    max_profundidad=2,
    max_miembros=5_000,
)
PROVINCIAS = ["AR-C", "AR-B"]


def ultimo_recurso(cliente: httpx.Client) -> tuple[str, date]:
    """El ZIP más reciente de los siete (uno por día de la semana) y su fecha."""
    datos = cliente.get(validar_url(URL_RECURSOS, HOSTS)).json()
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
            with httpx.Client(timeout=httpx.Timeout(30.0, read=180.0)) as cliente:
                url, fecha = ultimo_recurso(cliente)
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
