# Datos escrapeados: precios reales por tienda (PAK'nSAVE / New World, NZ)

Snapshot de precios reales por tienda, obtenidos replicando llamadas internas
de los sitios web de PAK'nSAVE y New World (Foodstuffs NZ) — no existe una API
pública que entregue este dato. Ver `scrapers/foodstuffs_api.py` para el
mecanismo exacto.

**Fecha de scraping:** PAK'nSAVE 2026-10-25, New World 2026-10-26 (antes del
inicio del hackathon, 26 oct). El pipeline que lo generó (este repo) y la
integración con los lentes Meta (otro repo) se construyeron/extendieron
durante la ventana del hackathon; este dataset es la infraestructura de datos
propia que alimenta esa integración, no el entregable del hackathon en sí.

## Archivos

- `retailer_stores.json` — 207 tiendas (ambas cadenas) con id, nombre,
  dirección, lat/lon.
- `prices_paknsave.csv.gz` — 615.734 filas (ean, store_id, chain_id, price,
  promo_price, currency, stock, last_updated, product_name).
- `prices_new_world.csv.gz` — 1.155.136 filas, mismas columnas.

## Columnas de los CSV

| columna | descripción |
|---|---|
| `ean` | código de barras |
| `store_id` | FK al `id` en `retailer_stores.json` |
| `chain_id` | `paknsave` \| `newworld` |
| `price` | precio real en esa tienda, NZD |
| `promo_price` | precio en oferta si aplica, si no vacío |
| `currency` | `NZD` |
| `stock` | disponibilidad reportada |
| `last_updated` | timestamp del scrape |
| `product_name` | nombre del producto |

Para cargarlo a Supabase: `upload_output_to_supabase.py` (ajustar paths a
`data/` en vez de `output/`).
