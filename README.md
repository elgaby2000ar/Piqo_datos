# Piqo_datos

Paquete diario de precios para la app **Piqo**, publicado en GitHub Pages.

Todos los días una PC en Argentina baja el último ZIP de
[SEPA](https://datos.produccion.gob.ar/dataset/sepa-precios) (precios que las cadenas
informan a la Secretaría de Comercio, datos abiertos), se queda con CABA y la provincia
de Buenos Aires, arma el paquete y lo sube a la rama `paquete`, que GitHub Pages publica tal cual
(Settings → Pages → Deploy from a branch → `paquete`, raíz). Si un día no se actualiza,
queda publicado el anterior.

¿Por qué una PC y no GitHub Actions? El portal de datos devuelve 403 a las IPs de
centros de datos (probado el 18/11/2026): solo responde a conexiones desde Argentina.

## Instalar en la PC (una vez)

1. Instalar [Python 3.12 o más nuevo](https://www.python.org/downloads/) (marcar "Add to PATH") y Git.
2. Clonar este repositorio: `git clone https://github.com/elgaby2000ar/Piqo_datos`
3. En PowerShell, dentro de la carpeta: `powershell -ExecutionPolicy Bypass -File pc\instalar.ps1`

Corre a las 14:00 y 18:30; si la PC estaba apagada, apenas se prende. Registro en `pc\actualizar.log`.

## Formato (`v1/`)

| Archivo | Contenido |
| --- | --- |
| `manifiesto.json` | fecha de los datos, cantidades, cantidad de fragmentos |
| `comercios.json` | sucursales: `id, cadena, nombre, direccion, barrio, provincia, lat, lon`; su posición es el número de sucursal |
| `productos.json` | catálogo: `ean, nombre, marca, categoria, contenido, unidad, minimo, sucursales`; su posición es el número de producto |
| `leyendas.json` | textos de las ofertas |
| `p/<n>.json` | `{número de producto: {"id": uuid, "p": [[sucursal, lista, oferta, leyenda], ...]}}` con `n = número de producto % fragmentos` |

Los ids son UUID5 deterministas (del EAN o de la clave de sucursal de SEPA): el servidor
de Piqo y la app llegan al mismo id sin consultarse.

## Código

`constructor/` es una copia de los módulos de lectura de SEPA del repositorio de Piqo
(`backend/scripts/sincronizar_piqo_datos.sh`). No editar acá: se pisa en cada sincronización.

A mano: `cd constructor && pip install httpx && python scripts/armar_paquete.py --salida ../sitio`
