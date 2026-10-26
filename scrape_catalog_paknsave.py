"""
scrape_catalog_paknsave.py - Catálogo completo PAK'nSAVE: EAN + tienda + precio, TODO real.

Reemplaza a scrape_catalog_paknsave_AUTO.py / _REAL_PER_STORE.py / _REAL_PER_STORE_V2.py
(esos 3 asumían que prod["stores"] era un dict con precio por tienda - eso dejó de
ser cierto, el API actual (oct-2026) solo da un "averagePrice" nacional ahí).

El precio real por tienda se confirmó en vivo con el navegador real: el sitio llama
POST /v1/edge/store/{storeId}/decorateProducts al elegir tienda, y SÍ varía
(ej. Brócoli $1.89 en Auckland vs $2.99 en Invercargill). Este script:

  1. Recorre el catálogo completo UNA vez (EAN + nombre, no depende de la tienda)
  2. Para cada tienda real, pide el precio real de todos los productos en lotes
  3. Guarda y sube a Supabase tienda por tienda (progreso incremental: si se corta,
     no pierdes las tiendas ya completadas)

No necesitas cargar EANs ni precios a mano.

Uso:
  python3 scrape_catalog_paknsave.py                 # todo el catálogo, todas las tiendas
  python3 scrape_catalog_paknsave.py --max-stores 3   # prueba rápida
  python3 scrape_catalog_paknsave.py --dry-run        # no sube a Supabase
"""
import os, json, argparse, time
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client

from scrapers.foodstuffs_api import (
    new_session, get_token, get_real_stores, crawl_catalog, extract_ean,
    decorate_products_for_store,
)

CHAIN_ID = "paknsave"
load_dotenv()


def get_supabase():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise SystemExit("Falta SUPABASE_URL / SUPABASE_SERVICE_KEY en .env")
    return create_client(url, key)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def upsert_with_retry(supabase, batch, retries=4, delay=3):
    """Un timeout de red de un segundo hacia Supabase no debe tirar abajo una
    corrida de horas. Reintenta antes de rendirse."""
    for attempt in range(retries):
        try:
            supabase.table("product_prices").upsert(batch, on_conflict="ean,store_id,country_code").execute()
            return
        except Exception as e:
            if attempt == retries - 1:
                raise
            print(f"    Supabase error (intento {attempt + 1}/{retries}): {e} - reintentando en {delay}s...")
            time.sleep(delay)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="No sube a Supabase, solo guarda JSON local")
    parser.add_argument("--max-stores", type=int, default=None, help="Límite de tiendas (para pruebas rápidas)")
    parser.add_argument("--max-products", type=int, default=None, help="Límite de productos (para pruebas rápidas)")
    parser.add_argument("--start-store", type=int, default=1, help="Retomar desde el número de tienda N (1-indexado), para continuar una corrida cortada")
    args = parser.parse_args()

    supabase = None if args.dry_run else get_supabase()
    session = new_session()

    print(f"[{CHAIN_ID}] Obteniendo token...")
    token = get_token(session, CHAIN_ID)

    print(f"[{CHAIN_ID}] Cargando tiendas reales...")
    stores = get_real_stores(session, token, CHAIN_ID)
    if args.max_stores:
        stores = stores[:args.max_stores]
    print(f"[{CHAIN_ID}] {len(stores)} tiendas")

    print(f"[{CHAIN_ID}] Recorriendo catálogo completo (EAN + nombre, no depende de tienda)...")
    products = crawl_catalog(session, token, CHAIN_ID)
    print(f"[{CHAIN_ID}] {len(products)} productos únicos en el catálogo")

    ean_by_pid = {}
    for pid, prod in products.items():
        ean = extract_ean(prod)
        if ean:
            ean_by_pid[pid] = ean
    product_ids = list(ean_by_pid.keys())
    if args.max_products:
        product_ids = product_ids[:args.max_products]
    print(f"[{CHAIN_ID}] {len(product_ids)} productos con EAN real (de {len(products)} totales)")

    os.makedirs("output", exist_ok=True)
    run_id = f"CATALOG_{CHAIN_ID}_{datetime.now().strftime('%Y%m%d_%H%M')}"
    all_rows = []

    def get_fresh_token():
        return get_token(session, CHAIN_ID)

    for idx, store in enumerate(stores):
        store_num = idx + 1
        if store_num < args.start_store:
            continue
        print(f"\n[{CHAIN_ID}] Tienda {store_num}/{len(stores)}: {store['name']} ({store['city_name']})")
        priced = decorate_products_for_store(session, CHAIN_ID, store["api_store_id"], product_ids, get_fresh_token)
        print(f"  {len(priced)} productos con precio real en esta tienda")

        # Un mismo EAN puede tener 2 productIDs (variante "-EA-" por unidad y
        # "-KGM-" por kilo para items pesados) -> si no se deduplica por EAN,
        # el upsert revienta con "cannot affect row a second time". Preferimos
        # la variante por unidad (-EA-), que es el precio que se muestra normalmente.
        best_by_ean = {}
        for pid, data in priced.items():
            ean = ean_by_pid.get(pid)
            if not ean or not (0.1 < data["price"] < 5000):
                continue
            current = best_by_ean.get(ean)
            if current is None or ("-EA-" in pid and "-EA-" not in current[0]):
                best_by_ean[ean] = (pid, data)

        store_rows = []
        for ean, (pid, data) in best_by_ean.items():
            store_rows.append({
                "ean": ean,
                "country_code": "NZ",
                "region_id": store["region_id"],
                "city_id": store["city_id"],
                "store_id": store["id"],
                "chain_id": CHAIN_ID,
                "price": data["price"],
                "promo_price": data["price"] if data.get("promo") else None,
                "currency": "NZD",
                "stock": True,
                "last_updated": now_iso(),
                "last_updated_local": now_iso(),
                "source": f"catalog_{CHAIN_ID}_real_per_store_v1",
                "scrapper_run_id": run_id,
                "product_name": str(data.get("name") or "")[:200],
            })
        all_rows.extend(store_rows)

        # guardado incremental: progreso por tienda, no se pierde si se corta
        with open(f"output/catalog_{CHAIN_ID}_progress.json", "w", encoding="utf-8") as f:
            json.dump(all_rows, f, ensure_ascii=False)

        if supabase and store_rows:
            for i in range(0, len(store_rows), 200):
                batch = store_rows[i:i + 200]
                upsert_with_retry(supabase, batch)
            print(f"  Subidas {len(store_rows)} filas de {store['name']} a Supabase")

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    final_path = f"output/catalog_{CHAIN_ID}_{ts}.json"
    with open(final_path, "w", encoding="utf-8") as f:
        json.dump(all_rows, f, indent=2, ensure_ascii=False)
    print(f"\n[{CHAIN_ID}] LISTO. {len(all_rows)} filas (ean x tienda) con precio real -> {final_path}")


if __name__ == "__main__":
    main()
