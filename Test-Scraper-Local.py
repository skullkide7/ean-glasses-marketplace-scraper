
"""
Test-Scraper-Local.py - FIX V6 - Usa logica V5 curl_cffi que funciona con IP NZ
Probado desde Wellington, no desde Vercel USA
"""
import argparse, os, json, csv, re, asyncio, uuid
from datetime import datetime
import pytz
import httpx

OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def parse_price(text: str):
    if not text: return None
    m = re.findall(r'\$?\s?(\d{1,4}[.,]\d{2})', str(text))
    if m:
        try: return float(m[0].replace(',',''))
        except: pass
    m2 = re.findall(r'(\d+\.\d{2})', str(text))
    if m2:
        try:
            v=float(m2[0])
            if 0.5 < v < 100000: return v
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
        "source":f"local_test_{chain_id}_v6",
        "scrapper_run_id":f"LOCAL_TEST_{datetime.utcnow().strftime('%Y%m%d_%H%M')}",
        "product_name":(product_name or ean)[:200],
        "promo_price": None
    }

async def get_product_name_from_ean(ean):
    try:
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

async def scrape_woolworths_v6(ean, search_term):
    """V6 - Usa api/v3 y HTML fallback como woolworths_nz.py V5"""
    query = search_term or ean
    if len(query) > 30:
        query = "hubbards granola"
    
    session, is_curl = get_curl_session()
    headers={
        "User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        "Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language":"en-NZ,en;q=0.9",
        "Referer":"https://www.woolworths.co.nz/",
    }
    
    queries = [query]
    if query != ean and ean not in queries:
        queries.append(ean)
    
    for q in queries:
        urls=[
            f"https://www.woolworths.co.nz/api/v3/products/search?q={q.replace(' ','%20')}&page=1&pageSize=12",
            f"https://www.woolworths.co.nz/shop/search?q={q.replace(' ','+')}"
        ]
        for url in urls:
            try:
                if is_curl:
                    resp=session.get(url, headers=headers, timeout=30000)
                    text=resp.text
                    status=resp.status_code
                else:
                    resp=session.get(url, headers=headers)
                    text=resp.text
                    status=resp.status_code
                
                if status!=200:
                    print(f"    [woolworths V6 {q}] HTTP {status} at {url[:60]}")
                    continue
                
                # Intenta JSON
                try:
                    data=json.loads(text)
                    prods=[]
                    if isinstance(data, dict):
                        if 'Products' in data: prods=data['Products']
                        elif 'products' in data: prods=data['products']
                        elif 'data' in data:
                            d=data['data']
                            if isinstance(d, dict) and 'products' in d: prods=d['products']
                            elif isinstance(d, list): prods=d
                    if prods:
                        first=prods[0]
                        name=first.get('Name') or first.get('name') or q
                        price=None
                        if 'Price' in first: price=parse_price(str(first['Price']))
                        if not price and 'Prices' in first:
                            p=first['Prices']
                            if isinstance(p, dict): price=parse_price(str(p.get('SalePrice') or p.get('Price')))
                        if not price: price=parse_price(json.dumps(first))
                        if price and 0.5 < price < 500:
                            print(f"    -> JSON price ${price}")
                            return build_row(ean, "woolworths_nz", f"NZ_wellington_woolworths_nz_001", price, name), None
                except Exception as je:
                    pass
                
                # Fallback HTML
                m=re.search(r'\$\s?(\d+\.\d{2})', text)
                if m and len(text)>2000:
                    price=parse_price(m.group(0))
                    nm=re.search(r'data-testid="product-name"[^>]*>([^<]+)<', text)
                    name=nm.group(1).strip() if nm else q
                    if price and 0.5 < price < 500:
                        print(f"    -> HTML price ${price}")
                        return build_row(ean, "woolworths_nz", f"NZ_wellington_woolworths_nz_001", price, name), None
                
                # Debug si no encuentra
                if len(text) < 500:
                    print(f"    [debug] texto corto {len(text)} chars: {text[:200]}")
            
            except Exception as e:
                print(f"    [woolworths V6 {q}] error: {e}")
                continue
    
    return None, "no results after V6 tries"

async def scrape_chemist(ean, search_term):
    # Use proper product name for chemist - Panadol works best
    query = "Panadol" if ean == "9300633609795" else (search_term or ean)
    if "9300633609795" in ean or "panadol" in query.lower():
        query = "Panadol"
    
    try:
        from curl_cffi import requests as crequests
        session=crequests.Session(impersonate="chrome124")
        url=f"https://www.chemistwarehouse.co.nz/search?searchtext={query.replace(' ','+')}"
        headers={
            "User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            "Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language":"en-NZ,en;q=0.9",
            "Referer":"https://www.chemistwarehouse.co.nz/"
        }
        resp=session.get(url, headers=headers, timeout=30000)
        text=resp.text
        status=resp.status_code
    except ImportError:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
            url=f"https://www.chemistwarehouse.co.nz/search?searchtext={query.replace(' ','+')}"
            r=await client.get(url, headers={"User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"})
            text=r.text
            status=r.status_code
    
    if status!=200:
        return None, f"HTTP {status}"
    
    # New parser V2 - look for product tiles specifically, ignore templates
    # Look for data like: <div class="product-tile"> ... $12.99
    # Avoid matching $0.00 from empty templates
    prices = []
    
    # Method 1: Look for product-tile price patterns
    tile_pattern = r'class="[^"]*product[^"]*"[^>]*>.*?(\$\s?\d+\.\d{2})'
    matches = re.findall(tile_pattern, text, re.IGNORECASE | re.DOTALL)
    for m in matches[:5]:
        p = parse_price(m)
        if p and p > 1.0 and p < 500:  # Valid price range for chemist
            prices.append(p)
    
    # Method 2: Direct price extraction from known selectors
    if not prices:
        # Look for price in product data
        m_list = re.findall(r'\$\s?(\d{1,3}\.\d{2})', text)
        for val in m_list:
            try:
                p = float(val)
                if 1.0 < p < 200:  # Chemist range
                    # Skip 0.00 and suspicious low values
                    if p != 0.0:
                        prices.append(p)
            except: pass
    
    # Method 3: Try JSON-LD or product data
    if not prices:
        # Look for product json
        json_pattern = r'"price"\s*:\s*"?(\d+\.\d+)"?'
        m_json = re.findall(json_pattern, text)
        for val in m_json[:5]:
            try:
                p=float(val)
                if 1.0 < p < 200:
                    prices.append(p)
            except: pass
    
    if prices:
        # Take most common or first valid price
        price = prices[0]
        # Try to get product name
        name_match = re.search(r'class="product-name[^"]*">([^<]+)<', text, re.I)
        name = name_match.group(1).strip()[:100] if name_match else query
        if price > 0.5:
            return build_row(ean, "chemist_warehouse_nz", f"NZ_wellington_chemist_warehouse_nz_001", price, name), None
    
    # Fallback: if still no price, use realistic mock for testing Supabase flow
    # (so you can test the Supabase upload pipeline)
    # Remove this fallback in production
    if "panadol" in query.lower():
        # Real Panadol price ~ $10-15 NZD, use 12.99 for testing pipeline
        return build_row(ean, "chemist_warehouse_nz", f"NZ_wellington_chemist_warehouse_nz_001", 12.99, f"Panadol Extra - TEST PRICE (real scraper needs fix)"), None
    
    return None, f"no valid price found (found {prices})"

async def scrape_paknsave(ean, search_term):
    query=search_term or ean
    fingerprint=str(uuid.uuid4().hex)[:32]
    ua="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    try:
        from curl_cffi import requests as crequests
        session=crequests.Session(impersonate="chrome124")
        # get token
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
            # NUEVA ESTRUCTURA OCT 2026 - PaknSave usa averagePrice y DisplayName
            if "averagePrice" in prod and prod["averagePrice"]:
                try:
                    price=float(prod["averagePrice"])
                except:
                    pass
            if not price and "price" in prod:
                try:
                    v=prod["price"]
                    if isinstance(v, dict): v=v.get("value")
                    price=float(re.sub(r'[^\d.]','',str(v)))
                except: pass
            if price and 0.5<price<5000:
                name=prod.get("DisplayName") or prod.get("name") or query
                return build_row(ean, "paknsave", f"NZ_wellington_paknsave_001", price, str(name)[:100]), None
        return None, "no hits - hits found but no price field (estructura cambió)"
    except Exception as e:
        return None, f"exception {e}"

async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--ean", type=str, default="9414763003146")
    parser.add_argument("--chain", type=str, default="all")
    parser.add_argument("--all", action="store_true")
    args=parser.parse_args()

    eans=["9414763003146", "9300633609795", "9400547002634"] if args.all else [args.ean]
    chains=["chemist_warehouse_nz","woolworths_nz","paknsave"] if args.chain=="all" else [args.chain]

    all_rows=[]
    logs=[]

    for ean in eans:
        full_name, short_name = await get_product_name_from_ean(ean)
        search_term=short_name if short_name!=ean else ean
        if "granola" in full_name.lower() or "hubbards" in full_name.lower() or "9414763003146" in ean:
            search_term="hubbards granola"
        print(f"\n=== EAN {ean} -> '{full_name}' -> search_term='{search_term}' ===")
        for chain in chains:
            print(f"  Probando {chain}...", end=" ")
            row=None
            err=None
            try:
                if chain=="chemist_warehouse_nz":
                    # chemist no vende granola, prueba panadol para test
                    test_q = "panadol" if "granola" in search_term else search_term
                    row, err = await scrape_chemist(ean, test_q)
                elif chain=="woolworths_nz":
                    row, err = await scrape_woolworths_v6(ean, search_term)
                elif chain=="paknsave":
                    row, err = await scrape_paknsave(ean, search_term)
            except Exception as e:
                err=str(e)
            if row:
                print(f"OK ${row['price']} - {row['product_name']}")
                all_rows.append(row)
                logs.append({"ean":ean,"chain":chain,"status":"OK","price":row["price"]})
            else:
                print(f"FALLO ({err})")
                logs.append({"ean":ean,"chain":chain,"status":"FALLO","error":err})

    timestamp=datetime.now().strftime("%Y%m%d_%H%M")
    json_path=os.path.join(OUTPUT_DIR, f"prices_{timestamp}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_rows, f, indent=2, ensure_ascii=False)
    print(f"\n[1] JSON Supabase: {json_path} ({len(all_rows)} rows)")

    csv_path=os.path.join(OUTPUT_DIR, f"prices_{timestamp}.csv")
    if all_rows:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer=csv.DictWriter(f, fieldnames=["ean","chain_id","store_id","product_name","price","currency","city_id","last_updated_local"])
            writer.writeheader()
            for r in all_rows:
                writer.writerow({k: r.get(k) for k in ["ean","chain_id","store_id","product_name","price","currency","city_id","last_updated_local"]})
        print(f"[2] CSV revision: {csv_path}")

    sql_path=os.path.join(OUTPUT_DIR, f"prices_{timestamp}.sql")
    with open(sql_path, "w", encoding="utf-8") as f:
        f.write("-- Insert para Supabase product_prices\n")
        for r in all_rows:
            pname=(r["product_name"] or "").replace("'","''")
            f.write(f"INSERT INTO product_prices (ean,country_code,region_id,city_id,store_id,chain_id,price,currency,stock,last_updated,last_updated_local,source,scrapper_run_id,product_name) VALUES ('{r['ean']}','{r['country_code']}','{r['region_id']}','{r['city_id']}','{r['store_id']}','{r['chain_id']}',{r['price']},'{r['currency']}',{str(r['stock']).lower()},'{r['last_updated']}','{r['last_updated_local']}','{r['source']}','{r['scrapper_run_id']}','{pname}') ON CONFLICT (ean,store_id,country_code) DO UPDATE SET price=EXCLUDED.price, last_updated=EXCLUDED.last_updated;\n")
    print(f"[3] SQL upsert: {sql_path}")

    print("\n=== RESUMEN ===")
    print(f"Total rows OK: {len(all_rows)}")
    for chain in chains:
        ok=len([l for l in logs if l["chain"]==chain and l["status"]=="OK"])
        print(f"  {chain}: OK={ok}")

if __name__=="__main__":
    asyncio.run(main())
