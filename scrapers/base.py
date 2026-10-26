"""
scrapers/base.py - MULTI-PAIS FIX
- Si no hay city_id -> city_id='ALL' (nacional)
- get_product_name_from_ean ahora devuelve query corta (2 palabras) para no bloquear Woolworths
"""
import os, re
from datetime import datetime
import pytz, httpx
from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

def get_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

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

async def get_product_name_from_ean(ean: str) -> str:
    # Para NZ usa EAN directo si es comida, si no 2 palabras max para no romper URL
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(f"https://world.openfoodfacts.org/api/v0/product/{ean}.json", headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code==200:
                prod=resp.json().get('product',{})
                name=prod.get('product_name') or prod.get('generic_name') or ''
                if name:
                    # solo 2 palabras para que URL no sea gigante (evita tu error CRISPY+CRUNCHY+...)
                    short=' '.join(name.split()[:2])
                    return short[:30] if short else ean
    except: pass
    return ean  # fallback EAN puro funciona mejor en Paknsave/Woolworths

def normalize_retailer_location(retailer: dict):
    country_code='NZ'
    if retailer.get('country_codes'):
        cc=retailer['country_codes']
        if isinstance(cc,list) and len(cc)>0: country_code=cc[0]
        elif isinstance(cc,str): country_code=cc.strip('{}').split(',')[0].strip()
    elif retailer.get('country_code'): country_code=retailer['country_code']
    city_id=retailer.get('city_id')
    if not city_id or str(city_id).strip()=='': city_id='ALL'
    region_id=retailer.get('region_id')
    if not region_id or str(region_id).strip()=='': region_id=f"{country_code}-ALL"
    store_id=retailer.get('store_id') or f"{country_code}_{city_id}_{retailer['id']}_001"
    tz_map={'NZ':'Pacific/Auckland','CL':'America/Santiago','US':'America/Los_Angeles'}
    timezone=retailer.get('timezone') or tz_map.get(country_code,'Pacific/Auckland')
    currency_map={'NZ':'NZD','CL':'CLP','US':'USD'}
    currency=retailer.get('currency') or currency_map.get(country_code,'NZD')
    return {'country_code':country_code,'city_id':city_id,'region_id':region_id,'store_id':store_id,'timezone':timezone,'currency':currency}

def build_row(ean, chain_id, store_id, price, product_name, country_code="NZ", region_id=None, city_id=None, promo_price=None, source=None, currency=None, timezone=None):
    if not city_id: city_id='ALL'
    if not region_id: region_id=f"{country_code}-ALL"
    if not currency:
        currency_map={'NZ':'NZD','CL':'CLP','US':'USD'}
        currency=currency_map.get(country_code,'NZD')
    if not timezone:
        tz_map={'NZ':'Pacific/Auckland','CL':'America/Santiago'}
        timezone=tz_map.get(country_code,'Pacific/Auckland')
    tz=pytz.timezone(timezone)
    now_local=datetime.now(tz)
    return {
        "ean":ean,"country_code":country_code,"region_id":region_id,"city_id":city_id,"store_id":store_id,"chain_id":chain_id,
        "price":price,"promo_price":promo_price,"currency":currency,"stock":True,
        "last_updated":datetime.utcnow().isoformat(),
        "last_updated_local":now_local.strftime("%Y-%m-%d %H:%M %Z"),
        "source":source or f"scraper_{chain_id}_{country_code.lower()}_v2",
        "scrapper_run_id":f"RUN_{datetime.utcnow().strftime('%Y%m%d_%H%M')}_{country_code}",
        "product_name":product_name[:200] if product_name else None,
    }
