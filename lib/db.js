import { Pool } from "pg";

// Pool global reaproveitado entre invocacoes serverless
const globalForPg = globalThis;

// Tenta DATABASE_URL primeiro (pooled), depois POSTGRES_URL (fallback)
const connectionString = process.env.DATABASE_URL || 
                         process.env.POSTGRES_URL ||
                         "postgresql://localhost/comparador";

export const pool =
  globalForPg._pgPool ??
  new Pool({
    connectionString,
    max: 3,
    ssl: connectionString.includes("sslmode=require") || connectionString.includes("neon")
      ? { rejectUnauthorized: false }
      : undefined,
  });

if (!globalForPg._pgPool) globalForPg._pgPool = pool;
