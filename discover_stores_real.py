"""
discover_stores_real.py - Reemplaza discover_all_foodstuffs_nationwide.py

Ese script viejo le asignaba a cada tienda una ciudad al azar (reparto ponderado +
jitter matemático) porque no existía un endpoint conocido con la ubicación real.

Ahora sí existe: /v1/edge/store en la API de PAK'nSAVE y New World devuelve
nombre, dirección y lat/lon REALES de cada tienda.

Este script:
  1. Trae las tiendas reales de paknsave y new_world
  2. Las sube a retailer_stores con id = NZ_<chain>_<uuid_real_de_la_api>
  3. Desactiva (is_active=False, no borra) las tiendas fabricadas viejas que
     ya no corresponden a ningún id real

Uso:
  python3 discover_stores_real.py
"""
import os, json
from dotenv import load_dotenv
from supabase import create_client

from scrapers.foodstuffs_api import CHAINS, new_session, get_token, get_real_stores

load_dotenv()


def get_supabase():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise SystemExit("Falta SUPABASE_URL / SUPABASE_SERVICE_KEY en .env")
    return create_client(url, key)


def main():
    supabase = get_supabase()
    os.makedirs("output", exist_ok=True)

    all_rows = []
    for chain_id in CHAINS:
        session = new_session()
        print(f"\n=== {chain_id} ===")
        token = get_token(session, chain_id)
        stores = get_real_stores(session, token, chain_id)
        print(f"[{chain_id}] {len(stores)} tiendas reales encontradas")
        all_rows.extend(stores)

    with open("output/retailer_stores_real.json", "w", encoding="utf-8") as f:
        json.dump(all_rows, f, indent=2, ensure_ascii=False)
    print(f"\nTotal tiendas reales: {len(all_rows)} -> output/retailer_stores_real.json")

    new_ids_by_chain = {}
    for r in all_rows:
        new_ids_by_chain.setdefault(r["chain_id"], set()).add(r["id"])

    print("\nSubiendo a retailer_stores...")
    clean = [{k: v for k, v in r.items() if k != "api_store_id"} for r in all_rows]
    for i in range(0, len(clean), 100):
        batch = clean[i:i + 100]
        supabase.table("retailer_stores").upsert(batch, on_conflict="id").execute()
        print(f"  Batch {i // 100 + 1} OK ({len(batch)} tiendas)")

    print("\nDesactivando tiendas fabricadas viejas que ya no son reales...")
    for chain_id, new_ids in new_ids_by_chain.items():
        res = supabase.table("retailer_stores").select("id").eq("chain_id", chain_id).eq("is_active", True).execute()
        old_ids = [r["id"] for r in (res.data or []) if r["id"] not in new_ids]
        if not old_ids:
            print(f"  [{chain_id}] nada que desactivar")
            continue
        for i in range(0, len(old_ids), 100):
            batch = old_ids[i:i + 100]
            supabase.table("retailer_stores").update({"is_active": False}).in_("id", batch).execute()
        print(f"  [{chain_id}] desactivadas {len(old_ids)} tiendas fabricadas viejas")

    print("\nListo. retailer_stores ahora tiene ubicaciones reales para paknsave y new_world.")


if __name__ == "__main__":
    main()
