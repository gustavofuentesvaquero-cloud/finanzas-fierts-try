"use client";

import React, { useMemo } from "react";

interface Trade {
  id: number;
  run_id: number;
  signal_type: string;
  entry_date: string;
  entry_price: number;
  exit_date?: string | null;
  exit_price?: number | null;
  return_pct?: number | null;
  exit_reason?: string | null;
}

interface PricePoint {
  date: string;
  adj_close: number;
}

interface StrategyChartProps {
  ticker: string;
  prices: PricePoint[];
  trades: Trade[];
}

export function StrategyChart({ ticker, prices, trades }: StrategyChartProps) {
  const { minPrice, maxPrice, polylinePoints, tradeDots } = useMemo(() => {
    if (!prices || prices.length === 0) {
      return { minPrice: 0, maxPrice: 100, polylinePoints: "", tradeDots: [] };
    }

    const pValues = prices.map((p) => p.adj_close);
    const minP = Math.min(...pValues) * 0.95;
    const maxP = Math.max(...pValues) * 1.05;
    const range = maxP - minP || 1;

    // SVG coordinate space: 800 x 260
    const w = 800;
    const h = 260;
    const paddingX = 10;
    const paddingY = 20;

    const points = prices.map((p, idx) => {
      const x = paddingX + (idx / (prices.length - 1)) * (w - 2 * paddingX);
      const y = h - paddingY - ((p.adj_close - minP) / range) * (h - 2 * paddingY);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });

    const dots: Array<{ x: number; y: number; trade: Trade; isBuy: boolean }> = [];
    trades.forEach((trade) => {
      const entryIdx = prices.findIndex((p) => p.date === trade.entry_date);
      if (entryIdx >= 0) {
        const x = paddingX + (entryIdx / (prices.length - 1)) * (w - 2 * paddingX);
        const y = h - paddingY - ((trade.entry_price - minP) / range) * (h - 2 * paddingY);
        dots.push({ x, y, trade, isBuy: true });
      }

      if (trade.exit_date && trade.exit_price) {
        const exitIdx = prices.findIndex((p) => p.date === trade.exit_date);
        if (exitIdx >= 0) {
          const x = paddingX + (exitIdx / (prices.length - 1)) * (w - 2 * paddingX);
          const y = h - paddingY - ((trade.exit_price - minP) / range) * (h - 2 * paddingY);
          dots.push({ x, y, trade, isBuy: false });
        }
      }
    });

    return {
      minPrice: minP,
      maxPrice: maxP,
      polylinePoints: points.join(" "),
      tradeDots: dots,
    };
  }, [prices, trades]);

  if (!prices || prices.length === 0) {
    return (
      <div className="h-64 flex items-center justify-center border border-zinc-200 bg-white text-zinc-400 text-sm">
        Cargando serie temporal de precios...
      </div>
    );
  }

  const firstDate = prices[0]?.date || "";
  const lastDate = prices[prices.length - 1]?.date || "";
  const lastPrice = prices[prices.length - 1]?.adj_close || 0;

  return (
    <div className="bg-white border border-zinc-200 rounded-lg p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <span className="text-xs uppercase tracking-wider font-semibold text-zinc-500">
            Serie de Precios y Ejecuciones ({ticker})
          </span>
          <div className="text-xl font-mono font-medium text-zinc-900 mt-0.5">
            ${lastPrice.toFixed(2)}
          </div>
        </div>
        <div className="flex items-center gap-4 text-xs font-mono text-zinc-500">
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-600 inline-block"></span>
            <span>BUY</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-rose-600 inline-block"></span>
            <span>SELL</span>
          </div>
        </div>
      </div>

      <div className="w-full overflow-hidden">
        <svg viewBox="0 0 800 260" className="w-full h-56 bg-white overflow-visible">
          {/* Grid lines minimalistas */}
          <line x1="10" y1="30" x2="790" y2="30" stroke="#f4f4f5" strokeWidth="1" strokeDasharray="4 4" />
          <line x1="10" y1="120" x2="790" y2="120" stroke="#f4f4f5" strokeWidth="1" strokeDasharray="4 4" />
          <line x1="10" y1="210" x2="790" y2="210" stroke="#f4f4f5" strokeWidth="1" strokeDasharray="4 4" />

          {/* Linea de precio ajustado */}
          <polyline
            fill="none"
            stroke="#18181b"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            points={polylinePoints}
          />

          {/* Marcadores de ejecucion */}
          {tradeDots.map((dot, i) => (
            <g key={i}>
              <circle
                cx={dot.x}
                cy={dot.y}
                r="4.5"
                fill={dot.isBuy ? "#059669" : "#dc2626"}
                stroke="#ffffff"
                strokeWidth="1.5"
              />
            </g>
          ))}
        </svg>
      </div>

      <div className="flex justify-between items-center text-xs text-zinc-400 font-mono mt-2 border-t border-zinc-100 pt-2">
        <span>{firstDate}</span>
        <span>Rango: ${minPrice.toFixed(0)} - ${maxPrice.toFixed(0)}</span>
        <span>{lastDate}</span>
      </div>
    </div>
  );
}
