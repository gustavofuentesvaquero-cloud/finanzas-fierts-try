#!/usr/bin/env python3
"""
run_chartist_backtest.py -- Ejecuta el Backtest Chartista Multi-Factor
====================================================================
Aplica las 4 prioridades para generar y auditar senales en indices:
    1. Filtro de Tendencia (Higher Highs / Higher Lows)
    2. Agresividad de giro
    3. Gatillos por figuras: Taza con Asa (cambio de sesgo) y Cuñas
    4. Salidas y pausas por Climax de Volatilidad (Rango de vela anomalo)
"""

import sys
from pathlib import Path

# Agregar directorio backend al path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sqlite3
import pandas as pd
from chartist_engine import ChartistAnalyzer, ChartistPattern

DB_PATH = Path(__file__).resolve().parent / "data" / "backtesting.db"


def run_chartist_for_all():
    conn = sqlite3.connect(str(DB_PATH))
    analyzer = ChartistAnalyzer(
        swing_window=5,
        range_ma_window=20,
        range_climax_multiplier=2.0,
        max_v_turn_sessions=3
    )

    indices = ["^GSPC", "^IXIC", "^GDAXI", "^FCHI", "^IBEX"]
    print("\n" + "=" * 80)
    print("  EJECUCION DE ANALISIS CHARTISTA (4 PRIORIDADES)")
    print("=" * 80)

    for ticker in indices:
        cursor = conn.execute("SELECT id, name FROM assets WHERE ticker = ?", (ticker,))
        row = cursor.fetchone()
        if not row:
            continue
        asset_id, name = row[0], row[1]

        df = pd.read_sql_query(
            "SELECT date, open, high, low, close, adj_close, volume FROM ohlcv_daily WHERE asset_id = ? ORDER BY date ASC",
            conn,
            params=(asset_id,),
            parse_dates=["date"],
            index_col="date"
        )

        if df.empty or len(df) < 60:
            continue

        swings = analyzer.detect_swings(df)
        trend, swing_struct = analyzer.evaluate_swing_trend(swings)
        relative_range, is_climax = analyzer.evaluate_relative_candle_range(df)
        cups = analyzer.detect_cup_and_handle(df, swings)
        wedges = analyzer.detect_wedges(df, swings)

        # Ultimo estado
        latest_date = df.index[-1].strftime("%Y-%m-%d")
        latest_close = df.iloc[-1]["close"]
        latest_rel_range = relative_range.iloc[-1]
        latest_climax = bool(is_climax.iloc[-1])
        aggression = analyzer.evaluate_turn_aggression(df, swings, len(df) - 1)

        print(f"\n>> {ticker} ({name}) - {latest_date}")
        print(f"   1. Tendencia por Swings:   {trend} ({swing_struct})")
        print(f"   2. Agresividad de Giro:     {aggression * 100:.0f}% (Velocidad en pivotes)")
        print(f"   3. Figuras Detectadas:      {len(cups)} Tazas con Asa | {len(wedges)} Cuñas")
        for cup in cups[-2:]:
            print(f"      * [TAZA] {cup.description} -> Target: {cup.target_price} | Stop: {cup.stop_price}")
        for w in wedges[-2:]:
            print(f"      * [CUÑA] {w.description} -> Target: {w.target_price} | Stop: {w.stop_price}")
        print(f"   4. Rango Relativo de Vela:  {latest_rel_range:.2f}x media ({'CLIMAX / FIN DE TENDENCIA' if latest_climax else 'Normal'})")

    conn.close()
    print("\n" + "=" * 80)


if __name__ == "__main__":
    run_chartist_for_all()
