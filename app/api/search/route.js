import { pool } from "@/lib/db";
import { NextResponse } from "next/server";

export const runtime = "nodejs";

export async function GET(req) {
  const q = req.nextUrl.searchParams.get("q")?.trim();
  if (!q || q.length < 2) return NextResponse.json({ products: [] });
  if (!process.env.DATABASE_URL) return NextResponse.json({ products: [], setupPending: true });

  try {
    const { rows } = await pool.query(
      `
      SELECT p.id, p.name, p.brand, p.quantity, p.unit, p.image_url,
             json_agg(json_build_object(
               'retailer', r.name, 'slug', r.slug,
               'price', cp.price, 'list_price', cp.list_price,
               'url', l.url, 'collected_at', cp.collected_at
             ) ORDER BY cp.price) AS offers
      FROM product p
      JOIN listing l        ON l.product_id = p.id AND l.active
      JOIN current_price cp ON cp.listing_id = l.id AND cp.available
      JOIN store st         ON st.id = l.store_id
      JOIN retailer r       ON r.id = st.retailer_id
      WHERE p.name ILIKE '%' || $1 || '%' OR similarity(p.name, $1) > 0.25
      GROUP BY p.id
      ORDER BY count(DISTINCT r.id) DESC, min(cp.price) ASC
      LIMIT 30
      `,
      [q]
    );
    return NextResponse.json({ products: rows });
  } catch (e) {
    return NextResponse.json(
      { products: [], setupPending: true, error: e.message },
      { status: 200 }
    );
  }
}