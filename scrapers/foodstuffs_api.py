"""
scrapers/foodstuffs_api.py - API compartida PAK'nSAVE + New World (ambos son Foodstuffs,
misma arquitectura: Next.js + Algolia vía api-prod.<domain>).

Resuelve, para una cadena dada:
  1. Tiendas reales (id, nombre, dirección, lat/lon) via /v1/edge/store
  2. Catálogo completo (EAN real + precio real por tienda) via partición
     recursiva por categorías, porque Algolia tiene tope de 1000 resultados
     por combinación de filtros (hitsPerPage max 50 x 20 páginas).
"""
import re, time, uuid
from curl_cffi import requests as crequests

CHAINS = {
    "paknsave": {
        "domain": "https://www.paknsave.co.nz",
        "api_base": "https://api-prod.paknsave.co.nz",
        "chain_name": "PAK'nSAVE",
    },
    "new_world": {
        "domain": "https://www.newworld.co.nz",
        "api_base": "https://api-prod.newworld.co.nz",
        "chain_name": "New World",
    },
}

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
SEARCH_INDEX = "products-index-popularity-asc"
MAX_HITS_PER_PAGE = 50
ALGOLIA_WINDOW_CAP = 1000  # tope duro de Algolia por combinación de filtros


def new_session():
    return crequests.Session(impersonate="chrome124")


def get_token(session, chain_id):
    cfg = CHAINS[chain_id]
    fingerprint = str(uuid.uuid4().hex)[:32]
    resp = session.post(
        f"{cfg['domain']}/api/user/get-current-user",
        json={"fingerprintUser": fingerprint, "fingerprintGuest": UA},
        headers={
            "Content-Type": "application/json", "User-Agent": UA,
            "Origin": cfg["domain"], "Referer": f"{cfg['domain']}/",
        },
        timeout=20,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"[{chain_id}] token HTTP {resp.status_code}")
    j = resp.json()
    token = j.get("access_token") or j.get("data", {}).get("access_token")
    if not token:
        raise RuntimeError(f"[{chain_id}] token no encontrado en respuesta: {j}")
    return token


def slugify(text):
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or "unknown"


def get_real_stores(session, token, chain_id):
    """Trae el directorio REAL de tiendas (nombre, dirección, lat/lon exactos)."""
    cfg = CHAINS[chain_id]
    resp = session.get(
        f"{cfg['api_base']}/v1/edge/store",
        headers={"Authorization": f"Bearer {token}", "Origin": cfg["domain"], "User-Agent": UA},
        timeout=20,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"[{chain_id}] /v1/edge/store HTTP {resp.status_code}: {resp.text[:200]}")
    stores_raw = resp.json().get("stores", [])

    stores = []
    for s in stores_raw:
        api_id = s.get("id")
        if not api_id:
            continue
        phys = s.get("physicalAddress") or {}
        city_name = phys.get("cityName") or "Unknown"
        region_name = phys.get("regionName") or "Unknown"
        city_id = slugify(city_name)
        region_id = f"NZ-{slugify(region_name)}"
        stores.append({
            "id": f"NZ_{chain_id}_{api_id}",
            "api_store_id": api_id,
            "chain_id": chain_id,
            "chain_name": cfg["chain_name"],
            "country_code": "NZ",
            "region_id": region_id,
            "city_id": city_id,
            "country_name": "New Zealand",
            "region_name": region_name,
            "city_name": city_name,
            "name": s.get("name") or f"{cfg['chain_name']} {api_id[:8]}",
            "address": s.get("address") or "",
            "lat": s.get("latitude"),
            "lon": s.get("longitude"),
            "category": "supermarket",
            "is_active": bool(s.get("onlineActive", True) and s.get("physicalActive", True)),
        })
    return stores


def _search(session, token, chain_id, query, facet_filters, page, hits_per_page=MAX_HITS_PER_PAGE, facets=None):
    cfg = CHAINS[chain_id]
    algolia_query = {
        "query": query, "hitsPerPage": hits_per_page, "page": page,
        "facetFilters": facet_filters,
    }
    if facets:
        algolia_query["facets"] = facets
    body = {"algoliaQuery": algolia_query, "disableAds": True}
    resp = session.post(
        f"{cfg['api_base']}/v1/edge/search/products/query/index/{SEARCH_INDEX}",
        json=body,
        headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {token}",
            "Origin": cfg["domain"], "User-Agent": UA,
        },
        timeout=20,
    )
    if resp.status_code != 200:
        return None
    return resp.json()


def _facet_counts(session, token, chain_id, facet_name, base_filters):
    j = _search(session, token, chain_id, "", base_filters, page=0, hits_per_page=1, facets=[facet_name])
    if not j:
        return {}
    return j.get("facets", {}).get(facet_name, {}) or {}


def crawl_catalog(session, token, chain_id, sleep_between=0.2, log=print):
    """
    Recorre TODO el catálogo sin que el usuario cargue EANs.
    Algolia limita cada combinación de filtros a 1000 resultados, así que
    particiona recursivamente por category0 -> category1 -> category2
    hasta que cada hoja tenga <=1000 productos, y pagina esa hoja completa.
    Devuelve dict ean_del_producto_unico -> hit (deduplicado por product id).
    """
    base_filters = [["tobacco:false"]]
    seen = {}

    def paginate_leaf(filters, label):
        page = 0
        while True:
            j = _search(session, token, chain_id, "", filters, page=page)
            if not j:
                break
            hits = j.get("hits") or []
            if not hits:
                break
            for prod in hits:
                # "productID" (mayúscula ID) es el campo real confirmado en la API;
                # NO usar DisplayName como fallback de identidad: productos distintos
                # (ej. distinto tamaño de paquete) pueden compartir el mismo nombre.
                key = prod.get("productID") or prod.get("objectID")
                if key is not None:
                    seen[key] = prod
            log(f"  [{chain_id}] {label} page {page}: {len(hits)} hits (total único: {len(seen)})")
            if len(hits) < MAX_HITS_PER_PAGE:
                break
            page += 1
            if page * MAX_HITS_PER_PAGE >= ALGOLIA_WINDOW_CAP:
                log(f"  [{chain_id}] {label}: tope de ventana Algolia alcanzado, puede faltar partir más")
                break
            time.sleep(sleep_between)

    def recurse(level, filters, label):
        facet_name = ["category0", "category1", "category2"][level] if level < 3 else None
        counts = _facet_counts(session, token, chain_id, facet_name, filters) if facet_name else {}
        if not counts:
            # no se pudo facetar más (llegamos al fondo o la API no devolvió facets) -> pagina lo que hay
            paginate_leaf(filters, label)
            return
        for value, count in counts.items():
            sub_filters = filters + [[f"{facet_name}:{value}"]]
            sub_label = f"{label}/{value}({count})"
            if count <= ALGOLIA_WINDOW_CAP:
                paginate_leaf(sub_filters, sub_label)
            else:
                recurse(level + 1, sub_filters, sub_label)

    recurse(0, base_filters, "root")
    return seen


def extract_ean(prod):
    barcodes = prod.get("barcodes") or prod.get("barcode") or prod.get("ean") or []
    candidates = []
    if isinstance(barcodes, list):
        candidates = barcodes
    elif isinstance(barcodes, str):
        candidates = re.findall(r"\d{8,14}", barcodes) or [barcodes]
    elif isinstance(barcodes, dict):
        candidates = list(barcodes.values())
    for bc in candidates:
        digits = re.sub(r"\D", "", str(bc))
        if len(digits) == 13 and digits != "0000000000000":
            return digits
        if len(digits) == 8:
            return digits
    return None


def extract_store_prices(prod):
    """
    OBSOLETO desde oct-2026: prod["stores"] ahora es solo una LISTA de UUIDs de
    disponibilidad (qué tiendas tienen el producto), no un dict con precio por tienda.
    El precio real por tienda viene de decorate_products_for_store() más abajo.
    Se deja esta función por compatibilidad pero normalmente no encontrará nada.
    """
    stores_raw = prod.get("stores")
    result = []
    if isinstance(stores_raw, dict):
        for api_id, data in stores_raw.items():
            if not isinstance(data, dict):
                continue
            price = data.get("price") or data.get("Price")
            if price is None:
                continue
            try:
                price = float(price)
            except (TypeError, ValueError):
                continue
            promo = data.get("promoPrice") or data.get("promo_price")
            try:
                promo = float(promo) if promo else None
            except (TypeError, ValueError):
                promo = None
            in_stock = data.get("inStock", True)
            result.append((api_id, price, promo, bool(in_stock) if isinstance(in_stock, bool) else True))
    return result


def get_available_store_ids(prod):
    """Lista de UUIDs de tiendas donde el producto está disponible (confirmado real)."""
    stores_raw = prod.get("stores") or prod.get("inStoreAvailable")
    if isinstance(stores_raw, list):
        return [s for s in stores_raw if isinstance(s, str)]
    if isinstance(stores_raw, dict):
        return list(stores_raw.keys())
    return []


def decorate_products_for_store(session, chain_id, store_id, product_ids, get_fresh_token, batch_size=200, sleep_between=0.3, log=print):
    """
    EL precio real por tienda. Confirmado con pruebas en vivo: el mismo producto
    cuesta distinto en distintas tiendas de la misma cadena (ej. Brócoli $1.89 en
    Auckland vs $2.99 en Invercargill) - esto es lo que replica exactamente lo que
    hace el sitio cuando un comprador elige su tienda y ve el catálogo.

    El token expira a los ~30 min (confirmado: "expires_time" en get-current-user es
    exactamente 30 min después de "current_time"), y un catálogo completo tiene miles
    de lotes, así que puede expirar a mitad de una tienda. get_fresh_token es una
    función sin argumentos que pide un token nuevo; se llama automáticamente si un
    lote responde 401/403.

    Devuelve dict productId -> {"price": float, "name": str, "available": bool}
    (price en dólares, ya convertido desde centavos).
    """
    cfg = CHAINS[chain_id]
    out = {}
    ids = list(product_ids)
    token = get_fresh_token()
    for i in range(0, len(ids), batch_size):
        batch = ids[i:i + batch_size]
        for attempt in range(2):
            resp = session.post(
                f"{cfg['api_base']}/v1/edge/store/{store_id}/decorateProducts",
                json={"productIds": batch},
                headers={
                    "Content-Type": "application/json", "Authorization": f"Bearer {token}",
                    "Origin": cfg["domain"], "User-Agent": UA,
                },
                timeout=30,
            )
            if resp.status_code in (401, 403) and attempt == 0:
                log(f"  [{chain_id}] token vencido a mitad de corrida, renovando...")
                token = get_fresh_token()
                continue
            break
        if resp.status_code != 200:
            log(f"  [{chain_id}] decorateProducts HTTP {resp.status_code} (lote {i}-{i+len(batch)}): {resp.text[:150]}")
            continue
        for p in resp.json().get("products", []):
            sp = p.get("singlePrice")
            if not sp or "price" not in sp:
                continue
            out[p["productId"]] = {
                "price": sp["price"] / 100.0,
                "name": p.get("name"),
                "promo": bool(p.get("onPromotion")),
            }
        time.sleep(sleep_between)
    return out
