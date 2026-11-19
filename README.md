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

## La PC que lo arma

Los scripts viven en el repositorio de Piqo (`pc/`, ver `pc/LEEME.md`): la PC clona Piqo,
y esa tarea clona este repositorio al lado para publicar. Todos los días: precios de SEPA
y ofertas de góndola de las tiendas online; una vez por semana: promos bancarias
(`promos/promos.json` de esta rama `main`).

## Formato (`v1/`)

| Archivo | Contenido |
| --- | --- |
| `manifiesto.json` | fecha de los datos, cantidades, cantidad de fragmentos |
| `comercios.json` | sucursales: `id, cadena, nombre, direccion, barrio, provincia, lat, lon`; su posición es el número de sucursal |
| `productos.json` | catálogo: `ean, nombre, marca, categoria, contenido, unidad, minimo, sucursales`; su posición es el número de producto |
| `leyendas.json` | textos de las ofertas |
| `promos.json` | promos bancarias vigentes (mismo formato que `GET /api/v1/promos` de Piqo); sale de `promos/promos.json` de `main`, que se actualiza una vez por semana |
| `ofertas.json` | ofertas de góndola de las tiendas online (hoy Coto Digital): por cadena, `[clave, factor, texto, lleva, comunidad]`; `factor` es precio por unidad con la oferta / precio sin ella (3x2 → 0.666667 llevando 3) |
| `p/<n>.json` | `{número de producto: {"id": uuid, "p": [[sucursal, lista, oferta, leyenda], ...]}}` con `n = número de producto % fragmentos` |

Los ids son UUID5 deterministas (del EAN o de la clave de sucursal de SEPA): el servidor
de Piqo y la app llegan al mismo id sin consultarse.

## Código

El armado está en el repositorio de Piqo (`backend/app/paquete.py`,
`backend/app/ofertas_super.py`, `backend/scripts/armar_paquete.py`). `constructor/` es una
copia vieja que ya no se usa.
