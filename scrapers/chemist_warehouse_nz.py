import asyncio
from .base import parse_price, get_product_name_from_ean, build_row, normalize_retailer_location
CHAIN_ID="chemist_warehouse_nz"
SEARCH_TEMPLATE="https://www.chemistwarehouse.co.nz/search?searchtext={query}"
async def scrap_one(page, ean, retailer):
    loc=normalize_retailer_location(retailer)
    queries=[ean]
    short=await get_product_name_from_ean(ean)
    if short!=ean: queries.append(short)
    for query in queries:
        url=SEARCH_TEMPLATE.format(query=query.replace(' ','+').replace(' ','-') if 'chemist_warehouse_nz'=='briscoes' else query.replace(' ','+'))
        # briscoes uses dash, others +
        if CHAIN_ID=='briscoes':
            url=SEARCH_TEMPLATE.format(query=query.replace(' ','-'))
        else:
            url=SEARCH_TEMPLATE.format(query=query.replace(' ','+'))
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(3500)
            try:
                await page.evaluate("window.scrollBy(0,200)")
            except: pass
            result=await page.evaluate('''() => {
                const sel=['[data-testid="product-tile"]','.product-tile','.productTileWrapper','[class*="ProductTile"]','.product-tile','.product','[data-testid="product"]'];
                let tile=null;
                for(const s of sel){ tile=document.querySelector(s); if(tile) break; }
                if(!tile) return {found:false};
                const name=tile.querySelector('h3, [data-testid="product-name"], .product-name, a')?.innerText||'';
                const priceText=tile.innerText.match(/\$\s?\d+\.\d{2}/)?.[0]||tile.innerText.match(/\$\d+/)?.[0]||'';
                return {found:true, name, priceText};
            }''')
            if not result.get('found'): continue
            price=parse_price(result.get('priceText',''))
            name=result.get('name')
            if not price: continue
            print(f"  [chemist_warehouse_nz {loc['country_code']}/{loc['city_id']}] {ean} ({query}) -> ${price}")
            return build_row(ean, CHAIN_ID, loc['store_id'], price, name or query,
                             country_code=loc['country_code'], region_id=loc['region_id'], city_id=loc['city_id'],
                             currency=loc['currency'], timezone=loc['timezone'],
                             source=f"scraper_{CHAIN_ID}_{loc['country_code'].lower()}_v3")
        except Exception as e:
            # execution context destroyed -> page reloaded, retry with next query
            if "Execution context was destroyed" in str(e):
                await page.wait_for_timeout(1500)
            print(f"  [chemist_warehouse_nz] {query} error {ean}: {e}")
            continue
    return None

async def run(ean_list, page, retailer=None):
    rows=[]
    for er in ean_list:
        row=await scrap_one(page, er['ean'], retailer or {})
        if row: rows.append(row)
        await asyncio.sleep(1.2)
    return rows
