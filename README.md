# CestaCerta — Comparador de preços de supermercado (Blumenau)

Compara a lista de compras entre Bistek, Giassi e Angeloni (Cooper em breve)
usando os preços dos e-commerces das redes.

## Arquitetura
- **Next.js (App Router)** na Vercel — frontend + API routes
- **Postgres** no Neon/Supabase — schema em `schema.sql`
- **Scraper Python** via GitHub Actions (cron diário 03:00 BRT)

## Setup
1. Crie o banco no [Neon](https://neon.tech) e aplique `schema.sql`
2. `cp .env.example .env.local` e preencha `DATABASE_URL`
3. `npm install && npm run dev`
4. Rode a primeira coleta: `DATABASE_URL=... python scraper/pipeline.py`

## Deploy
1. Suba o repo no GitHub
2. Importe na Vercel e configure `DATABASE_URL` nas Environment Variables
3. Adicione o secret `DATABASE_URL` no GitHub (Settings > Secrets) para o cron da coleta

## Pendências
- [ ] Subcategorias VTEX (limite de 2.500 itens/categoria)
- [ ] Scraper Cooper (minhacooper.com.br)
- [ ] Fuzzy matching para produtos sem EAN
