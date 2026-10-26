-- =====================================================
-- SCHEMA INTERNACIONAL: país > región > ciudad > retailer > precio
-- Supabase / Postgres - Partitioned por país para escala
-- =====================================================

-- 1. Países
CREATE TABLE countries (
  code CHAR(2) PRIMARY KEY, -- ISO 3166-1 alpha-2: NZ, CL, US, ES, AR, MX
  name TEXT NOT NULL, -- New Zealand, Chile
  currency CHAR(3) NOT NULL, -- NZD, CLP, USD, EUR
  timezone TEXT NOT NULL, -- Pacific/Auckland, America/Santiago
  default_language TEXT, -- en-NZ, es-CL
  is_active BOOLEAN DEFAULT true
);

INSERT INTO countries VALUES 
('NZ','New Zealand','NZD','Pacific/Auckland','en-NZ'),
('CL','Chile','CLP','America/Santiago','es-CL'),
('US','United States','USD','America/Los_Angeles','en-US'),
('ES','España','EUR','Europe/Madrid','es-ES');

-- 2. Regiones / Estados
CREATE TABLE regions (
  id TEXT PRIMARY KEY, -- NZ-WGN, CL-RM, US-CA, ES-MD
  country_code CHAR(2) REFERENCES countries(code),
  name TEXT NOT NULL, -- Wellington, Región Metropolitana
  iso_code TEXT,
  timezone TEXT -- puede sobreescribir país si es grande (US)
);
CREATE INDEX ON regions(country_code);

-- 3. Ciudades
CREATE TABLE cities (
  id TEXT PRIMARY KEY, -- wellington, santiago, los-angeles
  country_code CHAR(2) REFERENCES countries(code),
  region_id TEXT REFERENCES regions(id),
  name TEXT NOT NULL,
  lat DOUBLE PRECISION,
  lon DOUBLE PRECISION,
  is_active BOOLEAN DEFAULT true
);
CREATE INDEX ON cities(country_code, region_id);

-- 4. Cadenas de retailers (multi-país)
CREATE TABLE retailer_chains (
  id TEXT PRIMARY KEY, -- countdown, jumbo, walmart, sodimac
  name TEXT NOT NULL,
  category TEXT NOT NULL, -- supermarket, hardware, pharmacy, general, electronics
  country_codes CHAR(2)[] NOT NULL, -- {NZ} o {CL,AR,PE}
  logo_url TEXT,
  website TEXT
);

-- 5. Tiendas físicas (con jerarquía completa)
CREATE TABLE retailer_stores (
  id TEXT PRIMARY KEY, -- NZ_WGN_wellington_countdown_thorndon_001
  chain_id TEXT REFERENCES retailer_chains(id),
  chain_name TEXT NOT NULL, -- denormalizado para lectura rápida
  
  -- Jerarquía geográfica (desnormalizado para queries rápidas)
  country_code CHAR(2) NOT NULL REFERENCES countries(code),
  region_id TEXT NOT NULL REFERENCES regions(id),
  city_id TEXT NOT NULL REFERENCES cities(id),
  country_name TEXT NOT NULL,
  region_name TEXT NOT NULL,
  city_name TEXT NOT NULL,
  
  name TEXT NOT NULL, -- Countdown Thorndon
  address TEXT,
  lat DOUBLE PRECISION NOT NULL,
  lon DOUBLE PRECISION NOT NULL,
  category TEXT NOT NULL,
  is_active BOOLEAN DEFAULT true,
  
  -- Para búsqueda geoespacial
  geom GEOGRAPHY(POINT,4326) -- PostGIS opcional, si no usar lat/lon
);
CREATE INDEX ON retailer_stores(country_code, city_id);
CREATE INDEX ON retailer_stores(chain_id);
CREATE INDEX ON retailer_stores USING GIST(geom) WHERE geom IS NOT NULL;

-- Ejemplo inserts NZ
INSERT INTO regions VALUES ('NZ-WGN','NZ','Wellington Region','WGN','Pacific/Auckland');
INSERT INTO cities VALUES ('wellington','NZ','NZ-WGN','Wellington',-41.2924,174.7787);
INSERT INTO retailer_chains VALUES ('countdown','Countdown','supermarket','{NZ}',null,'countdown.co.nz');
INSERT INTO retailer_stores VALUES (
  'NZ_WGN_wellington_countdown_thorndon_001','countdown','Countdown',
  'NZ','NZ-WGN','wellington','New Zealand','Wellington Region','Wellington',
  'Countdown Thorndon','20 Murphy St, Thorndon',-41.274,174.772,'supermarket',true,null
);

-- 6. PRECIOS - Tabla principal, particionada por país
CREATE TABLE product_prices (
  ean TEXT NOT NULL, -- 9414763003146
  
  -- Jerarquía (para partition y query rápido)
  country_code CHAR(2) NOT NULL,
  region_id TEXT NOT NULL,
  city_id TEXT NOT NULL,
  store_id TEXT NOT NULL REFERENCES retailer_stores(id),
  chain_id TEXT NOT NULL,
  
  -- Datos precio
  price NUMERIC(10,2) NOT NULL,
  promo_price NUMERIC(10,2),
  currency CHAR(3) NOT NULL,
  stock BOOLEAN DEFAULT true,
  stock_quantity INT,
  
  -- Metadata scrapper
  last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_updated_local TEXT, -- "2026-10-13 08:00 NZST"
  source TEXT, -- scrapper_countdown_nz_v2
  scrapper_run_id TEXT, -- NZ_20261013_0800
  
  -- Datos producto enriquecidos
  product_name TEXT,
  brand TEXT,
  image_url TEXT,
  category_path TEXT,
  
  PRIMARY KEY (ean, store_id, country_code) -- PK incluye país para partition
) PARTITION BY LIST (country_code);

-- Particiones por país (escala horizontal)
CREATE TABLE product_prices_nz PARTITION OF product_prices FOR VALUES IN ('NZ');
CREATE TABLE product_prices_cl PARTITION OF product_prices FOR VALUES IN ('CL');
CREATE TABLE product_prices_us PARTITION OF product_prices FOR VALUES IN ('US');
CREATE TABLE product_prices_es PARTITION OF product_prices FOR VALUES IN ('ES');
CREATE TABLE product_prices_default PARTITION OF product_prices DEFAULT;

-- Índices críticos para lookup <200ms
CREATE INDEX ON product_prices (ean, country_code, city_id);
CREATE INDEX ON product_prices (ean, store_id);
CREATE INDEX ON product_prices (chain_id, country_code);
CREATE INDEX ON product_prices (last_updated DESC);
CREATE INDEX ON product_prices (country_code, city_id, chain_id);

-- 7. Scrapper runs - auditoría de jobs 8am y 3pm por país
CREATE TABLE scrapper_runs (
  id TEXT PRIMARY KEY, -- NZ_20261013_0800
  country_code CHAR(2) NOT NULL,
  region_id TEXT, -- opcional, si corre por región
  city_id TEXT, -- opcional
  scheduled_at TIMESTAMPTZ NOT NULL, -- 8am local
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  status TEXT, -- running, success, failed
  stores_processed INT,
  products_upserted INT,
  errors JSONB
);
CREATE INDEX ON scrapper_runs(country_code, scheduled_at DESC);

-- 8. Vista materializada para precios más baratos por ciudad (para comparador)
CREATE MATERIALIZED VIEW cheapest_prices_by_city AS
SELECT 
  country_code, city_id, ean,
  MIN(COALESCE(promo_price, price)) as cheapest_price,
  currency,
  COUNT(DISTINCT store_id) as stores_with_stock
FROM product_prices
WHERE stock = true
GROUP BY country_code, city_id, ean, currency;

-- Refrescar cada vez que termina scrapper
-- REFRESH MATERIALIZED VIEW CONCURRENTLY cheapest_prices_by_city;

-- =====================================================
-- QUERIES QUE USA LA APP
-- =====================================================

-- Lookup rápido: EAN en tienda donde estoy (Wellington)
-- SELECT * FROM product_prices 
-- WHERE ean='9414763003146' AND store_id='NZ_WGN_wellington_countdown_thorndon_001' AND country_code='NZ';

-- Lookup comparador: EAN en toda mi ciudad
-- SELECT * FROM product_prices 
-- WHERE ean='9414763003146' AND city_id='wellington' AND country_code='NZ' AND stock=true
-- ORDER BY COALESCE(promo_price, price) ASC;

-- Resolver tiendas cercanas por GPS (radio 300m)
-- SELECT * FROM retailer_stores 
-- WHERE country_code='NZ' AND city_id='wellington'
-- AND ST_DWithin(geom, ST_MakePoint(lon, lat)::geography, 300)
-- ORDER BY geom <-> ST_MakePoint(lon, lat)::geography LIMIT 5;
