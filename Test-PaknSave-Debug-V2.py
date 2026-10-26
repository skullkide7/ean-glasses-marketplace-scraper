"""
Debug PaknSave V2 - imprime JSON crudo para ver estructura real
"""
import asyncio, json, uuid

async def test():
    from curl_cffi import requests as crequests
    session = crequests.Session(impersonate="chrome124")
    
    fingerprint = str(uuid.uuid4().hex)[:32]
    ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    
    print("Sacando token...")
    resp = session.post(
        "https://www.paknsave.co.nz/api/user/get-current-user",
        json={"fingerprintUser": fingerprint, "fingerprintGuest": ua},
        headers={"Content-Type":"application/json","User-Agent":ua,"Origin":"https://www.paknsave.co.nz","Referer":"https://www.paknsave.co.nz/"},
        timeout=20000
    )
    token = resp.json().get("access_token") or resp.json().get("data",{}).get("access_token")
    print(f"Token OK\n")

    query = "hubbards granola"
    body = {
        "algoliaQuery":{"query": query, "hitsPerPage": 1, "facetFilters":[["stores:a7d09522-bee2-41e4-8fe0-0b82b7f342f5"],["tobacco:false"]]},
        "disableAds": True
    }
    resp2 = session.post(
        "https://api-prod.paknsave.co.nz/v1/edge/search/products/query/index/products-index-popularity-asc",
        json=body,
        headers={"Content-Type":"application/json","Authorization":f"Bearer {token}","Origin":"https://www.paknsave.co.nz"},
        timeout=20000
    )
    j2 = resp2.json()
    hits = j2.get("hits") or (j2.get("results",[{}])[0].get("hits") if j2.get("results") else [])
    
    print(f"Hits encontrados: {len(hits)}")
    if hits:
        first = hits[0]
        print("\n=== PRIMER HIT - KEYS ===")
        print(list(first.keys()))
        print("\n=== PRIMER HIT - JSON COMPLETO (primeros 2000 chars) ===")
        print(json.dumps(first, indent=2)[:3000])
        
        print("\n=== BUSCANDO PRECIO EN TODO EL HIT ===")
        text = json.dumps(first)
        import re
        prices = re.findall(r'\d+\.\d{2}', text)
        print(f"Numeros que parecen precio: {prices[:20]}")
        
        # Busca campos que suenan a precio
        for k in first.keys():
            if 'price' in k.lower() or 'sale' in k.lower() or 'amount' in k.lower():
                print(f"  Key precio-like: {k} = {first[k]}")

if __name__ == "__main__":
    asyncio.run(test())
