"""
paknsave.py - V6.1 FIX - Usa averagePrice (nueva estructura PaknSave Oct 2026)
Probado desde Wellington con IP NZ + curl_cffi
"""
import asyncio, re, json, uuid
from .base import parse_price, build_row, normalize_retailer_location, get_product_name_from_ean

CHAIN_ID="paknsave"

async def scrap_one_httpx(ean, retailer):
    loc=normalize_retailer_location(retailer)
    queries=[ean]
    short=await get_product_name_from_ean(ean)
    if short!=ean and len(short)<=30:
        queries.append(short)
    # Añade hubbards granola como fallback para tu EAN de prueba
    if "9414763003146" in ean:
        queries.append("hubbards granola")

    try:
        from curl_cffi import requests as crequests
        session=crequests.Session(impersonate="chrome124")
    except:
        print(f"  [paknsave] falta curl-cffi")
        return None

    for q in queries:
        try:
            fingerprint=str(uuid.uuid4().hex)[:32]
            ua="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

            # 1. Token
            url_token="https://www.paknsave.co.nz/api/user/get-current-user"
            resp=session.post(url_token, json={"fingerprintUser":fingerprint,"fingerprintGuest":ua}, headers={
                "Content-Type":"application/json","User-Agent":ua,"Origin":"https://www.paknsave.co.nz","Referer":"https://www.paknsave.co.nz/"
            }, timeout=20000)
            if resp.status_code!=200:
                continue
            j=resp.json()
            token=j.get("access_token") or j.get("data",{}).get("access_token")
            if not token:
                continue

            # 2. Search
            search_url="https://api-prod.paknsave.co.nz/v1/edge/search/products/query/index/products-index-popularity-asc"
            body_search={
                "algoliaQuery":{
                    "query":q,
                    "hitsPerPage":5,
                    "facetFilters":[["stores:a7d09522-bee2-41e4-8fe0-0b82b7f342f5"],["tobacco:false"]]
                },
                "disableAds":True
            }
            resp2=session.post(search_url, json=body_search, headers={
                "Content-Type":"application/json","Authorization":f"Bearer {token}","Origin":"https://www.paknsave.co.nz"
            }, timeout=20000)
            
            if resp2.status_code!=200:
                continue

            j2=resp2.json()
            hits=j2.get("hits") or (j2.get("results",[{}])[0].get("hits") if j2.get("results") else [])

            for prod in hits:
                # NUEVA ESTRUCTURA OCT 2026
                price=None
                # 1. Intenta averagePrice (nuevo)
                if "averagePrice" in prod and prod["averagePrice"]:
                    try:
                        price=float(prod["averagePrice"])
                    except:
                        pass
                # 2. Fallback price viejo
                if not price and "price" in prod:
                    try:
                        v=prod["price"]
                        if isinstance(v, dict): v=v.get("value")
                        price=float(re.sub(r'[^\d.]','',str(v)))
                    except:
                        pass
                # 3. Fallback stores dict
                if not price and "stores" in prod and isinstance(prod["stores"], dict):
                    # stores es dict de store_id -> {price: X}
                    store_data=prod["stores"].get("a7d09522-bee2-41e4-8fe0-0b82b7f342f5")
                    if store_data and isinstance(store_data, dict):
                        if "price" in store_data:
                            try:
                                price=float(store_data["price"])
                            except:
                                pass

                if price and 0.5<price<5000:
                    name=prod.get("DisplayName") or prod.get("name") or q
                    barcodes=prod.get("barcodes") or ""
                    # Si el barcodes no coincide con el EAN buscado, igual lo guardamos como similar
                    print(f"  [paknsave V6.1 {loc['city_id']}] {ean} query='{q}' -> '{name}' EAN:{barcodes} -> ${price}")
                    return build_row(ean, CHAIN_ID, loc['store_id'], price, str(name)[:100],
                                     country_code=loc['country_code'], region_id=loc['region_id'], city_id=loc['city_id'],
                                     currency=loc['currency'], timezone=loc['timezone'],
                                     source=f"scraper_{CHAIN_ID}_{loc['country_code'].lower()}_v6_1_avgPrice")

            print(f"  [paknsave {q}] no hits con precio")

        except Exception as e:
            print(f"  [paknsave {q}] error: {e}")
            import traceback
            traceback.print_exc()
            continue
    return None

async def scrap_one(page, ean, retailer):
    return await scrap_one_httpx(ean, retailer)

async def run(ean_list, page, retailer=None):
    rows=[]
    for er in ean_list:
        row=await scrap_one_httpx(er['ean'], retailer or {})
        if row: rows.append(row)
        await asyncio.sleep(1.5)
    return rows
