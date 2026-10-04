#!/usr/bin/env python3
"""
engine.py -- Motor de Backtesting Hibrido (Tecnico + Fundamental)
==================================================================
Evalua estrategias de trading cruzando senales tecnicas (cruce de medias
moviles) con filtros de validacion fundamental (EBITDA growth, leverage).

Arquitectura:
    1. DataLoader       - Carga series OHLCV y fundamentales desde SQLite
    2. SignalGenerator  - Genera senales tecnicas (Golden/Death Cross)
    3. FundamentalFilter - Valida senales contra metricas corporativas
    4. BacktestEngine   - Ejecuta la simulacion y calcula metricas
    5. ResultsPersister - Persiste resultados en backtest_runs/trades

Uso:
    python engine.py                              # Todos los activos, config default
    python engine.py --ticker AAPL                 # Un solo activo
    python engine.py --sma-short 20 --sma-long 50  # Parametros custom
    python engine.py --no-fundamental-filter        # Solo tecnico, sin filtro
    python engine.py --list                        # Listar backtests anteriores
"""

import argparse
import json
import logging
import sqlite3
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------------

DB_PATH = Path(__file__).resolve().parent / "data" / "backtesting.db"

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("engine")

# Parametros por defecto de la estrategia
DEFAULT_SMA_SHORT = 20
DEFAULT_SMA_LONG = 50
DEFAULT_INITIAL_CAPITAL = 100_000.0
RISK_FREE_RATE = 0.04  # 4% anual (T-Bill proxy)
TRADING_DAYS_PER_YEAR = 252


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class TradeRecord:
    """Registro de una operacion individual."""
    signal_type: str        # 'BUY' o 'SELL'
    entry_date: str
    entry_price: float
    exit_date: Optional[str] = None
    exit_price: Optional[float] = None
    return_pct: Optional[float] = None
    exit_reason: Optional[str] = None


@dataclass
class BacktestResult:
    """Resultado completo de una ejecucion de backtest."""
    asset_id: int
    ticker: str
    strategy_name: str
    parameters: dict
    start_date: str
    end_date: str
    # Rendimiento
    total_return_pct: float = 0.0
    buy_hold_return_pct: float = 0.0
    alpha_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    total_trades: int = 0
    # Metricas adicionales (no persistidas, para reporte)
    win_rate: float = 0.0
    avg_trade_return: float = 0.0
    best_trade_pct: float = 0.0
    worst_trade_pct: float = 0.0
    total_days_in_market: int = 0
    # Datos internos
    trades: list = field(default_factory=list)
    equity_curve: Optional[pd.Series] = None


# ---------------------------------------------------------------------------
# 1. DataLoader
# ---------------------------------------------------------------------------

class DataLoader:
    """Carga datos desde SQLite para el motor de backtesting."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute("PRAGMA foreign_keys=ON")

    def close(self):
        self.conn.close()

    def get_all_assets(self) -> list[dict]:
        """Retorna todos los activos registrados."""
        cursor = self.conn.execute(
            "SELECT id, ticker, name, sector FROM assets ORDER BY ticker"
        )
        return [
            {"id": r[0], "ticker": r[1], "name": r[2], "sector": r[3]}
            for r in cursor.fetchall()
        ]

    def get_asset_id(self, ticker: str) -> Optional[int]:
        """Retorna el asset_id para un ticker dado."""
        cursor = self.conn.execute(
            "SELECT id FROM assets WHERE ticker = ?", (ticker.upper(),)
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def load_ohlcv(self, asset_id: int) -> pd.DataFrame:
        """
        Carga datos OHLCV diarios para un activo.
        Retorna DataFrame con index=date, columnas: open, high, low, close, adj_close, volume.
        """
        df = pd.read_sql_query(
            """
            SELECT date, open, high, low, close, adj_close, volume
            FROM ohlcv_daily
            WHERE asset_id = ?
            ORDER BY date ASC
            """,
            self.conn,
            params=(asset_id,),
            parse_dates=["date"],
            index_col="date",
        )
        logger.info("  Cargadas %d filas OHLCV (asset_id=%d)", len(df), asset_id)
        return df

    def load_fundamentals(self, asset_id: int, period_type: str = "quarterly") -> pd.DataFrame:
        """
        Carga ratios fundamentales para un activo.
        Retorna DataFrame con index=period_end, ordenado cronologicamente.
        """
        df = pd.read_sql_query(
            """
            SELECT period_end, ebitda, ebitda_growth, revenue, net_income,
                   wacc, roe, debt_to_equity, current_ratio, pe_ratio, pb_ratio
            FROM fundamental_ratios
            WHERE asset_id = ? AND period_type = ?
            ORDER BY period_end ASC
            """,
            self.conn,
            params=(asset_id, period_type),
            parse_dates=["period_end"],
            index_col="period_end",
        )
        logger.info("  Cargados %d registros fundamentales %s (asset_id=%d)",
                     len(df), period_type, asset_id)
        return df


# ---------------------------------------------------------------------------
# 2. SignalGenerator -- Cruce de Medias Moviles (SMA Crossover)
# ---------------------------------------------------------------------------

class SignalGenerator:
    """
    Genera senales de trading basadas en el cruce de medias moviles simples.

    Logica:
        - Golden Cross (SMA_short cruza por encima de SMA_long) -> BUY
        - Death Cross  (SMA_short cruza por debajo de SMA_long) -> SELL

    Usa adj_close para calculo de SMAs (ajustado por splits/dividendos).
    """

    def __init__(self, sma_short: int = DEFAULT_SMA_SHORT, sma_long: int = DEFAULT_SMA_LONG):
        if sma_short >= sma_long:
            raise ValueError(
                f"SMA_short ({sma_short}) debe ser menor que SMA_long ({sma_long})"
            )
        self.sma_short = sma_short
        self.sma_long = sma_long

    def generate(self, ohlcv: pd.DataFrame) -> pd.DataFrame:
        """
        Agrega columnas de senales al DataFrame OHLCV:
            - sma_short, sma_long: medias moviles
            - raw_signal: 1 (long) o 0 (flat) basado en posicion relativa de SMAs
            - crossover: 1 (golden cross), -1 (death cross), 0 (sin cambio)

        Returns:
            DataFrame enriquecido con columnas de senales.
        """
        df = ohlcv.copy()

        # Calcular SMAs sobre precio ajustado
        df["sma_short"] = df["adj_close"].rolling(window=self.sma_short, min_periods=self.sma_short).mean()
        df["sma_long"] = df["adj_close"].rolling(window=self.sma_long, min_periods=self.sma_long).mean()

        # Signal: 1 cuando SMA_short > SMA_long, 0 en caso contrario
        df["raw_signal"] = 0
        df.loc[df["sma_short"] > df["sma_long"], "raw_signal"] = 1

        # Crossover: detectar cambios de estado (diff del signal)
        df["crossover"] = df["raw_signal"].diff()
        # crossover = 1  -> Golden Cross (BUY)
        # crossover = -1 -> Death Cross (SELL)
        # crossover = 0  -> Sin cambio

        # Limpiar NaN del periodo de calentamiento
        df["crossover"] = df["crossover"].fillna(0).astype(int)

        n_golden = (df["crossover"] == 1).sum()
        n_death = (df["crossover"] == -1).sum()
        logger.info("  Senales generadas: %d Golden Cross, %d Death Cross (SMA %d/%d)",
                     n_golden, n_death, self.sma_short, self.sma_long)

        return df


# ---------------------------------------------------------------------------
# 3. FundamentalFilter -- Validacion Fundamental de Senales
# ---------------------------------------------------------------------------

class FundamentalFilter:
    """
    Filtra senales de compra usando metricas fundamentales corporativas.

    Reglas de validacion (todas deben cumplirse para aprobar un BUY):
        1. EBITDA Growth > umbral minimo (default: 0%)
           -> La empresa debe mostrar crecimiento operativo.
        2. Debt-to-Equity < umbral maximo (default: 3.0)
           -> Apalancamiento controlado (proxy inverso de WACC favorable).

    Mecanica:
        Los datos fundamentales son trimestrales. Para cada fecha de senal,
        se busca el reporte fundamental mas reciente (look-back, sin look-ahead bias).
    """

    def __init__(
        self,
        min_ebitda_growth: float = 0.0,
        max_debt_to_equity: float = 3.0,
        enabled: bool = True,
    ):
        self.min_ebitda_growth = min_ebitda_growth
        self.max_debt_to_equity = max_debt_to_equity
        self.enabled = enabled

    def validate_buy(self, signal_date: pd.Timestamp, fundamentals: pd.DataFrame) -> tuple[bool, str]:
        """
        Valida si una senal de compra pasa el filtro fundamental.

        Args:
            signal_date: Fecha de la senal tecnica.
            fundamentals: DataFrame de ratios fundamentales (index=period_end).

        Returns:
            (aprobado, razon): Tupla con resultado y explicacion.
        """
        if not self.enabled:
            return True, "filtro_desactivado"

        if fundamentals.empty:
            return False, "sin_datos_fundamentales"

        # Look-back: encontrar el reporte mas reciente ANTERIOR a la fecha de senal
        # (evitar look-ahead bias)
        available = fundamentals[fundamentals.index <= signal_date]

        if available.empty:
            return False, "sin_reportes_previos_a_senal"

        latest = available.iloc[-1]

        # Regla 1: EBITDA Growth
        ebitda_growth = latest.get("ebitda_growth")
        if ebitda_growth is None or pd.isna(ebitda_growth):
            # Si no hay dato de crecimiento, verificar que al menos EBITDA sea positivo
            ebitda = latest.get("ebitda")
            if ebitda is None or pd.isna(ebitda) or ebitda <= 0:
                return False, f"ebitda_negativo_o_nulo (period={latest.name.strftime('%Y-%m-%d')})"
        elif ebitda_growth < self.min_ebitda_growth:
            return False, (
                f"ebitda_growth={ebitda_growth:.2f}% < min={self.min_ebitda_growth}% "
                f"(period={latest.name.strftime('%Y-%m-%d')})"
            )

        # Regla 2: Debt-to-Equity
        d2e = latest.get("debt_to_equity")
        if d2e is not None and not pd.isna(d2e) and d2e > self.max_debt_to_equity:
            return False, (
                f"debt_to_equity={d2e:.2f} > max={self.max_debt_to_equity} "
                f"(period={latest.name.strftime('%Y-%m-%d')})"
            )

        return True, (
            f"aprobado: ebitda_growth={ebitda_growth if ebitda_growth and not pd.isna(ebitda_growth) else 'N/A'}, "
            f"d2e={d2e if d2e and not pd.isna(d2e) else 'N/A'} "
            f"(period={latest.name.strftime('%Y-%m-%d')})"
        )


# ---------------------------------------------------------------------------
# 4. BacktestEngine -- Simulacion de Estrategia
# ---------------------------------------------------------------------------

class BacktestEngine:
    """
    Motor de backtesting event-driven sobre datos diarios.

    Flujo por cada barra (dia):
        1. Verificar si hay senal de crossover.
        2. Si BUY: validar con filtro fundamental -> abrir posicion.
        3. Si SELL: cerrar posicion abierta.
        4. Calcular equity diaria.

    Al finalizar:
        - Cerrar posicion abierta al ultimo precio (exit_reason='end_of_period')
        - Calcular metricas de rendimiento
        - Comparar contra Buy & Hold
    """

    def __init__(
        self,
        initial_capital: float = DEFAULT_INITIAL_CAPITAL,
        signal_generator: Optional[SignalGenerator] = None,
        fundamental_filter: Optional[FundamentalFilter] = None,
    ):
        self.initial_capital = initial_capital
        self.signal_gen = signal_generator or SignalGenerator()
        self.fund_filter = fundamental_filter or FundamentalFilter()

    def run(
        self,
        asset_id: int,
        ticker: str,
        ohlcv: pd.DataFrame,
        fundamentals: pd.DataFrame,
    ) -> BacktestResult:
        """
        Ejecuta el backtest completo para un activo.

        Args:
            asset_id: ID del activo en la DB.
            ticker: Simbolo del ticker.
            ohlcv: DataFrame OHLCV con index=date.
            fundamentals: DataFrame de fundamentales con index=period_end.

        Returns:
            BacktestResult con metricas, trades y equity curve.
        """
        logger.info("  Ejecutando backtest para '%s'...", ticker)

        # Generar senales tecnicas
        df = self.signal_gen.generate(ohlcv)

        # Inicializar estado
        capital = self.initial_capital
        position_shares = 0
        position_entry_price = 0.0
        position_entry_date = ""
        trades: list[TradeRecord] = []

        # Equity curve (valor total del portfolio por dia)
        equity_values = []
        equity_dates = []

        # Iterar por cada barra despues del periodo de calentamiento
        warmup = self.signal_gen.sma_long
        trading_df = df.iloc[warmup:]

        for date, row in trading_df.iterrows():
            current_price = row["adj_close"]
            crossover = row["crossover"]

            if position_shares > 0:
                # En posicion: calcular valor actual
                portfolio_value = capital + (position_shares * current_price)
            else:
                portfolio_value = capital

            equity_values.append(portfolio_value)
            equity_dates.append(date)

            # --- Senal de COMPRA ---
            if crossover == 1 and position_shares == 0:
                # Validar con filtro fundamental
                approved, reason = self.fund_filter.validate_buy(
                    pd.Timestamp(date), fundamentals
                )

                if approved:
                    # Comprar con todo el capital disponible
                    position_shares = int(capital // current_price)
                    if position_shares > 0:
                        cost = position_shares * current_price
                        capital -= cost
                        position_entry_price = current_price
                        position_entry_date = pd.Timestamp(date).strftime("%Y-%m-%d")

                        trades.append(TradeRecord(
                            signal_type="BUY",
                            entry_date=position_entry_date,
                            entry_price=round(current_price, 4),
                        ))
                        logger.debug("    BUY  %s @ %.2f (%d shares) | %s",
                                     position_entry_date, current_price, position_shares, reason)
                else:
                    logger.debug("    BUY RECHAZADO %s | %s",
                                 pd.Timestamp(date).strftime("%Y-%m-%d"), reason)

            # --- Senal de VENTA ---
            elif crossover == -1 and position_shares > 0:
                exit_price = current_price
                exit_date = pd.Timestamp(date).strftime("%Y-%m-%d")
                revenue = position_shares * exit_price
                capital += revenue
                trade_return = ((exit_price - position_entry_price) / position_entry_price) * 100

                # Completar el ultimo trade
                if trades and trades[-1].exit_date is None:
                    trades[-1].exit_date = exit_date
                    trades[-1].exit_price = round(exit_price, 4)
                    trades[-1].return_pct = round(trade_return, 4)
                    trades[-1].exit_reason = "signal"

                logger.debug("    SELL %s @ %.2f | return=%.2f%%",
                             exit_date, exit_price, trade_return)

                position_shares = 0
                position_entry_price = 0.0

                # Recalcular equity tras venta
                portfolio_value = capital
                equity_values[-1] = portfolio_value

        # --- Cerrar posicion abierta al final del periodo ---
        if position_shares > 0 and len(trading_df) > 0:
            last_price = trading_df.iloc[-1]["adj_close"]
            last_date = pd.Timestamp(trading_df.index[-1]).strftime("%Y-%m-%d")
            revenue = position_shares * last_price
            capital += revenue
            trade_return = ((last_price - position_entry_price) / position_entry_price) * 100

            if trades and trades[-1].exit_date is None:
                trades[-1].exit_date = last_date
                trades[-1].exit_price = round(last_price, 4)
                trades[-1].return_pct = round(trade_return, 4)
                trades[-1].exit_reason = "end_of_period"

            portfolio_value = capital
            if equity_values:
                equity_values[-1] = portfolio_value
            position_shares = 0

        # --- Construir equity curve ---
        equity_curve = pd.Series(equity_values, index=equity_dates, name="equity")

        # --- Calcular metricas ---
        result = self._compute_metrics(
            asset_id=asset_id,
            ticker=ticker,
            trades=trades,
            equity_curve=equity_curve,
            ohlcv=trading_df,
            final_capital=capital,
        )

        return result

    def _compute_metrics(
        self,
        asset_id: int,
        ticker: str,
        trades: list[TradeRecord],
        equity_curve: pd.Series,
        ohlcv: pd.DataFrame,
        final_capital: float,
    ) -> BacktestResult:
        """Calcula todas las metricas de rendimiento del backtest."""

        # --- Rendimiento de la estrategia ---
        total_return_pct = ((final_capital - self.initial_capital) / self.initial_capital) * 100

        # --- Buy & Hold benchmark ---
        if len(ohlcv) >= 2:
            first_price = ohlcv.iloc[0]["adj_close"]
            last_price = ohlcv.iloc[-1]["adj_close"]
            buy_hold_return_pct = ((last_price - first_price) / first_price) * 100
        else:
            buy_hold_return_pct = 0.0

        # --- Alpha ---
        alpha_pct = total_return_pct - buy_hold_return_pct

        # --- Max Drawdown ---
        max_drawdown_pct = self._compute_max_drawdown(equity_curve)

        # --- Sharpe Ratio (anualizado) ---
        sharpe_ratio = self._compute_sharpe_ratio(equity_curve)

        # --- Estadisticas de trades ---
        completed_trades = [t for t in trades if t.exit_date is not None]
        n_trades = len(completed_trades)

        win_trades = [t for t in completed_trades if t.return_pct is not None and t.return_pct > 0]
        win_rate = (len(win_trades) / n_trades * 100) if n_trades > 0 else 0.0

        returns = [t.return_pct for t in completed_trades if t.return_pct is not None]
        avg_return = sum(returns) / len(returns) if returns else 0.0
        best_trade = max(returns) if returns else 0.0
        worst_trade = min(returns) if returns else 0.0

        # Dias en el mercado
        days_in_market = 0
        for t in completed_trades:
            if t.entry_date and t.exit_date:
                entry = pd.Timestamp(t.entry_date)
                exit_ = pd.Timestamp(t.exit_date)
                days_in_market += (exit_ - entry).days

        # Fechas
        start_date = ohlcv.index[0].strftime("%Y-%m-%d") if len(ohlcv) > 0 else ""
        end_date = ohlcv.index[-1].strftime("%Y-%m-%d") if len(ohlcv) > 0 else ""

        # Parametros
        parameters = {
            "sma_short": self.signal_gen.sma_short,
            "sma_long": self.signal_gen.sma_long,
            "initial_capital": self.initial_capital,
            "fundamental_filter": self.fund_filter.enabled,
            "min_ebitda_growth": self.fund_filter.min_ebitda_growth,
            "max_debt_to_equity": self.fund_filter.max_debt_to_equity,
        }

        result = BacktestResult(
            asset_id=asset_id,
            ticker=ticker,
            strategy_name="SMA_Crossover_Fundamental",
            parameters=parameters,
            start_date=start_date,
            end_date=end_date,
            total_return_pct=round(total_return_pct, 4),
            buy_hold_return_pct=round(buy_hold_return_pct, 4),
            alpha_pct=round(alpha_pct, 4),
            max_drawdown_pct=round(max_drawdown_pct, 4),
            sharpe_ratio=round(sharpe_ratio, 4),
            total_trades=n_trades,
            win_rate=round(win_rate, 2),
            avg_trade_return=round(avg_return, 4),
            best_trade_pct=round(best_trade, 4),
            worst_trade_pct=round(worst_trade, 4),
            total_days_in_market=days_in_market,
            trades=trades,
            equity_curve=equity_curve,
        )

        return result

    @staticmethod
    def _compute_max_drawdown(equity: pd.Series) -> float:
        """Calcula el maximo drawdown porcentual de la equity curve."""
        if equity.empty or len(equity) < 2:
            return 0.0

        cummax = equity.cummax()
        drawdown = (equity - cummax) / cummax * 100
        return round(abs(drawdown.min()), 4)

    @staticmethod
    def _compute_sharpe_ratio(equity: pd.Series) -> float:
        """
        Calcula el Sharpe Ratio anualizado.

        Sharpe = (Rp - Rf) / sigma_p
        donde:
            Rp = retorno anualizado del portfolio
            Rf = tasa libre de riesgo
            sigma_p = volatilidad anualizada de los retornos diarios
        """
        if equity.empty or len(equity) < 2:
            return 0.0

        # Retornos diarios logaritmicos
        daily_returns = np.log(equity / equity.shift(1)).dropna()

        if daily_returns.std() == 0:
            return 0.0

        # Anualizar
        mean_daily = daily_returns.mean()
        std_daily = daily_returns.std()

        annualized_return = mean_daily * TRADING_DAYS_PER_YEAR
        annualized_vol = std_daily * np.sqrt(TRADING_DAYS_PER_YEAR)

        sharpe = (annualized_return - RISK_FREE_RATE) / annualized_vol
        return round(float(sharpe), 4)


# ---------------------------------------------------------------------------
# 5. ResultsPersister -- Persistencia en SQLite
# ---------------------------------------------------------------------------

class ResultsPersister:
    """Persiste resultados de backtests en la base de datos."""

    def __init__(self, db_path: Path = DB_PATH):
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute("PRAGMA foreign_keys=ON")

    def close(self):
        self.conn.close()

    def save(self, result: BacktestResult) -> int:
        """
        Persiste un BacktestResult en backtest_runs y backtest_trades.
        Retorna el run_id generado.
        """
        # Insertar en backtest_runs
        cursor = self.conn.execute(
            """
            INSERT INTO backtest_runs
                (asset_id, strategy_name, parameters, start_date, end_date,
                 total_return_pct, buy_hold_return_pct, alpha_pct,
                 max_drawdown_pct, sharpe_ratio, total_trades)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.asset_id,
                result.strategy_name,
                json.dumps(result.parameters),
                result.start_date,
                result.end_date,
                result.total_return_pct,
                result.buy_hold_return_pct,
                result.alpha_pct,
                result.max_drawdown_pct,
                result.sharpe_ratio,
                result.total_trades,
            ),
        )
        run_id = cursor.lastrowid

        # Insertar trades
        for trade in result.trades:
            self.conn.execute(
                """
                INSERT INTO backtest_trades
                    (run_id, signal_type, entry_date, entry_price,
                     exit_date, exit_price, return_pct, exit_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    trade.signal_type,
                    trade.entry_date,
                    trade.entry_price,
                    trade.exit_date,
                    trade.exit_price,
                    trade.return_pct,
                    trade.exit_reason,
                ),
            )

        self.conn.commit()
        logger.info("  Resultados persistidos: run_id=%d (%d trades)", run_id, len(result.trades))
        return run_id

    def list_runs(self, limit: int = 20) -> list[dict]:
        """Lista las ultimas ejecuciones de backtest."""
        cursor = self.conn.execute(
            """
            SELECT r.id, a.ticker, r.strategy_name, r.start_date, r.end_date,
                   r.total_return_pct, r.buy_hold_return_pct, r.alpha_pct,
                   r.max_drawdown_pct, r.sharpe_ratio, r.total_trades,
                   r.executed_at
            FROM backtest_runs r
            JOIN assets a ON r.asset_id = a.id
            ORDER BY r.executed_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        cols = [desc[0] for desc in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]


# ---------------------------------------------------------------------------
# Reporte por consola
# ---------------------------------------------------------------------------

def print_report(result: BacktestResult) -> None:
    """Imprime un reporte detallado del backtest en consola."""
    print("\n" + "=" * 70)
    print(f"  BACKTEST REPORT: {result.ticker}")
    print(f"  Strategy: {result.strategy_name}")
    print("=" * 70)

    print(f"\n  [PARAMS]")
    for k, v in result.parameters.items():
        print(f"     {k:25s}: {v}")

    print(f"\n  [PERIOD]")
    print(f"     Start:                    {result.start_date}")
    print(f"     End:                      {result.end_date}")

    print(f"\n  [PERFORMANCE]")
    print(f"     Strategy Return:          {result.total_return_pct:>10.2f}%")
    print(f"     Buy & Hold Return:        {result.buy_hold_return_pct:>10.2f}%")
    alpha_sign = "+" if result.alpha_pct >= 0 else ""
    print(f"     Alpha:                    {alpha_sign}{result.alpha_pct:>9.2f}%")
    print(f"     Sharpe Ratio:             {result.sharpe_ratio:>10.4f}")
    print(f"     Max Drawdown:             {result.max_drawdown_pct:>10.2f}%")

    print(f"\n  [TRADES]")
    print(f"     Total Trades:             {result.total_trades:>10d}")
    print(f"     Win Rate:                 {result.win_rate:>10.1f}%")
    print(f"     Avg Trade Return:         {result.avg_trade_return:>10.2f}%")
    print(f"     Best Trade:               {result.best_trade_pct:>10.2f}%")
    print(f"     Worst Trade:              {result.worst_trade_pct:>10.2f}%")
    print(f"     Days in Market:           {result.total_days_in_market:>10d}")

    if result.trades:
        print(f"\n  [TRADE LOG]")
        print(f"     {'#':>3s}  {'Type':5s}  {'Entry Date':12s}  {'Entry $':>10s}  "
              f"{'Exit Date':12s}  {'Exit $':>10s}  {'Return':>8s}  {'Reason'}")
        print(f"     {'---':>3s}  {'-----':5s}  {'----------':12s}  {'--------':>10s}  "
              f"{'----------':12s}  {'--------':>10s}  {'------':>8s}  {'------'}")
        for i, t in enumerate(result.trades, 1):
            exit_d = t.exit_date or "-"
            exit_p = f"{t.exit_price:.2f}" if t.exit_price else "-"
            ret = f"{t.return_pct:.2f}%" if t.return_pct is not None else "-"
            reason = t.exit_reason or "-"
            print(f"     {i:>3d}  {t.signal_type:5s}  {t.entry_date:12s}  "
                  f"{t.entry_price:>10.2f}  {exit_d:12s}  {exit_p:>10s}  "
                  f"{ret:>8s}  {reason}")

    # Veredicto
    print(f"\n  [VERDICT]")
    if result.alpha_pct > 0:
        print(f"     >> La estrategia SUPERA al Buy & Hold por {result.alpha_pct:.2f}pp")
    elif result.alpha_pct < 0:
        print(f"     >> La estrategia PIERDE frente al Buy & Hold por {abs(result.alpha_pct):.2f}pp")
    else:
        print(f"     >> La estrategia IGUALA al Buy & Hold")

    print("=" * 70 + "\n")


def print_runs_table(runs: list[dict]) -> None:
    """Imprime tabla de backtests anteriores."""
    if not runs:
        print("\n  No hay backtests registrados.\n")
        return

    print("\n" + "=" * 100)
    print("  HISTORIAL DE BACKTESTS")
    print("=" * 100)
    print(f"  {'ID':>4s}  {'Ticker':6s}  {'Strategy':30s}  {'Period':25s}  "
          f"{'Return':>8s}  {'B&H':>8s}  {'Alpha':>8s}  {'Sharpe':>7s}  {'Trades':>6s}")
    print(f"  {'----':>4s}  {'------':6s}  {'-----':30s}  {'------':25s}  "
          f"{'------':>8s}  {'---':>8s}  {'-----':>8s}  {'------':>7s}  {'------':>6s}")

    for r in runs:
        period = f"{r['start_date']} -> {r['end_date']}"
        alpha_s = f"{r['alpha_pct']:+.2f}%"
        print(f"  {r['id']:>4d}  {r['ticker']:6s}  {r['strategy_name']:30s}  {period:25s}  "
              f"{r['total_return_pct']:>7.2f}%  {r['buy_hold_return_pct']:>7.2f}%  "
              f"{alpha_s:>8s}  {r['sharpe_ratio']:>7.4f}  {r['total_trades']:>6d}")

    print("=" * 100 + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Motor de Backtesting Hibrido (Tecnico + Fundamental)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--ticker", type=str, default=None,
        help="Ticker especifico a evaluar (default: todos los activos)",
    )
    parser.add_argument(
        "--sma-short", type=int, default=DEFAULT_SMA_SHORT,
        help=f"Periodo de la SMA corta (default: {DEFAULT_SMA_SHORT})",
    )
    parser.add_argument(
        "--sma-long", type=int, default=DEFAULT_SMA_LONG,
        help=f"Periodo de la SMA larga (default: {DEFAULT_SMA_LONG})",
    )
    parser.add_argument(
        "--capital", type=float, default=DEFAULT_INITIAL_CAPITAL,
        help=f"Capital inicial (default: {DEFAULT_INITIAL_CAPITAL:,.0f})",
    )
    parser.add_argument(
        "--no-fundamental-filter", action="store_true",
        help="Desactivar filtro fundamental (solo senales tecnicas)",
    )
    parser.add_argument(
        "--min-ebitda-growth", type=float, default=0.0,
        help="Umbral minimo de EBITDA growth %% para filtro fundamental (default: 0)",
    )
    parser.add_argument(
        "--max-debt-to-equity", type=float, default=3.0,
        help="Umbral maximo de Debt/Equity para filtro fundamental (default: 3.0)",
    )
    parser.add_argument(
        "--list", action="store_true", dest="list_runs",
        help="Listar backtests anteriores y salir",
    )
    parser.add_argument(
        "--db-path", type=str, default=None,
        help="Ruta personalizada para la base de datos",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Mostrar logs detallados (nivel DEBUG)",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger("engine").setLevel(logging.DEBUG)

    db_path = Path(args.db_path) if args.db_path else DB_PATH

    if not db_path.exists():
        logger.error("Base de datos no encontrada: %s", db_path)
        logger.error("Ejecuta primero: python init_db.py")
        return 1

    # --- Listar backtests anteriores ---
    if args.list_runs:
        persister = ResultsPersister(db_path)
        runs = persister.list_runs()
        print_runs_table(runs)
        persister.close()
        return 0

    # --- Configurar componentes ---
    loader = DataLoader(db_path)
    signal_gen = SignalGenerator(sma_short=args.sma_short, sma_long=args.sma_long)
    fund_filter = FundamentalFilter(
        min_ebitda_growth=args.min_ebitda_growth,
        max_debt_to_equity=args.max_debt_to_equity,
        enabled=not args.no_fundamental_filter,
    )
    engine = BacktestEngine(
        initial_capital=args.capital,
        signal_generator=signal_gen,
        fundamental_filter=fund_filter,
    )
    persister = ResultsPersister(db_path)

    # --- Determinar activos a evaluar ---
    if args.ticker:
        asset_id = loader.get_asset_id(args.ticker)
        if asset_id is None:
            logger.error("Ticker '%s' no encontrado en la base de datos.", args.ticker)
            loader.close()
            return 1
        assets = [{"id": asset_id, "ticker": args.ticker.upper()}]
    else:
        assets = loader.get_all_assets()

    print("\n" + "=" * 70)
    print("  MOTOR DE BACKTESTING -- EJECUCION")
    print("=" * 70)
    print(f"  Activos:  {', '.join(a['ticker'] for a in assets)}")
    print(f"  SMA:      {args.sma_short}/{args.sma_long}")
    print(f"  Capital:  ${args.capital:,.0f}")
    print(f"  Filtro:   {'ON' if not args.no_fundamental_filter else 'OFF'}")
    print("=" * 70)

    # --- Ejecutar backtest por activo ---
    results: list[BacktestResult] = []

    for asset in assets:
        asset_id = asset["id"]
        ticker = asset["ticker"]

        logger.info("Procesando: %s", ticker)

        # Cargar datos
        ohlcv = loader.load_ohlcv(asset_id)
        fundamentals = loader.load_fundamentals(asset_id, period_type="quarterly")

        if ohlcv.empty:
            logger.warning("Sin datos OHLCV para '%s', saltando.", ticker)
            continue

        if len(ohlcv) < args.sma_long + 10:
            logger.warning(
                "Insuficientes datos para '%s' (%d filas, minimo %d). Saltando.",
                ticker, len(ohlcv), args.sma_long + 10
            )
            continue

        # Ejecutar backtest
        result = engine.run(asset_id, ticker, ohlcv, fundamentals)

        # Persistir resultados
        run_id = persister.save(result)

        # Imprimir reporte
        print_report(result)

        results.append(result)

    # --- Resumen comparativo ---
    if len(results) > 1:
        print("\n" + "=" * 70)
        print("  RESUMEN COMPARATIVO")
        print("=" * 70)
        print(f"  {'Ticker':6s}  {'Return':>9s}  {'B&H':>9s}  {'Alpha':>9s}  "
              f"{'Sharpe':>8s}  {'MaxDD':>8s}  {'WinRate':>8s}  {'Trades':>6s}")
        print(f"  {'------':6s}  {'------':>9s}  {'---':>9s}  {'-----':>9s}  "
              f"{'------':>8s}  {'-----':>8s}  {'-------':>8s}  {'------':>6s}")
        for r in results:
            print(f"  {r.ticker:6s}  {r.total_return_pct:>8.2f}%  {r.buy_hold_return_pct:>8.2f}%  "
                  f"{r.alpha_pct:>+8.2f}%  {r.sharpe_ratio:>8.4f}  "
                  f"{r.max_drawdown_pct:>7.2f}%  {r.win_rate:>7.1f}%  {r.total_trades:>6d}")
        print("=" * 70 + "\n")

    # Cleanup
    loader.close()
    persister.close()

    logger.info("[OK] Backtest completado para %d activo(s).", len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
