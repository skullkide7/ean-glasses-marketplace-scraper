"""
scrape_catalog_new_world.py - Catálogo completo New World: EAN + tienda + precio, TODO real.

Misma lógica que scrape_catalog_paknsave.py (ambos son Foodstuffs, misma API y mismo
endpoint real de precio por tienda: POST /v1/edge/store/{storeId}/decorateProducts).
New World no tenía NINGÚN scraper de catálogo antes (solo 1 EAN a la vez, cargado a mano).

No necesitas cargar EANs ni precios a mano.

Procesa varias tiendas EN PARALELO (--concurrency, default 4) para no tardar horas -
cada tienda usa su propia sesión/token, así que no hay nada compartido entre hilos
salvo la subida a Supabase, que queda serializada en el hilo principal.

Uso:
  python3 scrape_catalog_new_world.py                    # todo el catálogo, todas las tiendas
  python3 scrape_catalog_new_world.py --concurrency 6     # más rápido, más peticiones simultáneas
  python3 scrape_catalog_new_world.py --max-stores 3      # prueba rápida
  python3 scrape_catalog_new_world.py --dry-run           # no sube a Supabase
"""
import os, json, argparse, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client

from scrapers.foodstuffs_api import (
    new_session, get_token, get_real_stores, crawl_catalog, extract_ean,
    decorate_products_for_store,
)

CHAIN_ID = "new_world"
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


def build_store_rows(store, priced, ean_by_pid, run_id):
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

    rows = []
    for ean, (pid, data) in best_by_ean.items():
        rows.append({
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
    return rows


def process_store(store, product_ids):
    """Corre en un hilo propio: su propia sesión y su propio token, nada compartido."""
    worker_session = new_session()

    def get_fresh_token():
        return get_token(worker_session, CHAIN_ID)

    priced = decorate_products_for_store(worker_session, CHAIN_ID, store["api_store_id"], product_ids, get_fresh_token)
    return store, priced


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="No sube a Supabase, solo guarda JSON local")
    parser.add_argument("--max-stores", type=int, default=None, help="Límite de tiendas (para pruebas rápidas)")
    parser.add_argument("--max-products", type=int, default=None, help="Límite de productos (para pruebas rápidas)")
    parser.add_argument("--start-store", type=int, default=1, help="Retomar desde el número de tienda N (1-indexado), para continuar una corrida cortada")
    parser.add_argument("--concurrency", type=int, default=4, help="Tiendas procesadas en paralelo (default 4)")
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

    pending_stores = [s for idx, s in enumerate(stores) if idx + 1 >= args.start_store]
    print(f"[{CHAIN_ID}] Procesando {len(pending_stores)} tiendas con concurrencia={args.concurrency}...")

    done_count = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = {executor.submit(process_store, store, product_ids): store for store in pending_stores}
        for future in as_completed(futures):
            store = futures[future]
            done_count += 1
            try:
                store, priced = future.result()
            except Exception as e:
                print(f"\n[{CHAIN_ID}] ERROR en {store['name']}: {e} - se reintentará en la próxima corrida con --start-store")
                continue

            print(f"\n[{CHAIN_ID}] ({done_count}/{len(pending_stores)}) {store['name']} ({store['city_name']}): {len(priced)} productos con precio real")
            store_rows = build_store_rows(store, priced, ean_by_pid, run_id)
            all_rows.extend(store_rows)

            # guardado incremental: progreso acumulado, no se pierde si se corta
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
