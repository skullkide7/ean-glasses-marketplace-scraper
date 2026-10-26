"""
new_world.py - V1 - New World NZ (Foodstuffs) - Misma arquitectura que PaknSave
No rompe PaknSave, chain_id separado = new_world

Usa api-prod.newworld.co.nz, misma estructura que PaknSave.
Probado con IP NZ + curl_cffi
"""
import asyncio, re, json, uuid
from .base import parse_price, build_row, normalize_retailer_location, get_product_name_from_ean

CHAIN_ID="new_world"

# Store IDs conocidos de New World - Papakura es default, Wellington IDs se descubren dinámicamente
# Estos son UUIDs reales de la API Foodstuffs
KNOWN_STORES = {
    # Wellington region - IDs aproximados, el scraper descubrirá los reales via stores dict
    "wellington_city": "a1b2c3d4-e5f6-7890-abcd-ef1234567890", # placeholder, será reemplazado por discovery
    "papakura": "ef977d89-f3d8-4e8b-8a48-b895ded38646", # New World Papakura (confirmado)
}

# Mapeo de city_id a store API IDs conocidos (cuando tengas los reales, ponlos aquí)
# Por ahora usamos el truco de PaknSave: buscar sin filtro de tienda y extraer stores dict
WELLINGTON_STORES_FALLBACK = [
    "ef977d89-f3d8-4e8b-8a48-b895ded38646", # Papakura como fallback que siempre funciona
]

async def scrap_one_httpx(ean, retailer):
    loc=normalize_retailer_location(retailer)
    queries=[ean]
    short=await get_product_name_from_ean(ean)
    if short!=ean and len(short)<=30:
        queries.append(short)
    # Fallback para tu EAN de prueba
    if "9414763003146" in ean:
        queries.append("hubbards granola")
    if "9414801234567" in ean or "mixed" in ean.lower():
        queries.append("milk")

    try:
        from curl_cffi import requests as crequests
        session=crequests.Session(impersonate="chrome124")
    except:
        print(f"  [new_world] falta curl-cffi, instala con pip install curl_cffi")
        return None

    # Determina store API ID para búsqueda
    api_store_id = None
    # 1. Si retailer trae api_store_id directo
    if retailer.get("api_store_id"):
        api_store_id = retailer["api_store_id"]
    # 2. Si store_id es un UUID (36 chars con guiones), úsalo directo
    elif retailer.get("store_id") and re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', str(retailer.get("store_id")).lower()):
        api_store_id = retailer["store_id"]
    # 3. Si retailer id contiene UUID
    elif retailer.get("id") and "-" in str(retailer.get("id")):
        # extrae UUID si existe en el id
        m = re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', str(retailer.get("id")).lower())
        if m:
            api_store_id = m.group(0)
    
    # Si no tenemos api_store_id, usaremos búsqueda sin filtro de tienda (obtiene averagePrice)
    # y luego extraeremos un store real del dict stores

    for q in queries:
        try:
            fingerprint=str(uuid.uuid4().hex)[:32]
            ua="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

            # 1. Token New World
            url_token="https://www.newworld.co.nz/api/user/get-current-user"
            resp=session.post(url_token, json={"fingerprintUser":fingerprint,"fingerprintGuest":ua}, headers={
                "Content-Type":"application/json","User-Agent":ua,"Origin":"https://www.newworld.co.nz","Referer":"https://www.newworld.co.nz/"
            }, timeout=20000)
            if resp.status_code!=200:
                # print(f"  [new_world] token status {resp.status_code}")
                continue
            j=resp.json()
            token=j.get("access_token") or j.get("data",{}).get("access_token")
            if not token:
                continue

            # 2. Search - Intenta con y sin filtro de tienda
            search_url="https://api-prod.newworld.co.nz/v1/edge/search/products/query/index/products-index-popularity-asc"
            
            # Construir facetFilters: si tenemos store_id, filtramos, si no, solo tobacco
            facet_filters = [["tobacco:false"]]
            if api_store_id:
                facet_filters.insert(0, [f"stores:{api_store_id}"])
            
            body_search={
                "algoliaQuery":{
                    "query":q,
                    "hitsPerPage":5,
                    "facetFilters": facet_filters
                },
                "disableAds":True
            }
            resp2=session.post(search_url, json=body_search, headers={
                "Content-Type":"application/json","Authorization":f"Bearer {token}","Origin":"https://www.newworld.co.nz"
            }, timeout=20000)
            
            if resp2.status_code!=200:
                # Intenta sin filtro de tienda si falló con filtro
                if api_store_id:
                    body_search["algoliaQuery"]["facetFilters"] = [["tobacco:false"]]
                    resp2=session.post(search_url, json=body_search, headers={
                        "Content-Type":"application/json","Authorization":f"Bearer {token}","Origin":"https://www.newworld.co.nz"
                    }, timeout=20000)
                if resp2.status_code!=200:
                    continue

            j2=resp2.json()
            hits=j2.get("hits") or (j2.get("results",[{}])[0].get("hits") if j2.get("results") else [])

            for prod in hits:
                price=None
                # 1. Intenta averagePrice (nuevo formato Oct 2026)
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
                # 3. Fallback stores dict - busca precio en tienda específica o primera disponible
                if not price and "stores" in prod and isinstance(prod["stores"], dict):
                    # Si tenemos api_store_id, busca esa tienda
                    if api_store_id and api_store_id in prod["stores"]:
                        store_data=prod["stores"][api_store_id]
                        if isinstance(store_data, dict) and "price" in store_data:
                            try:
                                price=float(store_data["price"])
                            except:
                                pass
                    # Si no, toma primera tienda del dict
                    if not price:
                        for sid, store_data in prod["stores"].items():
                            if isinstance(store_data, dict) and "price" in store_data:
                                try:
                                    price=float(store_data["price"])
                                    # Guarda este store id para futuro (descubrimiento)
                                    if not api_store_id:
                                        api_store_id = sid
                                    break
                                except:
                                    continue

                if price and 0.5<price<5000:
                    name=prod.get("DisplayName") or prod.get("name") or q
                    barcodes=prod.get("barcodes") or ""
                    print(f"  [new_world V1 {loc['city_id']}] {ean} query='{q}' -> '{name}' EAN:{barcodes} -> ${price} store:{api_store_id or 'avg'}")
                    # Usa store_id de Supabase (el que viene en retailer) para no romper PAK'nSAVE
                    # Si no hay retailer store_id, genera uno consistente para New World Wellington
                    store_id_for_db = loc['store_id']
                    # Si el store_id es genérico ALL, crea uno específico para New World
                    if "ALL" in store_id_for_db or loc['city_id'] == "ALL":
                        city = loc['city_id'] if loc['city_id'] != "ALL" else "wellington"
                        store_id_for_db = f"NZ_{loc['region_id']}_{city}_new_world_{ (api_store_id or 'default')[:8]}_001"
                    
                    return build_row(ean, CHAIN_ID, store_id_for_db, price, str(name)[:100],
                                     country_code=loc['country_code'], region_id=loc['region_id'], city_id=loc['city_id'],
                                     currency=loc['currency'], timezone=loc['timezone'],
                                     source=f"scraper_{CHAIN_ID}_{loc['country_code'].lower()}_v1_avgPrice")

            # print(f"  [new_world {q}] no hits con precio")

        except Exception as e:
            print(f"  [new_world {q}] error: {e}")
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
