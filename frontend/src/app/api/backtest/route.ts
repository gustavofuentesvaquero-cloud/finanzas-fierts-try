import { NextResponse } from "next/server";
import { getDb } from "@/lib/db";

export async function GET() {
  try {
    const db = getDb();

    // 1. Activos registrados
    const assets = db.prepare(`
      SELECT a.id, a.ticker, a.name, a.sector, a.currency,
        (SELECT COUNT(*) FROM ohlcv_daily WHERE asset_id = a.id) as ohlcv_count,
        (SELECT MIN(date) FROM ohlcv_daily WHERE asset_id = a.id) as first_date,
        (SELECT MAX(date) FROM ohlcv_daily WHERE asset_id = a.id) as last_date
      FROM assets a
      ORDER BY a.ticker ASC
    `).all();

    // 2. Ultimas corridas de backtest
    const runs = db.prepare(`
      SELECT r.id, r.asset_id, a.ticker, r.strategy_name, r.parameters,
        r.start_date, r.end_date, r.total_return_pct, r.buy_hold_return_pct,
        r.alpha_pct, r.max_drawdown_pct, r.sharpe_ratio, r.total_trades,
        r.executed_at
      FROM backtest_runs r
      JOIN assets a ON r.asset_id = a.id
      ORDER BY r.executed_at DESC
    `).all();

    // 3. Trades asociados a las corridas
    const trades = db.prepare(`
      SELECT t.id, t.run_id, t.signal_type, t.entry_date, t.entry_price,
        t.exit_date, t.exit_price, t.return_pct, t.exit_reason
      FROM backtest_trades t
      ORDER BY t.entry_date ASC
    `).all();

    // 4. Fundamentales
    const fundamentals = db.prepare(`
      SELECT f.asset_id, a.ticker, f.period_end, f.period_type, f.ebitda,
        f.ebitda_growth, f.wacc, f.roe, f.debt_to_equity
      FROM fundamental_ratios f
      JOIN assets a ON f.asset_id = a.id
      ORDER BY f.period_end DESC
    `).all();

    return NextResponse.json({
      success: true,
      assets,
      runs: runs.map((run: any) => ({
        ...run,
        parameters: JSON.parse(run.parameters || "{}")
      })),
      trades,
      fundamentals
    });
  } catch (error: any) {
    return NextResponse.json(
      { success: false, error: error.message },
      { status: 500 }
    );
  }
}
