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

    const rows = db.prepare(`
      SELECT date, open, high, low, close, volume
      FROM ohlcv_daily
      WHERE asset_id = ?
      ORDER BY date ASC
    `).all(asset.id) as Array<{ date: string; open: number; high: number; low: number; close: number; volume: number }>;

    if (rows.length < 30) {
      return NextResponse.json({ success: true, analysis: null });
    }

    // 1. Detectar Swings (Fractales k=5)
    const k = 5;
    const swings: Array<{ index: number; date: string; price: number; type: "HIGH" | "LOW" }> = [];
    for (let i = k; i < rows.length - k; i++) {
      let isHigh = true;
      let isLow = true;
      for (let j = 1; j <= k; j++) {
        if (rows[i].high <= rows[i - j].high || rows[i].high < rows[i + j].high) isHigh = false;
        if (rows[i].low >= rows[i - j].low || rows[i].low > rows[i + j].low) isLow = false;
      }
      if (isHigh) swings.push({ index: i, date: rows[i].date, price: rows[i].high, type: "HIGH" });
      if (isLow) swings.push({ index: i, date: rows[i].date, price: rows[i].low, type: "LOW" });
    }

    // Prioridad 1: Tendencia por Higher Highs / Lows
    const highSwings = swings.filter((s) => s.type === "HIGH");
    const lowSwings = swings.filter((s) => s.type === "LOW");
    let trend = "SIDEWAYS";
    let swingStructure = "MIXED";

    if (highSwings.length >= 2 && lowSwings.length >= 2) {
      const hCurr = highSwings[highSwings.length - 1].price;
      const hPrev = highSwings[highSwings.length - 2].price;
      const lCurr = lowSwings[lowSwings.length - 1].price;
      const lPrev = lowSwings[lowSwings.length - 2].price;

      if (hCurr > hPrev && lCurr > lPrev) {
        trend = "BULLISH";
        swingStructure = "HH_HL (Máximos y Mínimos Crecientes)";
      } else if (hCurr < hPrev && lCurr < lPrev) {
        trend = "BEARISH";
        swingStructure = "LH_LL (Máximos y Mínimos Decrecientes)";
      }
    }

    // Prioridad 2: Agresividad del Giro
    let turnAggression = "Moderada";
    if (swings.length > 0) {
      const lastSwing = swings[swings.length - 1];
      const barsSince = rows.length - 1 - lastSwing.index;
      if (barsSince <= 3) turnAggression = "Vuelta en V Violenta (Clímax)";
      else if (barsSince <= 6) turnAggression = "Giro Rápido";
      else turnAggression = "Consolidación / Giro Lento";
    }

    // Prioridad 4: Rango Relativo de Vela vs Media (Clímax de Volatilidad)
    const lastRow = rows[rows.length - 1];
    const lastRange = Math.abs(lastRow.high - lastRow.low);
    const recentRanges = rows.slice(-21, -1).map((r) => Math.abs(r.high - r.low));
    const avgRange = recentRanges.reduce((a, b) => a + b, 0) / (recentRanges.length || 1);
    const relativeRange = avgRange > 0 ? lastRange / avgRange : 1.0;
    const isVolatilityClimax = relativeRange >= 2.0;

    // Prioridad 3: Tazas con Asa (Reversión) y Cuñas
    const patterns: any[] = [];
    if (highSwings.length >= 2 && lowSwings.length >= 1) {
      for (let i = 0; i < highSwings.length - 1; i++) {
        const left = highSwings[i];
        const right = highSwings[i + 1];
        const dist = right.index - left.index;
        if (dist >= 15 && dist <= 150) {
          const diff = Math.abs(left.price - right.price) / left.price;
          if (diff <= 0.06) {
            patterns.push({
              type: "CUP_AND_HANDLE",
              name: "Taza con Asa (Cambio de Tendencia)",
              startDate: left.date,
              endDate: right.date,
              resistance: Math.max(left.price, right.price),
              status: "Formación Confirmada"
            });
          }
        }
      }
    }

    // Cuña en últimos pivotes
    if (highSwings.length >= 3 && lowSwings.length >= 3) {
      const h3 = highSwings.slice(-3);
      const l3 = lowSwings.slice(-3);
      const hSlope = (h3[2].price - h3[0].price) / (h3[2].index - h3[0].index);
      const lSlope = (l3[2].price - l3[0].price) / (l3[2].index - l3[0].index);

      if (hSlope < 0 && lSlope < 0 && lSlope > hSlope) {
        patterns.push({
          type: "FALLING_WEDGE",
          name: "Cuña Descendente (Convergencia Alcista)",
          startDate: h3[0].date,
          endDate: h3[2].date,
          status: "Convergencia Activa"
        });
      } else if (hSlope > 0 && lSlope > 0 && hSlope < lSlope) {
        patterns.push({
          type: "RISING_WEDGE",
          name: "Cuña Ascendente (Convergencia Bajista)",
          startDate: l3[0].date,
          endDate: l3[2].date,
          status: "Convergencia Activa"
        });
      }
    }

    return NextResponse.json({
      success: true,
      analysis: {
        ticker: asset.ticker,
        name: asset.name,
        date: lastRow.date,
        trend,
        swingStructure,
        turnAggression,
        relativeRange: Number(relativeRange.toFixed(2)),
        isVolatilityClimax,
        patterns: patterns.slice(-3),
        totalSwings: swings.length
      }
    });
  } catch (error: any) {
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
}
