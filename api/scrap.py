"""
api/scrape.py - Vercel Python Serverless + Cron
Funciona desde Vercel con proxy residencial para Pak'nSave/Woolworths
Si no hay proxy, funciona igual para Chemist Warehouse (que no bloquea)

Deploy:
1. En Vercel dashboard -> Settings -> Environment Variables:
   SUPABASE_URL, SUPABASE_SERVICE_KEY, PROXY_URL (opcional, ej: http://brd-customer-xxx:pass@brd.superproxy.io:22225)

2. vercel.json ya tiene cron: corre cada 6 horas

Endpoint: GET https://tu-app.vercel.app/api/scrape
"""

import os, re, json, asyncio
from datetime import datetime
import pytz
import httpx
from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
PROXY_URL = os.getenv("PROXY_URL")  # opcional: http://user:pass@host:port o Bright Data

def parse_price(text):
    if not text: return None
    m = re.findall(r'\$?\s?(\d{1,4}[.,]\d{2})', str(text))
    if m:
        try: return float(m[0].replace(',',''))
        except: pass
    return None

def get_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

async def get_product_name(ean):
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"https://world.openfoodfacts.org/api/v0/product/{ean}.json", headers={"User-Agent":"Mozilla/5.0"})
            if r.status_code==200:
                p=r.json().get('product',{})
                name=p.get('product_name') or p.get('generic_name') or ''
                if name: return ' '.join(name.split()[:2])[:30]
    except: pass
    return ean

def build_row(ean, chain_id, store_id, price, product_name, country_code="NZ", city_id="ALL"):
    tz=pytz.timezone('Pacific/Auckland')
    now_local=datetime.now(tz)
    return {
        "ean":ean,"country_code":country_code,"region_id":f"{country_code}-ALL","city_id":city_id,
        "store_id":store_id,"chain_id":chain_id,"price":price,"currency":"NZD","stock":True,
        "last_updated":datetime.utcnow().isoformat(),
        "last_updated_local":now_local.strftime("%Y-%m-%d %H:%M %Z"),
        "source":f"vercel_{chain_id}_{country_code.lower()}_v6",
        "scrapper_run_id":f"VERCEL_{datetime.utcnow().strftime('%Y%m%d_%H%M')}_{country_code}",
        "product_name":product_name[:200] if product_name else None,
    }

async def scrap_with_curl_cffi(url, proxy=None):
    """Intenta con curl_cffi (bypass Cloudflare), fallback httpx"""
    try:
        from curl_cffi import requests as crequests
        session=crequests.Session(impersonate="chrome124")
        proxies={"http": proxy, "https": proxy} if proxy else None
        resp=session.get(url, timeout=20000, proxies=proxies) if proxies else session.get(url, timeout=20000)
        return resp.text, resp.status_code, True
    except ImportError:
        # fallback httpx
        try:
            client_kwargs={"follow_redirects":True, "timeout":20}
            if proxy:
                client_kwargs["proxies"]=proxy
            async with httpx.AsyncClient(**client_kwargs) as client:
                r=await client.get(url, headers={
                    "User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
                    "Accept-Language":"en-NZ,en;q=0.9",
                })
                return r.text, r.status_code, False
        except Exception as e:
            return str(e), 0, False
    except Exception as e:
        return str(e), 0, True

async def scrap_retailer(chain_id, eans, retailer):
    rows=[]
    city_id=retailer.get('city_id') or 'wellington'
    store_id=retailer.get('store_id') or f"NZ_{city_id}_{chain_id}_001"

    for er in eans:
        ean=er['ean']
        query=await get_product_name(ean)

        # URLs según chain
        if chain_id=='paknsave':
            urls=[f"https://www.paknsave.co.nz/shop/search?q={ean}"]
        elif chain_id=='woolworths_nz':
            urls=[f"https://www.woolworths.co.nz/shop/search?q={ean}", f"https://www.woolworths.co.nz/shop/Search?q={ean}"]
        elif chain_id=='chemist_warehouse_nz':
            urls=[f"https://www.chemistwarehouse.co.nz/search?searchtext={ean}"]
        else:
            urls=[f"https://www.{chain_id}.co.nz/search?q={ean}"]

        for url in urls:
            text, status, is_curl = await scrap_with_curl_cffi(url, PROXY_URL)
            if status!=200:
                print(f"[{chain_id}] {ean} HTTP {status} {'CURL' if is_curl else 'HTTPX'} {url[:40]} proxy={bool(PROXY_URL)}")
                continue
            m=re.search(r'\$\s?(\d+\.\d{2})', text)
            if m and len(text)>1000:
                price=parse_price(m.group(0))
                if price and price>0.5:
                    nm=re.search(r'data-testid="product-name"[^>]*>([^<]+)<', text)
                    name=nm.group(1).strip() if nm else query
                    print(f"[{chain_id} {city_id}] {ean} -> ${price} {'CURL' if is_curl else ''} proxy={bool(PROXY_URL)}")
                    rows.append(build_row(ean, chain_id, store_id, price, name, city_id=city_id))
                    break
        await asyncio.sleep(1.0)
    return rows

# Vercel handler (Python serverless)
async def handler(request):
    try:
        supabase=get_supabase()
        # EANs NZ
        try:
            ean_res=supabase.table("top_eans").select("ean,country_code").eq("country_code","NZ").limit(5).execute()
            eans=ean_res.data or []
        except:
            eans=[{"ean":"9414763003146"},{"ean":"9414954110143"},{"ean":"9300633609795"}]

        # retailers
        res=supabase.table("retailer_chains").select("*").eq("is_active", True).execute()
        retailers=[r for r in (res.data or []) if 'NZ' in str(r.get('country_codes','')) or r.get('country_code')=='NZ']

        all_rows=[]
        for ret in retailers[:6]:  # limita a 6 para no timeout en Vercel (10s max en hobby, 60s en pro)
            rows=await scrap_retailer(ret['id'], eans, ret)
            all_rows.extend(rows)

        if all_rows:
            # upsert
            clean=[]
            for r in all_rows:
                clean.append({k: r[k] for k in ["ean","country_code","region_id","city_id","store_id","chain_id","price","currency","stock","last_updated","last_updated_local","source","scrapper_run_id","product_name"] if k in r})
            for i in range(0,len(clean),200):
                supabase.table("product_prices").upsert(clean[i:i+200], on_conflict="ean,store_id,country_code").execute()

        return {
            "statusCode":200,
            "body": json.dumps({"success":True, "rows":len(all_rows), "proxy":bool(PROXY_URL), "retailers":len(retailers), "sample":all_rows[:3]})
        }
    except Exception as e:
        return {"statusCode":500,"body": json.dumps({"error":str(e)})}

# Para vercel dev local
if __name__=="__main__":
    import asyncio
    async def local():
        class Req: pass
        res=await handler(Req())
        print(res)
    asyncio.run(local())
