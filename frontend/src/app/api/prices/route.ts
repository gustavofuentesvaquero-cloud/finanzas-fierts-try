import { NextResponse } from "next/server";
import { getDb } from "@/lib/db";

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const ticker = searchParams.get("ticker");

    if (!ticker) {
      return NextResponse.json({ success: false, error: "Ticker requerido" }, { status: 400 });
    }

    const db = getDb();
    const asset = db.prepare("SELECT id, ticker, name FROM assets WHERE ticker = ?").get(ticker.toUpperCase()) as any;

    if (!asset) {
      return NextResponse.json({ success: false, error: "Activo no encontrado" }, { status: 404 });
    }

    const prices = db.prepare(`
      SELECT date, open, high, low, close, adj_close, volume
      FROM ohlcv_daily
      WHERE asset_id = ?
      ORDER BY date ASC
    `).all(asset.id);

    return NextResponse.json({
      success: true,
      asset,
      prices
    });
  } catch (error: any) {
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
}
