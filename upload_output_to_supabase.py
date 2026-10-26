
"""
upload_output_to_supabase.py - Sube el output/prices_*.json a Supabase product_prices
Uso: 
  1. Pon tu SUPABASE_URL y SUPABASE_SERVICE_KEY en .env o exporta
  2. python3 upload_output_to_supabase.py --file output/prices_20261019_1014.json
"""

import os, json, argparse, glob
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")

def get_latest_json():
    files = sorted(glob.glob("output/prices_*.json"), reverse=True)
    return files[0] if files else None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=str, help="Archivo JSON output/prices_xxx.json, si no se pone usa el ultimo")
    args = parser.parse_args()

    json_path = args.file or get_latest_json()
    if not json_path or not os.path.exists(json_path):
        print(f"❌ No se encontró archivo. Busqué: {json_path}")
        print("Corre primero: python3 Test-Scraper-Local.py --ean 9300633609795 --chain chemist_warehouse_nz")
        return

    print(f"📄 Usando archivo: {json_path}")
    
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    if not data:
        print("❌ JSON vacío, 0 rows")
        return
    
    print(f"📦 {len(data)} rows a subir:")
    for r in data[:5]:
        print(f"  - {r['ean']} | {r['chain_id']} | ${r['price']} | {r['product_name'][:40]}")

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("\n❌ Falta SUPABASE_URL o SUPABASE_SERVICE_KEY")
        print("Crea un archivo .env en ean-glasses-marketplaceGithub/ con:")
        print("SUPABASE_URL=https://tu-proyecto.supabase.co")
        print("SUPABASE_SERVICE_KEY=tu_service_key_largo")
        print("\nLos encuentras en Supabase Dashboard -> Settings -> API")
        return

    try:
        from supabase import create_client
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        # Upsert
        print(f"\n⬆️ Subiendo a Supabase {SUPABASE_URL}...")
        res = supabase.table("product_prices").upsert(data, on_conflict="ean,store_id,country_code").execute()
        
        print(f"✅ Subido OK. Respuesta: {len(res.data) if res.data else 'ok'} rows afectados")
        
        # Verifica
        print("\n🔍 Verificando...")
        check = supabase.table("product_prices").select("ean,chain_id,price,product_name,last_updated").order("last_updated", desc=True).limit(5).execute()
        print(f"Últimos 5 en Supabase:")
        for r in check.data or []:
            print(f"  {r['ean']} | {r['chain_id']} | ${r['price']} | {r['product_name']}")
        
        print("\n✅ Ahora tu API Vercel ya puede leerlo:")
        print("curl https://tu-vercel.vercel.app/api/test?chain=chemist_warehouse_nz&ean=9300633609795")
        print("Y tu iPhone lo ve con MarketplaceService_SUPABASE.swift")
        
    except Exception as e:
        import traceback
        print(f"❌ Error subiendo: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()
