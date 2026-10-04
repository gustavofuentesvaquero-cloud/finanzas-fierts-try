"use client";

import React, { useEffect, useState, useTransition } from "react";
import { ArrowUpRight, ArrowDownRight, RefreshCw, BarChart2, ShieldCheck, Activity } from "lucide-react";
import { StrategyChart } from "@/components/StrategyChart";

interface Asset {
  id: number;
  ticker: string;
  name: string;
  sector: string;
  ohlcv_count: number;
  first_date: string;
  last_date: string;
}

interface BacktestRun {
  id: number;
  asset_id: number;
  ticker: string;
  strategy_name: string;
  parameters: any;
  start_date: string;
  end_date: string;
  total_return_pct: number;
  buy_hold_return_pct: number;
  alpha_pct: number;
  max_drawdown_pct: number;
  sharpe_ratio: number;
  total_trades: number;
  executed_at: string;
}

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

interface Fundamental {
  asset_id: number;
  ticker: string;
  period_end: string;
  period_type: string;
  ebitda: number | null;
  ebitda_growth: number | null;
  wacc: number | null;
  roe: number | null;
  debt_to_equity: number | null;
}

export default function Dashboard() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [runs, setRuns] = useState<BacktestRun[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [fundamentals, setFundamentals] = useState<Fundamental[]>([]);
  const [selectedTicker, setSelectedTicker] = useState<string>("AAPL");
  const [prices, setPrices] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [isPending, startTransition] = useTransition();

  const loadData = async () => {
    try {
      setLoading(true);
      const res = await fetch("/api/backtest");
      const json = await res.json();
      if (json.success) {
        setAssets(json.assets || []);
        setRuns(json.runs || []);
        setTrades(json.trades || []);
        setFundamentals(json.fundamentals || []);
      }
    } catch (err) {
      console.error("Error al cargar datos del backtest:", err);
    } finally {
      setLoading(false);
    }
  };

  const loadPrices = async (ticker: string) => {
    try {
      const res = await fetch(`/api/prices?ticker=${ticker}`);
      const json = await res.json();
      if (json.success) {
        setPrices(json.prices || []);
      }
    } catch (err) {
      console.error("Error al cargar precios:", err);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  useEffect(() => {
    if (selectedTicker) {
      loadPrices(selectedTicker);
    }
  }, [selectedTicker]);

  // Datos filtrados para el ticker seleccionado
  const currentRun = runs.find((r) => r.ticker === selectedTicker);
  const currentTrades = trades.filter((t) => t.run_id === currentRun?.id);
  const currentFundamentals = fundamentals.filter((f) => f.ticker === selectedTicker).slice(0, 4);

  return (
    <div className="min-h-screen bg-white text-zinc-900">
      {/* Barra superior de navegacion minimalista */}
      <header className="border-b border-zinc-200 bg-white sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-7 h-7 bg-black rounded flex items-center justify-center text-white font-bold text-xs">
              Q
            </div>
            <div>
              <h1 className="text-sm font-semibold tracking-tight text-zinc-900">
                Motor Cuantitativo Híbrido
              </h1>
              <p className="text-[11px] text-zinc-400 font-mono">
                Cruce SMA + Validación Fundamental (EBITDA / D&E)
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => {
                startTransition(() => {
                  loadData();
                  if (selectedTicker) loadPrices(selectedTicker);
                });
              }}
              className="text-xs font-mono border border-zinc-200 px-3 py-1.5 rounded hover:bg-zinc-50 flex items-center gap-1.5 transition-colors text-zinc-700 bg-white"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isPending ? "animate-spin" : ""}`} />
              Sincronizar
            </button>
            <div className="h-4 w-px bg-zinc-200"></div>
            <span className="inline-flex items-center gap-1.5 text-[11px] font-mono text-zinc-500">
              <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
              SQLite WAL Active
            </span>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8 space-y-8 bg-white">
        {/* Selector de Ticker y Resumen de Estado */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-zinc-100 pb-6">
          <div className="flex items-center gap-2">
            {assets.map((asset) => {
              const active = asset.ticker === selectedTicker;
              return (
                <button
                  key={asset.ticker}
                  onClick={() => setSelectedTicker(asset.ticker)}
                  className={`px-4 py-2 text-sm font-mono rounded border transition-all ${
                    active
                      ? "border-black bg-black text-white font-medium"
                      : "border-zinc-200 bg-white text-zinc-600 hover:border-zinc-400"
                  }`}
                >
                  {asset.ticker}
                </button>
              );
            })}
          </div>

          <div className="text-xs font-mono text-zinc-500">
            {currentRun ? (
              <span>
                Ventana de prueba: {currentRun.start_date} a {currentRun.end_date}
              </span>
            ) : (
              <span>Sin ejecución registrada</span>
            )}
          </div>
        </div>

        {/* Tarjetas Cuantitativas Principales */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {/* 1. Retorno Estrategia */}
          <div className="border border-zinc-200 rounded-lg p-5 bg-white">
            <span className="text-[11px] uppercase tracking-wider font-semibold text-zinc-500">
              Retorno Estrategia
            </span>
            <div className="mt-2 flex items-baseline justify-between">
              <div
                className={`text-2xl font-mono font-medium ${
                  (currentRun?.total_return_pct ?? 0) >= 0 ? "text-emerald-700" : "text-rose-700"
                }`}
              >
                {(currentRun?.total_return_pct ?? 0) >= 0 ? "+" : ""}
                {currentRun?.total_return_pct?.toFixed(2) ?? "0.00"}%
              </div>
              {(currentRun?.total_return_pct ?? 0) >= 0 ? (
                <ArrowUpRight className="w-5 h-5 text-emerald-600" />
              ) : (
                <ArrowDownRight className="w-5 h-5 text-rose-600" />
              )}
            </div>
            <p className="text-xs text-zinc-400 mt-2 font-mono">
              Capital base: ${currentRun?.parameters?.initial_capital?.toLocaleString() || "100,000"}
            </p>
          </div>

          {/* 2. Buy & Hold Benchmark */}
          <div className="border border-zinc-200 rounded-lg p-5 bg-white">
            <span className="text-[11px] uppercase tracking-wider font-semibold text-zinc-500">
              Benchmark Buy & Hold
            </span>
            <div className="mt-2 flex items-baseline justify-between">
              <div className="text-2xl font-mono font-medium text-zinc-900">
                {(currentRun?.buy_hold_return_pct ?? 0) >= 0 ? "+" : ""}
                {currentRun?.buy_hold_return_pct?.toFixed(2) ?? "0.00"}%
              </div>
              <Activity className="w-5 h-5 text-zinc-400" />
            </div>
            <p className="text-xs text-zinc-400 mt-2 font-mono">Retorno del activo subyacente</p>
          </div>

          {/* 3. Alpha */}
          <div className="border border-zinc-200 rounded-lg p-5 bg-white">
            <span className="text-[11px] uppercase tracking-wider font-semibold text-zinc-500">
              Alpha vs Buy & Hold
            </span>
            <div className="mt-2 flex items-baseline justify-between">
              <div
                className={`text-2xl font-mono font-medium ${
                  (currentRun?.alpha_pct ?? 0) >= 0 ? "text-emerald-700" : "text-rose-700"
                }`}
              >
                {(currentRun?.alpha_pct ?? 0) >= 0 ? "+" : ""}
                {currentRun?.alpha_pct?.toFixed(2) ?? "0.00"}%
              </div>
              <BarChart2 className="w-5 h-5 text-zinc-400" />
            </div>
            <p className="text-xs text-zinc-400 mt-2 font-mono">Sobre/Bajo rendimiento neto</p>
          </div>

          {/* 4. Riesgo (Sharpe & MaxDD) */}
          <div className="border border-zinc-200 rounded-lg p-5 bg-white">
            <span className="text-[11px] uppercase tracking-wider font-semibold text-zinc-500">
              Métricas de Riesgo
            </span>
            <div className="mt-2 flex items-baseline justify-between">
              <div>
                <div className="text-xl font-mono font-medium text-zinc-900">
                  {currentRun?.sharpe_ratio?.toFixed(2) ?? "0.00"}
                </div>
                <div className="text-[11px] text-zinc-400 font-mono">Sharpe Ratio</div>
              </div>
              <div className="text-right">
                <div className="text-xl font-mono font-medium text-rose-600">
                  {currentRun?.max_drawdown_pct?.toFixed(2) ?? "0.00"}%
                </div>
                <div className="text-[11px] text-zinc-400 font-mono">Max Drawdown</div>
              </div>
            </div>
          </div>
        </div>

        {/* Gráfico Minimalista de la Estrategia */}
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-xs uppercase tracking-wider font-semibold text-zinc-600">
              Evolución y Ejecuciones
            </h2>
            <span className="text-xs text-zinc-400 font-mono">
              SMA({currentRun?.parameters?.sma_short || 20}) / SMA({currentRun?.parameters?.sma_long || 50}) + Filtro Fundamental
            </span>
          </div>
          <StrategyChart ticker={selectedTicker} prices={prices} trades={currentTrades} />
        </section>

        {/* Dos Columnas: Log de Trades y Filtros Fundamentales */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* Tabla de Operaciones */}
          <div className="border border-zinc-200 rounded-lg p-5 bg-white">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-xs uppercase tracking-wider font-semibold text-zinc-700">
                Log de Trades Registrados ({currentTrades.length})
              </h3>
              <span className="text-xs font-mono text-zinc-400">Total simulados</span>
            </div>

            {currentTrades.length === 0 ? (
              <div className="text-xs font-mono text-zinc-400 py-8 text-center">
                No hay operaciones para este activo.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs font-mono">
                  <thead>
                    <tr className="border-b border-zinc-200 text-left text-zinc-400">
                      <th className="pb-2 font-normal">Tipo</th>
                      <th className="pb-2 font-normal">Entrada</th>
                      <th className="pb-2 font-normal">Salida</th>
                      <th className="pb-2 font-normal text-right">Retorno</th>
                      <th className="pb-2 font-normal text-right">Motivo</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-100">
                    {currentTrades.map((t) => (
                      <tr key={t.id} className="hover:bg-zinc-50">
                        <td className="py-2.5">
                          <span
                            className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                              t.signal_type === "BUY"
                                ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                                : "bg-rose-50 text-rose-700 border border-rose-200"
                            }`}
                          >
                            {t.signal_type}
                          </span>
                        </td>
                        <td className="py-2.5 text-zinc-600">
                          {t.entry_date} (${t.entry_price.toFixed(2)})
                        </td>
                        <td className="py-2.5 text-zinc-600">
                          {t.exit_date ? `${t.exit_date} ($${t.exit_price?.toFixed(2)})` : "Abierta"}
                        </td>
                        <td
                          className={`py-2.5 text-right font-medium ${
                            (t.return_pct ?? 0) >= 0 ? "text-emerald-700" : "text-rose-700"
                          }`}
                        >
                          {t.return_pct !== null && t.return_pct !== undefined
                            ? `${t.return_pct >= 0 ? "+" : ""}${t.return_pct.toFixed(2)}%`
                            : "-"}
                        </td>
                        <td className="py-2.5 text-right text-zinc-400">
                          {t.exit_reason || "-"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Validaciones Fundamentales */}
          <div className="border border-zinc-200 rounded-lg p-5 bg-white">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-1.5">
                <ShieldCheck className="w-4 h-4 text-zinc-700" />
                <h3 className="text-xs uppercase tracking-wider font-semibold text-zinc-700">
                  Filtro Fundamental Look-Back
                </h3>
              </div>
              <span className="text-[11px] font-mono text-zinc-400">
                EBITDA &gt; 0% &amp; D/E &lt; 3.0
              </span>
            </div>

            {currentFundamentals.length === 0 ? (
              <div className="text-xs font-mono text-zinc-400 py-8 text-center">
                Sin datos fundamentales registrados.
              </div>
            ) : (
              <div className="space-y-3">
                {currentFundamentals.map((f, i) => (
                  <div
                    key={i}
                    className="border border-zinc-100 rounded p-3 text-xs font-mono flex items-center justify-between hover:border-zinc-300 transition-colors bg-white"
                  >
                    <div>
                      <div className="font-semibold text-zinc-800">
                        Período: {f.period_end} ({f.period_type})
                      </div>
                      <div className="text-zinc-500 text-[11px] mt-0.5">
                        EBITDA: ${f.ebitda ? (f.ebitda / 1e9).toFixed(2) + "B" : "N/A"}
                      </div>
                    </div>
                    <div className="text-right">
                      <div
                        className={`font-medium ${
                          (f.ebitda_growth ?? 0) >= 0 ? "text-emerald-700" : "text-rose-700"
                        }`}
                      >
                        Crecimiento:{" "}
                        {f.ebitda_growth !== null && f.ebitda_growth !== undefined
                          ? `${f.ebitda_growth >= 0 ? "+" : ""}${f.ebitda_growth.toFixed(1)}%`
                          : "N/A"}
                      </div>
                      <div className="text-zinc-500 text-[11px] mt-0.5">
                        Deuda/Patrimonio: {f.debt_to_equity ? f.debt_to_equity.toFixed(2) : "N/A"}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
