"""
woolworths_nz.py - V5 curl_cffi BYPASS Cloudflare + Woolworths API
"""
import asyncio, re, json
from .base import parse_price, build_row, normalize_retailer_location, get_product_name_from_ean

CHAIN_ID="woolworths_nz"

async def scrap_one_httpx(ean, retailer):
    loc=normalize_retailer_location(retailer)
    queries=[ean]
    short=await get_product_name_from_ean(ean)
    if short!=ean: queries.append(short)

    try:
        from curl_cffi import requests as crequests
        session=crequests.Session(impersonate="chrome124")
        is_curl=True
    except:
        import httpx
        session=httpx.Client(follow_redirects=True, timeout=20)
        is_curl=False

    headers={
        "User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        "Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language":"en-NZ,en;q=0.9",
        "Referer":"https://www.woolworths.co.nz/",
    }

    for q in queries:
        # Woolworths front search
        url=f"https://www.woolworths.co.nz/shop/search?q={q.replace(' ','+')}"
        api_urls=[
            f"https://www.woolworths.co.nz/api/v3/products/search?q={q.replace(' ','%20')}&page=1&pageSize=12",
            url
        ]
        for u in api_urls:
            try:
                if is_curl:
                    resp=session.get(u, headers=headers, timeout=20000)
                    text=resp.text
                    status=resp.status_code
                else:
                    resp=session.get(u, headers=headers)
                    text=resp.text
                    status=resp.status_code

                if status!=200:
                    print(f"  [woolworths V5 {q}] HTTP {status} at {u[:50]}")
                    continue

                # Intenta JSON primero
                price=None
                name=q
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
                        if 'Price' in first: price=parse_price(str(first['Price']))
                        if not price and 'Prices' in first:
                            p=first['Prices']
                            if isinstance(p, dict): price=parse_price(str(p.get('SalePrice') or p.get('Price')))
                        if not price: price=parse_price(json.dumps(first))
                        if price:
                            print(f"  [woolworths V5 API {loc['country_code']}/{loc['city_id']}] {ean} ({q}) -> ${price}")
                            return build_row(ean, CHAIN_ID, loc['store_id'], price, name,
                                             country_code=loc['country_code'], region_id=loc['region_id'], city_id=loc['city_id'],
                                             currency=loc['currency'], timezone=loc['timezone'],
                                             source=f"scraper_{CHAIN_ID}_{loc['country_code'].lower()}_v5_api")
                except:
                    pass

                # Fallback HTML
                m=re.search(r'\$\s?(\d+\.\d{2})', text)
                if m and len(text)>2000:
                    price=parse_price(m.group(0))
                    nm=re.search(r'data-testid="product-name"[^>]*>([^<]+)<', text)
                    if nm: name=nm.group(1).strip()
                    if price and price>0.5 and price<500:
                        print(f"  [woolworths V5 HTML {loc['country_code']}/{loc['city_id']}] {ean} -> ${price} {'CURL' if is_curl else ''}")
                        return build_row(ean, CHAIN_ID, loc['store_id'], price, name,
                                         country_code=loc['country_code'], region_id=loc['region_id'], city_id=loc['city_id'],
                                         currency=loc['currency'], timezone=loc['timezone'],
                                         source=f"scraper_{CHAIN_ID}_{loc['country_code'].lower()}_v5_html")

            except Exception as e:
                print(f"  [woolworths V5 {q}] error: {e}")
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
