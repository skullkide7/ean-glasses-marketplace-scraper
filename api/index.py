from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
import os
from supabase import create_client

app = FastAPI()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

def get_supabase():
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    return create_client(SUPABASE_URL, SUPABASE_KEY)

@app.get("/")
async def root():
    return {
        "status":"ok",
        "message":"Price Engine NZ - READ ONLY from Supabase. Scraper corre local en Mac NZ (sin proxy), Vercel solo lee Supabase.",
        "architecture":"Mac NZ (scraper) -> Supabase product_prices -> Vercel (API) -> iPhone",
        "proxy_needed": False
    }

@app.get("/api/test")
async def test_chain(chain: str = Query(...), ean: str = Query("9414763003146")):
    supabase=get_supabase()
    if not supabase:
        return JSONResponse({"error":"SUPABASE no configurado"}, status_code=500)
    try:
        res=supabase.table("product_prices").select("*").eq("ean", ean).eq("chain_id", chain).order("last_updated", desc=True).limit(5).execute()
        rows=res.data or []
        return {
            "success": True,
            "chain": chain,
            "ean": ean,
            "rows": len(rows),
            "sample": rows[:3],
            "source":"supabase_read_only",
            "message":"Si rows=0, corre ./run_scraper_local_nz.sh en tu Mac NZ"
        }
    except Exception as e:
        import traceback
        return JSONResponse({"success": False, "error": str(e), "trace": traceback.format_exc()}, status_code=500)

@app.get("/api/index")
@app.get("/api/scrape")
async def scrape():
    # Ya NO scrapea en Vercel USA (bloqueado). Solo lee lo que tu Mac NZ ya subio a Supabase
    supabase=get_supabase()
    if not supabase:
        return JSONResponse({"error":"SUPABASE_URL / SERVICE_KEY no set"}, status_code=500)
    try:
        res=supabase.table("product_prices").select("ean,chain_id,product_name,price,city_id,last_updated").order("last_updated", desc=True).limit(20).execute()
        rows=res.data or []
        return {
            "success": True,
            "rows": len(rows),
            "sample": rows[:10],
            "message":"Datos vienen de Supabase, scraper debe correr local en tu Mac NZ: ./run_scraper_local_nz.sh",
            "how_to_run_local":"python scrapper_orchestrator.py  (desde tu Mac en Wellington, IP NZ, sin proxy)"
        }
    except Exception as e:
        import traceback
        return JSONResponse({"success": False, "error": str(e), "trace": traceback.format_exc()}, status_code=500)
