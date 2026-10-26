"""
Debug PaknSave - prueba sin filtro de tienda y con varias queries
"""
import asyncio, json, re, uuid

async def test_paknsave():
    try:
        from curl_cffi import requests as crequests
        session = crequests.Session(impersonate="chrome124")
    except:
        print("Instala: pip3 install curl-cffi")
        return

    fingerprint = str(uuid.uuid4().hex)[:32]
    ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    
    print("1. Sacando token...")
    url_token = "https://www.paknsave.co.nz/api/user/get-current-user"
    body = {"fingerprintUser": fingerprint, "fingerprintGuest": ua}
    resp = session.post(url_token, json=body, headers={
        "Content-Type":"application/json",
        "User-Agent":ua,
        "Origin":"https://www.paknsave.co.nz",
        "Referer":"https://www.paknsave.co.nz/"
    }, timeout=20000)
    print(f"   Token status: {resp.status_code}")
    if resp.status_code != 200:
        print(resp.text[:500])
        return
    j = resp.json()
    token = j.get("access_token") or j.get("data",{}).get("access_token")
    print(f"   Token OK: {token[:20]}...")

    queries = ["hubbards granola", "hubbards", "granola", "9414763003146"]
    
    for q in queries:
        print(f"\n--- Probando query: '{q}' ---")
        
        # Test A: CON filtro de tienda Wellington (el viejo)
        print("  A) Con filtro tienda a7d09522...")
        body_search = {
            "algoliaQuery":{
                "query": q,
                "hitsPerPage":5,
                "facetFilters":[["stores:a7d09522-bee2-41e4-8fe0-0b82b7f342f5"],["tobacco:false"]]
            },
            "disableAds": True
        }
        resp2 = session.post(
            "https://api-prod.paknsave.co.nz/v1/edge/search/products/query/index/products-index-popularity-asc",
            json=body_search,
            headers={"Content-Type":"application/json","Authorization":f"Bearer {token}","Origin":"https://www.paknsave.co.nz"},
            timeout=20000
        )
        print(f"     Status: {resp2.status_code}")
        if resp2.status_code == 200:
            j2 = resp2.json()
            hits = j2.get("hits") or (j2.get("results",[{}])[0].get("hits") if j2.get("results") else [])
            print(f"     Hits: {len(hits)}")
            if hits:
                for h in hits[:2]:
                    print(f"       - {h.get('name')} | price: {h.get('price')} | {h.get('ean')}")
        
        # Test B: SIN filtro de tienda (prueba nacional)
        print("  B) SIN filtro de tienda...")
        body_search2 = {
            "algoliaQuery":{
                "query": q,
                "hitsPerPage":5,
            },
            "disableAds": True
        }
        resp3 = session.post(
            "https://api-prod.paknsave.co.nz/v1/edge/search/products/query/index/products-index-popularity-asc",
            json=body_search2,
            headers={"Content-Type":"application/json","Authorization":f"Bearer {token}","Origin":"https://www.paknsave.co.nz"},
            timeout=20000
        )
        print(f"     Status: {resp3.status_code}")
        if resp3.status_code == 200:
            j3 = resp3.json()
            hits3 = j3.get("hits") or (j3.get("results",[{}])[0].get("hits") if j3.get("results") else [])
            print(f"     Hits: {len(hits3)}")
            if hits3:
                for h in hits3[:2]:
                    print(f"       - {h.get('name')} | price: {h.get('price')} | {h.get('ean')}")
            else:
                # Debug: muestra keys
                print(f"     Respuesta keys: {list(j3.keys())[:10]}")
                print(f"     Raw preview: {str(j3)[:500]}")

if __name__ == "__main__":
    asyncio.run(test_paknsave())
