"""
Pipeline de coleta — Comparador de Preços
Crawl por categoria (árvore VTEX) + persistência PostgreSQL.ee

Uso:
    python3 pipeline.py                        # coleta tudo
    python3 pipeline.py --limit-categories 3   # POC: só 3 categorias por mercado
"""
import argparse
import re
import time
import os
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
import requests

# Ler DATABASE_URL da env var (GitHub Actions injeta automaticamente)
DSN = os.environ.get("DATABASE_URL", "host=localhost dbname=comparador user=app password=app")
HEADERS = {"User-Agent": "Mozilla/5.0 (comparador-poc)"}
PAGE_SIZE = 50
DELAY = 0.4

RETAILERS = {
    "bistek":   {"name": "Bistek",   "base": "https://www.bistek.com.br",         "sc": None},
    "giassi":   {"name": "Giassi",   "base": "https://www.giassi.com.br",         "sc": "1"},
    "angeloni": {"name": "Angeloni", "base": "https://www.angeloni.com.br/super", "sc": None},
}

# ---------------------------------------------------------------- normalização

UNIT_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(kg|g|l|ml|un|unidades?)\b", re.IGNORECASE
)

def parse_quantity(name: str):
    """Extrai (quantidade, unidade) do nome. Ex: 'Arroz 5kg' -> (5, 'kg')."""
    m = UNIT_RE.search(name or "")
    if not m:
        return None, None
    qty = float(m.group(1).replace(",", "."))
    unit = m.group(2).lower()
    if unit.startswith("un"):
        unit = "un"
    return qty, unit


def valid_ean(ean: str) -> bool:
    return bool(ean) and ean.isdigit() and len(ean) in (8, 12, 13, 14)

# ---------------------------------------------------------------- API VTEX

def get_categories(base: str) -> list[dict]:
    """Árvore de categorias nível 1 (departamentos)."""
    r = requests.get(f"{base}/api/catalog_system/pub/category/tree/1",
                     headers=HEADERS, timeout=20)
    r.raise_for_status()
    return [{"id": c["id"], "name": c["name"]} for c in r.json()]


def crawl_category(base: str, cat_id: int, sc: str | None):
    """Itera produtos de uma categoria com paginação.
    VTEX limita _from a 2500; categorias maiores exigiriam subcategorias."""
    offset = 0
    while offset < 2500:
        url = (f"{base}/api/catalog_system/pub/products/search/"
               f"?fq=C:{cat_id}&_from={offset}&_to={offset + PAGE_SIZE - 1}")
        if sc:
            url += f"&sc={sc}"
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code not in (200, 206):
            return
        page = r.json()
        if not page:
            return
        yield from page
        if len(page) < PAGE_SIZE:
            return
        offset += PAGE_SIZE
        time.sleep(DELAY)

# ---------------------------------------------------------------- persistência

def upsert_store(cur, slug: str) -> int:
    cfg = RETAILERS[slug]
    cur.execute("""
        INSERT INTO retailer (slug, name, platform, base_url, scraper_config)
        VALUES (%s, %s, 'vtex', %s, %s)
        ON CONFLICT (slug) DO UPDATE SET base_url = EXCLUDED.base_url
        RETURNING id
    """, (slug, cfg["name"], cfg["base"],
          psycopg2.extras.Json({"sc": cfg["sc"]})))
    retailer_id = cur.fetchone()[0]
    # MVP: 1 "loja" lógica por rede = o e-commerce regional
    cur.execute("""
        INSERT INTO store (retailer_id, external_id, name, city)
        VALUES (%s, 'ecommerce', %s, 'Blumenau')
        ON CONFLICT (retailer_id, external_id) DO UPDATE SET name = EXCLUDED.name
        RETURNING id
    """, (retailer_id, f"{cfg['name']} Online"))
    return cur.fetchone()[0]


def upsert_product(cur, ean, name, brand, category) -> int | None:
    """Produto canônico: chave = EAN. Sem EAN válido -> sem matching no MVP."""
    if not valid_ean(ean):
        return None
    qty, unit = parse_quantity(name)
    cur.execute("""
        INSERT INTO product (ean, name, brand, category, quantity, unit)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (ean) DO UPDATE
            SET name = LEAST(product.name, EXCLUDED.name)
        RETURNING id
    """, (ean, name, brand, category, qty, unit))
    return cur.fetchone()[0]


def upsert_listing_and_price(cur, store_id, product_id, sku, raw_name,
                             raw_ean, url, offer, collected_at):
    cur.execute("""
        INSERT INTO listing (store_id, product_id, external_sku, raw_name,
                             raw_ean, url, match_method, last_seen)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (store_id, external_sku) DO UPDATE
            SET product_id = COALESCE(EXCLUDED.product_id, listing.product_id),
                last_seen = EXCLUDED.last_seen, active = true
        RETURNING id
    """, (store_id, product_id, sku, raw_name, raw_ean, url,
          "ean" if product_id else None, collected_at))
    listing_id = cur.fetchone()[0]

    price = offer.get("Price")
    if not price:
        return
    available = bool(offer.get("IsAvailable"))
    list_price = offer.get("ListPrice")

    cur.execute("""
        INSERT INTO price_history (listing_id, collected_at, price, list_price, available)
        VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
    """, (listing_id, collected_at, price, list_price, available))
    cur.execute("""
        INSERT INTO current_price (listing_id, price, list_price, available, collected_at)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (listing_id) DO UPDATE
            SET price = EXCLUDED.price, list_price = EXCLUDED.list_price,
                available = EXCLUDED.available, collected_at = EXCLUDED.collected_at
    """, (listing_id, price, list_price, available, collected_at))

# ---------------------------------------------------------------- orquestração

def run(limit_categories: int | None = None):
    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    collected_at = datetime.now(timezone.utc)

    for slug, cfg in RETAILERS.items():
        cur = conn.cursor()
        store_id = upsert_store(cur, slug)
        cur.execute("""INSERT INTO scrape_run (store_id) VALUES (%s) RETURNING id""",
                    (store_id,))
        run_id = cur.fetchone()[0]
        conn.commit()

        found = 0
        status, error = "ok", None
        try:
            cats = get_categories(cfg["base"])
            if limit_categories:
                cats = cats[:limit_categories]
            print(f"[{slug}] {len(cats)} categorias")
            for cat in cats:
                n_cat = 0
                for p in crawl_category(cfg["base"], cat["id"], cfg["sc"]):
                    for item in p.get("items", []):
                        sellers = item.get("sellers", [])
                        if not sellers:
                            continue
                        offer = sellers[0].get("commertialOffer", {})
                        ean = item.get("ean")
                        name = item.get("nameComplete") or p.get("productName")
                        product_id = upsert_product(
                            cur, ean, name, p.get("brand"), cat["name"])
                        upsert_listing_and_price(
                            cur, store_id, product_id, item["itemId"], name,
                            ean, p.get("link"), offer, collected_at)
                        found += 1
                        n_cat += 1
                conn.commit()
                print(f"  {cat['name']}: {n_cat} SKUs")
        except Exception as e:
            conn.rollback()
            status, error = "failed", str(e)[:500]
            print(f"[{slug}] ERRO: {e}")

        cur.execute("""
            UPDATE scrape_run SET finished_at = now(), status = %s,
                   items_found = %s, error = %s WHERE id = %s
        """, (status, found, error, run_id))
        conn.commit()
        print(f"[{slug}] total: {found} SKUs\n")

    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-categories", type=int, default=None)
    args = ap.parse_args()
    run(args.limit_categories)
