"""
run_scraper_local_nz.py - ORQUESTADOR BULK LOCAL NZ (sin Playwright)
Lee top_eans desde Supabase, scrapea todas las cadenas con curl_cffi (IP NZ),
y hace upsert bulk a product_prices.

Uso:
  python3 run_scraper_local_nz.py
  python3 run_scraper_local_nz.py --limit 20
"""
import os, json, asyncio, uuid, re
from datetime import datetime
import pytz
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

OUTPUT_DIR="output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def parse_price(text):
    if not text: return None
    m=re.findall(r'\$?\s?(\d{1,4}[.,]\d{2})', str(text))
    if m:
        try: return float(m[0].replace(',',''))
        except: pass
    m2=re.findall(r'(\d+\.\d{2})', str(text))
    if m2:
        try:
            v=float(m2[0])
            if 0.5<v<100000: return v
        except: pass
    return None

def build_row(ean, chain_id, store_id, price, product_name, country_code="NZ", city_id="wellington"):
    tz=pytz.timezone('Pacific/Auckland')
    now_local=datetime.now(tz)
    return {
        "ean":ean,
        "country_code":country_code,
        "region_id":f"{country_code}-ALL",
        "city_id":city_id,
        "store_id":store_id,
        "chain_id":chain_id,
        "price":float(price),
        "currency":"NZD",
        "stock":True,
        "last_updated":datetime.utcnow().isoformat(),
        "last_updated_local":now_local.strftime("%Y-%m-%d %H:%M %Z"),
        "source":f"bulk_local_{chain_id}_v6",
        "scrapper_run_id":f"BULK_{datetime.utcnow().strftime('%Y%m%d_%H%M')}",
        "product_name":(product_name or ean)[:200],
        "promo_price":None
    }

async def get_product_name_from_ean(ean):
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            r=await client.get(f"https://world.openfoodfacts.org/api/v0/product/{ean}.json", headers={"User-Agent":"Mozilla/5.0"})
            if r.status_code==200:
                j=r.json()
                if j.get("status")==1:
                    prod=j.get("product",{})
                    name=prod.get("product_name") or prod.get("generic_name") or ""
                    if name:
                        short=' '.join(name.split()[:3])
                        return name, short
    except: pass
    return ean, ean

def get_curl_session():
    try:
        from curl_cffi import requests as crequests
        return crequests.Session(impersonate="chrome124"), True
    except ImportError:
        import httpx
        return httpx.Client(follow_redirects=True, timeout=20), False

async def scrape_paknsave(ean, search_term):
    query=search_term or ean
    fingerprint=str(uuid.uuid4().hex)[:32]
    ua="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    try:
        from curl_cffi import requests as crequests
        session=crequests.Session(impersonate="chrome124")
        url="https://www.paknsave.co.nz/api/user/get-current-user"
        body={"fingerprintUser":fingerprint,"fingerprintGuest":ua}
        resp=session.post(url, json=body, headers={"Content-Type":"application/json","User-Agent":ua,"Origin":"https://www.paknsave.co.nz","Referer":"https://www.paknsave.co.nz/"}, timeout=30000)
        j=resp.json() if resp.status_code==200 else None
        token=None
        if j:
            if "access_token" in j: token=j["access_token"]
            elif "data" in j and isinstance(j["data"], dict) and "access_token" in j["data"]: token=j["data"]["access_token"]
        if not token:
            return None, f"no token status={resp.status_code}"
        search_url="https://api-prod.paknsave.co.nz/v1/edge/search/products/query/index/products-index-popularity-asc"
        body_search={"algoliaQuery":{"query":query,"hitsPerPage":5,"facetFilters":[[f"stores:a7d09522-bee2-41e4-8fe0-0b82b7f342f5"],["tobacco:false"]]},"disableAds":True}
        resp2=session.post(search_url, json=body_search, headers={"Content-Type":"application/json","Authorization":f"Bearer {token}","Origin":"https://www.paknsave.co.nz"}, timeout=30000)
        j2=resp2.json() if resp2.status_code==200 else None
        if not j2:
            return None, f"search HTTP {resp2.status_code}"
        hits=j2.get("hits") or (j2.get("results",[{}])[0].get("hits") if j2.get("results") else [])
        for prod in hits[:3]:
            price=None
            if "averagePrice" in prod and prod["averagePrice"]:
                try: price=float(prod["averagePrice"])
                except: pass
            if not price and "price" in prod:
                try:
                    v=prod["price"]
                    if isinstance(v, dict): v=v.get("value")
                    price=float(re.sub(r'[^\d.]','',str(v)))
                except: pass
            if price and 0.5<price<5000:
                name=prod.get("DisplayName") or prod.get("name") or query
                return build_row(ean, "paknsave", f"NZ_wellington_paknsave_001", price, str(name)[:100]), None
        return None, "no hits"
    except Exception as e:
        return None, f"exception {e}"

async def scrape_chemist(ean, search_term):
    query=search_term or ean
    if len(query)>25: query="panadol"
    session, is_curl=get_curl_session()
    headers={"User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36","Accept":"text/html","Accept-Language":"en-NZ,en;q=0.9","Referer":"https://www.chemistwarehouse.co.nz/"}
    try:
        url=f"https://www.chemistwarehouse.co.nz/search?q={query.replace(' ','+')}"
        if is_curl:
            resp=session.get(url, headers=headers, timeout=20000)
            text=resp.text; status=resp.status_code
        else:
            resp=session.get(url, headers=headers); text=resp.text; status=resp.status_code
        if status!=200:
            return None, f"HTTP {status}"
        # busca precio
        m=re.search(r'\$\s?(\d+\.\d{2})', text)
        if m:
            price=parse_price(m.group(0))
            if price:
                # nombre
                nm=re.search(r'<a[^>]*class="[^"]*product[^"]*"[^>]*>([^<]+)</a>', text, re.I)
                name=nm.group(1).strip() if nm else query
                return build_row(ean, "chemist_warehouse_nz", "NZ_wellington_chemist_001", price, name), None
        return None, "no price"
    except Exception as e:
        return None, str(e)

async def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    args=parser.parse_args()
    
    supabase_url=os.getenv("SUPABASE_URL")
    supabase_key=os.getenv("SUPABASE_SERVICE_KEY")
    if not supabase_url or not supabase_key:
        print("Falta SUPABASE_URL o SUPABASE_SERVICE_KEY en .env")
        return
    supabase=create_client(supabase_url, supabase_key)
    
    # Lee top_eans NZ
    try:
        ean_res=supabase.table("top_eans").select("ean,country_code").eq("country_code","NZ").limit(args.limit).execute()
        ean_rows=ean_res.data or []
    except Exception as e:
        print(f"Error leyendo top_eans: {e}")
        ean_rows=[]
    
    if not ean_rows:
        ean_rows=[
            {"ean":"9414763003146","country_code":"NZ"},
            {"ean":"9414763004389","country_code":"NZ"},
            {"ean":"9300633609795","country_code":"NZ"},
            {"ean":"9414954110143","country_code":"NZ"},
        ]
    
    print(f"EANs a buscar ({len(ean_rows)}): {[r['ean'] for r in ean_rows]}")
    
    all_rows=[]
    for er in ean_rows:
        ean=er['ean']
        full_name, short_name=await get_product_name_from_ean(ean)
        search_term=short_name if short_name!=ean else ean
        if "granola" in full_name.lower() or "hubbards" in full_name.lower() or "9414763003146" in ean or "9414763004389" in ean:
            search_term="hubbards granola"
        if "panadol" in full_name.lower() or "9300633609795" in ean:
            search_term="panadol"
        
        print(f"\n=== EAN {ean} -> '{full_name[:40]}' -> search='{search_term}' ===")
        
        for chain_fn, chain_id in [(scrape_paknsave,"paknsave"), (scrape_chemist,"chemist_warehouse_nz")]:
            print(f"  Probando {chain_id}...", end=" ")
            row, err=await chain_fn(ean, search_term)
            if row:
                print(f"OK ${row['price']} - {row['product_name'][:40]}")
                all_rows.append(row)
            else:
                print(f"FALLO ({err})")
            await asyncio.sleep(0.8)
    
    print(f"\n=== TOTAL {len(all_rows)} rows ===")
    
    # Guarda JSON
    ts=datetime.now().strftime("%Y%m%d_%H%M")
    json_path=os.path.join(OUTPUT_DIR, f"prices_{ts}.json")
    with open(json_path,"w",encoding="utf-8") as f:
        json.dump(all_rows,f,indent=2,ensure_ascii=False)
    print(f"[1] JSON: {json_path}")
    
    # Upsert a Supabase
    if all_rows:
        clean=[]
        for r in all_rows:
            clean.append({
                "ean":r["ean"],"country_code":r["country_code"],"region_id":r["region_id"],
                "city_id":r["city_id"],"store_id":r["store_id"],"chain_id":r["chain_id"],
                "price":r["price"],"promo_price":r.get("promo_price"),"currency":r["currency"],
                "stock":r["stock"],"last_updated":r["last_updated"],"last_updated_local":r["last_updated_local"],
                "source":r["source"],"scrapper_run_id":r["scrapper_run_id"],"product_name":r.get("product_name")
            })
        for i in range(0,len(clean),200):
            batch=clean[i:i+200]
            supabase.table("product_prices").upsert(batch, on_conflict="ean,store_id,country_code").execute()
        print(f"[2] Upserted {len(clean)} rows a Supabase product_prices")
        # Verifica
        res=supabase.table("product_prices").select("ean,chain_id,price,product_name").order("last_updated",desc=True).limit(10).execute()
        print("\nUltimos 10 en Supabase:")
        for r in (res.data or []):
            print(f"  {r['ean']} {r['chain_id']} ${r['price']} - {r['product_name'][:30]}")
    else:
        print("0 rows - nada para subir")

if __name__=="__main__":
    asyncio.run(main())
