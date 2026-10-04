"use client";

import React, { useEffect, useState, useTransition } from "react";
import { ArrowUpRight, ArrowDownRight, RefreshCw, BarChart2, ShieldCheck, Activity, Compass, Zap, Flame, Maximize2 } from "lucide-react";
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

interface ChartistAnalysis {
  ticker: string;
  name: string;
  date: string;
  trend: string;
  swingStructure: string;
  turnAggression: string;
  relativeRange: number;
  isVolatilityClimax: boolean;
  patterns: Array<{
    type: string;
    name: string;
    startDate: string;
    endDate: string;
    status: string;
    resistance?: number;
  }>;
  totalSwings: number;
}

export default function Dashboard() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [runs, setRuns] = useState<BacktestRun[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [chartist, setChartist] = useState<ChartistAnalysis | null>(null);
  const [selectedTicker, setSelectedTicker] = useState<string>("^GSPC");
  const [prices, setPrices] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [isPending, startTransition] = useTransition();

  const loadData = async () => {
    try {
      setLoading(true);
      const res = await fetch("/api/backtest");
      const json = await res.json();
      if (json.success) {
        const loadedAssets: Asset[] = json.assets || [];
        setAssets(loadedAssets);
        setRuns(json.runs || []);
        setTrades(json.trades || []);
        if (loadedAssets.length > 0 && !loadedAssets.some((a) => a.ticker === selectedTicker)) {
          setSelectedTicker(loadedAssets[0].ticker);
        }
      }
    } catch (err) {
      console.error("Error al cargar datos:", err);
    } finally {
      setLoading(false);
    }
  };

  const loadPrices = async (ticker: string) => {
    try {
      const res = await fetch(`/api/prices?ticker=${encodeURIComponent(ticker)}`);
      const json = await res.json();
      if (json.success) {
        setPrices(json.prices || []);
      }
    } catch (err) {
      console.error("Error al cargar precios:", err);
    }
  };

  const loadChartist = async (ticker: string) => {
    try {
      const res = await fetch(`/api/chartist?ticker=${encodeURIComponent(ticker)}`);
      const json = await res.json();
      if (json.success) {
        setChartist(json.analysis || null);
      }
    } catch (err) {
      console.error("Error al cargar analisis chartista:", err);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  useEffect(() => {
    if (selectedTicker) {
      loadPrices(selectedTicker);
      loadChartist(selectedTicker);
    }
  }, [selectedTicker]);

  const currentRun = runs.find((r) => r.ticker === selectedTicker);
  const currentTrades = trades.filter((t) => t.run_id === currentRun?.id);

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
                Motor Cuantitativo Chartista
              </h1>
              <p className="text-[11px] text-zinc-400 font-mono">
                Índices EE.UU. &amp; Europa • 4 Prioridades Operativas
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => {
                startTransition(() => {
                  loadData();
                  if (selectedTicker) {
                    loadPrices(selectedTicker);
                    loadChartist(selectedTicker);
                  }
                });
              }}
              className="text-xs font-mono border border-zinc-200 px-3 py-1.5 rounded hover:bg-zinc-50 flex items-center gap-1.5 transition-colors text-zinc-700 bg-white"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isPending ? "animate-spin" : ""}`} />
              Sincronizar
            </button>
            <div className="h-4 w-px border-r border-zinc-200"></div>
            <span className="inline-flex items-center gap-1.5 text-[11px] font-mono text-zinc-500">
              <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
              SQLite WAL Active
            </span>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8 space-y-8 bg-white">
        {/* Selector de Ticker de Indices */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-zinc-100 pb-6">
          <div className="flex items-center gap-2 flex-wrap">
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
            {chartist ? (
              <span>Índice: {chartist.name} • Fecha: {chartist.date}</span>
            ) : (
              <span>Cargando datos...</span>
            )}
          </div>
        </div>

        {/* Panel de las 4 Prioridades Chartistas */}
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-xs uppercase tracking-wider font-semibold text-zinc-700">
              Diagnóstico de las 4 Prioridades Chartistas
            </h2>
            <span className="text-[11px] font-mono text-zinc-400">
              Marco Temporal: Diario (1D)
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            {/* 1. Prioridad 1: Tendencia por Swings */}
            <div className="border border-zinc-200 rounded-lg p-5 bg-white">
              <div className="flex items-center justify-between text-zinc-500 mb-2">
                <span className="text-[11px] uppercase tracking-wider font-semibold">
                  1. Tendencia Swings
                </span>
                <Compass className="w-4 h-4 text-zinc-500" />
              </div>
              <div className="mt-1">
                <div
                  className={`text-xl font-mono font-medium ${
                    chartist?.trend === "BULLISH"
                      ? "text-emerald-700"
                      : chartist?.trend === "BEARISH"
                      ? "text-rose-700"
                      : "text-zinc-700"
                  }`}
                >
                  {chartist?.trend === "BULLISH"
                    ? "ALCISTA"
                    : chartist?.trend === "BEARISH"
                    ? "BAJISTA"
                    : "LATERAL"}
                </div>
                <div className="text-[11px] text-zinc-400 font-mono mt-1">
                  {chartist?.swingStructure || "Calculando..."}
                </div>
              </div>
            </div>

            {/* 2. Prioridad 2: Agresividad del Giro */}
            <div className="border border-zinc-200 rounded-lg p-5 bg-white">
              <div className="flex items-center justify-between text-zinc-500 mb-2">
                <span className="text-[11px] uppercase tracking-wider font-semibold">
                  2. Agresividad Giro
                </span>
                <Zap className="w-4 h-4 text-zinc-500" />
              </div>
              <div className="mt-1">
                <div className="text-xl font-mono font-medium text-zinc-900">
                  {chartist?.turnAggression || "Moderada"}
                </div>
                <div className="text-[11px] text-zinc-400 font-mono mt-1">
                  Permanencia en vértices de precio
                </div>
              </div>
            </div>

            {/* 3. Prioridad 3: Figuras (Taza / Cuña) */}
            <div className="border border-zinc-200 rounded-lg p-5 bg-white">
              <div className="flex items-center justify-between text-zinc-500 mb-2">
                <span className="text-[11px] uppercase tracking-wider font-semibold">
                  3. Figuras Activas
                </span>
                <Maximize2 className="w-4 h-4 text-zinc-500" />
              </div>
              <div className="mt-1">
                <div className="text-xl font-mono font-medium text-zinc-900">
                  {chartist?.patterns?.length || 0} Detectada(s)
                </div>
                <div className="text-[11px] text-zinc-400 font-mono mt-1">
                  {chartist?.patterns && chartist.patterns.length > 0
                    ? chartist.patterns[chartist.patterns.length - 1].name
                    : "Taza con Asa (Reversión) / Cuñas"}
                </div>
              </div>
            </div>

            {/* 4. Prioridad 4: Climax de Volatilidad (Rango de Vela) */}
            <div className="border border-zinc-200 rounded-lg p-5 bg-white">
              <div className="flex items-center justify-between text-zinc-500 mb-2">
                <span className="text-[11px] uppercase tracking-wider font-semibold">
                  4. Rango Vela vs Media
                </span>
                <Flame className={`w-4 h-4 ${chartist?.isVolatilityClimax ? "text-rose-600" : "text-zinc-500"}`} />
              </div>
              <div className="mt-1">
                <div
                  className={`text-xl font-mono font-medium ${
                    chartist?.isVolatilityClimax ? "text-rose-600" : "text-zinc-900"
                  }`}
                >
                  {chartist?.relativeRange ? `${chartist.relativeRange}x Media` : "1.0x"}
                </div>
                <div className="text-[11px] font-mono mt-1">
                  {chartist?.isVolatilityClimax ? (
                    <span className="text-rose-600 font-semibold">ALERTA: FIN DE TENDENCIA / CLÍMAX</span>
                  ) : (
                    <span className="text-zinc-400">Rango Normal de Sesión</span>
                  )}
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Gráfico Minimalista de Precios */}
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-xs uppercase tracking-wider font-semibold text-zinc-600">
              Serie Temporal Diaria ({selectedTicker})
            </h2>
            <span className="text-xs text-zinc-400 font-mono">
              Fondo Estrictamente Blanco • Datos Oficiales
            </span>
          </div>
          <StrategyChart ticker={selectedTicker} prices={prices} trades={currentTrades} />
        </section>

        {/* Detalle de Figuras Chartistas y Log */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* Panel de Figuras Detectadas */}
          <div className="border border-zinc-200 rounded-lg p-5 bg-white">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-xs uppercase tracking-wider font-semibold text-zinc-700">
                Figuras Chartistas Identificadas
              </h3>
              <span className="text-xs font-mono text-zinc-400">
                Tazas (Giro de Tendencia) y Cuñas
              </span>
            </div>

            {!chartist?.patterns || chartist.patterns.length === 0 ? (
              <div className="text-xs font-mono text-zinc-400 py-8 text-center">
                No se detectan figuras activas en la ventana reciente.
              </div>
            ) : (
              <div className="space-y-3">
                {chartist.patterns.map((p, idx) => (
                  <div key={idx} className="border border-zinc-100 rounded p-3 text-xs font-mono bg-white hover:border-zinc-300 transition-colors">
                    <div className="flex items-center justify-between font-semibold text-zinc-800">
                      <span>{p.name}</span>
                      <span className="text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200 text-[10px]">
                        {p.status}
                      </span>
                    </div>
                    <div className="text-zinc-500 text-[11px] mt-1.5 flex justify-between">
                      <span>Inicio: {p.startDate}</span>
                      <span>Formación: {p.endDate}</span>
                    </div>
                    {p.resistance && (
                      <div className="text-zinc-600 text-[11px] mt-1">
                        Resistencia de Giro: ${p.resistance.toFixed(2)}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Resumen del Enfoque Metodológico */}
          <div className="border border-zinc-200 rounded-lg p-5 bg-white">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-xs uppercase tracking-wider font-semibold text-zinc-700">
                Reglas del Algoritmo Chartista
              </h3>
              <span className="text-xs font-mono text-zinc-400">Jerarquía Estricta</span>
            </div>

            <div className="space-y-2.5 text-xs text-zinc-600 font-mono">
              <div className="p-2.5 bg-zinc-50 border border-zinc-100 rounded">
                <span className="font-semibold text-zinc-800">1. Tendencia por Swings:</span> Determina el sesgo evaluando Higher Highs/Lows vs Lower Highs/Lows.
              </div>
              <div className="p-2.5 bg-zinc-50 border border-zinc-100 rounded">
                <span className="font-semibold text-zinc-800">2. Agresividad de Giro:</span> Monitorea el número de sesiones en máximos antes de girar (giros en V = clímax).
              </div>
              <div className="p-2.5 bg-zinc-50 border border-zinc-100 rounded">
                <span className="font-semibold text-zinc-800">3. Figuras Exclusivas:</span> Taza con Asa (como cambio de tendencia) y Cuñas para puntos de inflexión.
              </div>
              <div className="p-2.5 bg-zinc-50 border border-zinc-100 rounded">
                <span className="font-semibold text-zinc-800">4. Rango de Vela Relativo:</span> Compara el rango diario contra su media; picos extremos activan fin de tendencia.
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
