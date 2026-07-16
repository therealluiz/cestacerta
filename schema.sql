-- ============================================================
-- Comparador de Preços — Modelo de Dados (PostgreSQL 15+)
-- ============================================================

-- ----------------------------------------------------------
-- REDES E LOJAS
-- ----------------------------------------------------------
CREATE TABLE retailer (
    id            SERIAL PRIMARY KEY,
    slug          TEXT UNIQUE NOT NULL,          -- 'bistek', 'giassi', 'angeloni', 'cooper'
    name          TEXT NOT NULL,
    platform      TEXT NOT NULL,                 -- 'vtex' | 'custom'
    base_url      TEXT NOT NULL,
    scraper_config JSONB NOT NULL DEFAULT '{}',  -- sales_channel, endpoints, headers etc.
    active        BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE store (
    id            SERIAL PRIMARY KEY,
    retailer_id   INT NOT NULL REFERENCES retailer(id),
    external_id   TEXT NOT NULL,                 -- id da filial na plataforma (ex: 'mafisa-bnu', sc=3)
    name          TEXT NOT NULL,
    city          TEXT NOT NULL,
    state         CHAR(2) NOT NULL DEFAULT 'SC',
    lat           NUMERIC(9,6),
    lng           NUMERIC(9,6),
    delivery_area JSONB,                         -- CEPs/polígono atendidos (se aplicável)
    active        BOOLEAN NOT NULL DEFAULT true,
    UNIQUE (retailer_id, external_id)
);

-- ----------------------------------------------------------
-- PRODUTO CANÔNICO (o "produto real", independente de mercado)
-- ----------------------------------------------------------
CREATE TABLE product (
    id            BIGSERIAL PRIMARY KEY,
    ean           TEXT UNIQUE,                   -- GTIN-13; NULL quando desconhecido
    name          TEXT NOT NULL,                 -- nome normalizado
    brand         TEXT,
    category      TEXT,                          -- taxonomia própria simplificada
    quantity      NUMERIC(10,3),                 -- 1.000, 0.500...
    unit          TEXT,                          -- 'kg' | 'g' | 'l' | 'ml' | 'un'
    image_url     TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_product_name_trgm ON product USING gin (name gin_trgm_ops); -- busca fuzzy (ext. pg_trgm)
CREATE INDEX idx_product_category ON product (category);

-- ----------------------------------------------------------
-- OFERTA: o produto como listado em cada mercado
-- ----------------------------------------------------------
CREATE TABLE listing (
    id            BIGSERIAL PRIMARY KEY,
    store_id      INT NOT NULL REFERENCES store(id),
    product_id    BIGINT REFERENCES product(id), -- NULL = ainda sem matching
    external_sku  TEXT NOT NULL,                 -- SKU/productId na plataforma de origem
    raw_name      TEXT NOT NULL,                 -- nome original do e-commerce (auditoria)
    raw_ean       TEXT,
    url           TEXT,                          -- deep link p/ o produto no e-commerce
    match_method  TEXT,                          -- 'ean' | 'fuzzy' | 'manual' | NULL
    match_score   NUMERIC(4,3),                  -- 0–1 quando fuzzy
    active        BOOLEAN NOT NULL DEFAULT true,
    first_seen    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (store_id, external_sku)
);

CREATE INDEX idx_listing_product ON listing (product_id);
CREATE INDEX idx_listing_unmatched ON listing (store_id) WHERE product_id IS NULL;

-- ----------------------------------------------------------
-- PREÇOS: snapshot histórico (append-only) + preço corrente
-- ----------------------------------------------------------
CREATE TABLE price_history (
    listing_id    BIGINT NOT NULL REFERENCES listing(id),
    collected_at  TIMESTAMPTZ NOT NULL,
    price         NUMERIC(10,2) NOT NULL,        -- preço de venda
    list_price    NUMERIC(10,2),                 -- preço "de" (riscado), se houver
    club_price    NUMERIC(10,2),                 -- preço clube/cooperado, se identificável
    available     BOOLEAN NOT NULL DEFAULT true,
    PRIMARY KEY (listing_id, collected_at)
);
-- Particionar por mês quando crescer: PARTITION BY RANGE (collected_at)

-- Preço corrente materializado (evita MAX(collected_at) em toda query do app)
CREATE TABLE current_price (
    listing_id    BIGINT PRIMARY KEY REFERENCES listing(id),
    price         NUMERIC(10,2) NOT NULL,
    list_price    NUMERIC(10,2),
    club_price    NUMERIC(10,2),
    available     BOOLEAN NOT NULL,
    collected_at  TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_current_price_collected ON current_price (collected_at);

-- ----------------------------------------------------------
-- USUÁRIO E LISTA DE COMPRAS (MVP: anônimo via device_id)
-- ----------------------------------------------------------
CREATE TABLE app_user (
    id            BIGSERIAL PRIMARY KEY,
    device_id     TEXT UNIQUE NOT NULL,          -- gerado no app; sem cadastro no MVP
    city          TEXT,
    cep           TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE shopping_list (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL REFERENCES app_user(id),
    name          TEXT NOT NULL DEFAULT 'Minha lista',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE shopping_list_item (
    id            BIGSERIAL PRIMARY KEY,
    list_id       BIGINT NOT NULL REFERENCES shopping_list(id) ON DELETE CASCADE,
    product_id    BIGINT NOT NULL REFERENCES product(id),
    qty           NUMERIC(6,2) NOT NULL DEFAULT 1,
    UNIQUE (list_id, product_id)
);

-- ----------------------------------------------------------
-- OPERAÇÃO: monitoramento das coletas
-- ----------------------------------------------------------
CREATE TABLE scrape_run (
    id            BIGSERIAL PRIMARY KEY,
    store_id      INT NOT NULL REFERENCES store(id),
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    status        TEXT NOT NULL DEFAULT 'running', -- running | ok | partial | failed
    items_found   INT,
    items_changed INT,
    error         TEXT
);

-- ----------------------------------------------------------
-- QUERY PRINCIPAL DO APP: total da cesta por mercado
-- ----------------------------------------------------------
-- SELECT s.id AS store_id, r.name AS retailer, st.name AS store,
--        COUNT(sli.product_id)                          AS itens_encontrados,
--        SUM(cp.price * sli.qty)                        AS total
-- FROM shopping_list_item sli
-- JOIN listing l        ON l.product_id = sli.product_id AND l.active
-- JOIN current_price cp ON cp.listing_id = l.id AND cp.available
-- JOIN store st         ON st.id = l.store_id AND st.city = :cidade_usuario
-- JOIN retailer r       ON r.id = st.retailer_id
-- JOIN store s          ON s.id = st.id
-- WHERE sli.list_id = :lista
-- GROUP BY s.id, r.name, st.name
-- ORDER BY total ASC;
