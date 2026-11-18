# Piqo_datos

Paquete diario de precios para la app **Piqo**, publicado en GitHub Pages.

Todos los días (08:17 y 14:43, hora argentina) GitHub Actions baja el último ZIP de
[SEPA](https://datos.produccion.gob.ar/dataset/sepa-precios) (precios que las cadenas
informan a la Secretaría de Comercio, datos abiertos), se queda con CABA y la provincia
de Buenos Aires y lo publica como JSON. Si algo falla, queda publicado el del día anterior.

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
