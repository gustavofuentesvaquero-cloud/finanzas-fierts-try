#!/usr/bin/env python3
"""
init_db.py — Inicialización del Motor de Backtesting
=====================================================
Crea el esquema SQLite y ejecuta la carga inicial de datos históricos (5 años)
para los tickers de prueba desde Yahoo Finance.

Diseñado para ser idempotente: puede ejecutarse múltiples veces sin duplicar datos
gracias a las restricciones UNIQUE y la estrategia INSERT OR IGNORE.

Uso:
    python init_db.py                    # Carga los 3 tickers por defecto
    python init_db.py --tickers AAPL MSFT GOOGL TSLA  # Tickers personalizados
    python init_db.py --years 10         # Ventana temporal personalizada
"""

import argparse
import logging
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

DB_DIR = Path(__file__).resolve().parent / "data"
DB_PATH = DB_DIR / "backtesting.db"

DEFAULT_TICKERS = ["AAPL", "MSFT", "GOOGL"]
DEFAULT_YEARS = 5

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("init_db")


# ---------------------------------------------------------------------------
# Esquema DDL
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
-- ==========================================================================
-- Tabla maestra de activos
-- ==========================================================================
CREATE TABLE IF NOT EXISTS assets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT    NOT NULL UNIQUE,
    name        TEXT,
    sector      TEXT,
    industry    TEXT,
    currency    TEXT    DEFAULT 'USD',
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

-- ==========================================================================
-- Precios históricos OHLCV diarios
-- Índice compuesto (asset_id, date) para:
--   1. Queries de rango temporal eficientes
--   2. Idempotencia en la ingesta (INSERT OR IGNORE)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS ohlcv_daily (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id    INTEGER NOT NULL,
    date        TEXT    NOT NULL,
    open        REAL    NOT NULL,
    high        REAL    NOT NULL,
    low         REAL    NOT NULL,
    close       REAL    NOT NULL,
    adj_close   REAL    NOT NULL,
    volume      INTEGER NOT NULL,
    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE,
    UNIQUE (asset_id, date)
);

CREATE INDEX IF NOT EXISTS idx_ohlcv_asset_date
    ON ohlcv_daily(asset_id, date);

-- ==========================================================================
-- Ratios fundamentales corporativos
-- Granularidad: trimestral o anual (period_type)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS fundamental_ratios (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id        INTEGER NOT NULL,
    period_end      TEXT    NOT NULL,
    period_type     TEXT    NOT NULL CHECK (period_type IN ('quarterly', 'annual')),
    -- Métricas primarias de filtro
    ebitda          REAL,
    ebitda_growth   REAL,
    revenue         REAL,
    net_income      REAL,
    -- Métricas de coste de capital y eficiencia
    wacc            REAL,
    roe             REAL,
    debt_to_equity  REAL,
    current_ratio   REAL,
    -- Métricas de valoración
    pe_ratio        REAL,
    pb_ratio        REAL,
    fetched_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE,
    UNIQUE (asset_id, period_end, period_type)
);

CREATE INDEX IF NOT EXISTS idx_fundamental_asset_period
    ON fundamental_ratios(asset_id, period_end);

-- ==========================================================================
-- Registro de ejecuciones de backtest
-- Cada fila = una simulación completa con sus parámetros y resultados.
-- ==========================================================================
CREATE TABLE IF NOT EXISTS backtest_runs (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id                INTEGER NOT NULL,
    strategy_name           TEXT    NOT NULL,
    parameters              TEXT,           -- JSON con parámetros de la estrategia
    start_date              TEXT    NOT NULL,
    end_date                TEXT    NOT NULL,
    -- Resultados de rendimiento
    total_return_pct        REAL,
    buy_hold_return_pct     REAL,
    alpha_pct               REAL,           -- total_return - buy_hold
    max_drawdown_pct        REAL,
    sharpe_ratio            REAL,
    total_trades            INTEGER DEFAULT 0,
    executed_at             TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE
);

-- ==========================================================================
-- Log de operaciones individuales dentro de un backtest
-- ==========================================================================
CREATE TABLE IF NOT EXISTS backtest_trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL,
    signal_type     TEXT    NOT NULL CHECK (signal_type IN ('BUY', 'SELL', 'SHORT', 'COVER')),
    entry_date      TEXT    NOT NULL,
    entry_price     REAL    NOT NULL,
    exit_date       TEXT,
    exit_price      REAL,
    return_pct      REAL,
    exit_reason     TEXT,                   -- 'signal', 'stop_loss', 'take_profit', 'end_of_period'
    FOREIGN KEY (run_id) REFERENCES backtest_runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_trades_run
    ON backtest_trades(run_id);
"""


# ---------------------------------------------------------------------------
# Funciones de inicialización de base de datos
# ---------------------------------------------------------------------------

def create_database_at(db_path: Path = DB_PATH, db_dir: Path = DB_DIR) -> sqlite3.Connection:
    """Crea el directorio de datos y la base de datos con el esquema completo."""
    db_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")          # Write-Ahead Logging para concurrencia
    conn.execute("PRAGMA foreign_keys=ON")            # Activar integridad referencial
    conn.execute("PRAGMA busy_timeout=5000")          # 5s de espera ante bloqueo
    conn.executescript(SCHEMA_SQL)
    conn.commit()

    logger.info("Base de datos creada/verificada en: %s", db_path)
    return conn


# ---------------------------------------------------------------------------
# Registro de activos
# ---------------------------------------------------------------------------

def register_asset(conn: sqlite3.Connection, ticker: str) -> int:
    """
    Registra un ticker en la tabla assets y retorna su id.
    Si ya existe, retorna el id existente.
    Enriquece con metadatos del ticker desde yfinance.
    """
    cursor = conn.execute("SELECT id FROM assets WHERE ticker = ?", (ticker,))
    row = cursor.fetchone()
    if row:
        logger.info("  Asset '%s' ya registrado (id=%d)", ticker, row[0])
        return row[0]

    # Obtener metadatos del activo
    yf_ticker = yf.Ticker(ticker)
    info = yf_ticker.info or {}

    name = info.get("longName") or info.get("shortName") or ticker
    sector = info.get("sector")
    industry = info.get("industry")
    currency = info.get("currency", "USD")

    cursor = conn.execute(
        """
        INSERT INTO assets (ticker, name, sector, industry, currency)
        VALUES (?, ?, ?, ?, ?)
        """,
        (ticker, name, sector, industry, currency),
    )
    conn.commit()
    asset_id = cursor.lastrowid
    logger.info("  Asset registrado: '%s' -> id=%d | %s | %s", ticker, asset_id, sector, industry)
    return asset_id


# ---------------------------------------------------------------------------
# Ingesta de datos OHLCV
# ---------------------------------------------------------------------------

def ingest_ohlcv(conn: sqlite3.Connection, ticker: str, asset_id: int, years: int) -> int:
    """
    Descarga datos OHLCV diarios de los últimos `years` años desde Yahoo Finance
    y los inserta en la tabla ohlcv_daily.

    Retorna el número de filas insertadas (nuevas).
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=years * 365)

    logger.info("  Descargando OHLCV para '%s': %s -> %s ...",
                ticker, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))

    df = yf.download(
        ticker,
        start=start_date.strftime("%Y-%m-%d"),
        end=end_date.strftime("%Y-%m-%d"),
        auto_adjust=False,
        progress=False,
    )

    if df.empty:
        logger.warning("  [!] No se obtuvieron datos OHLCV para '%s'", ticker)
        return 0

    # yfinance puede devolver MultiIndex si se pasa una lista; aplanar si es necesario
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Preparar datos para inserción masiva
    records = []
    for date_idx, row in df.iterrows():
        date_str = pd.Timestamp(date_idx).strftime("%Y-%m-%d")
        try:
            records.append((
                asset_id,
                date_str,
                round(float(row["Open"]), 6),
                round(float(row["High"]), 6),
                round(float(row["Low"]), 6),
                round(float(row["Close"]), 6),
                round(float(row.get("Adj Close", row["Close"])), 6),
                int(row["Volume"]),
            ))
        except (ValueError, TypeError) as e:
            logger.debug("  Fila descartada (%s): %s", date_str, e)
            continue

    # INSERT OR IGNORE para idempotencia
    cursor = conn.executemany(
        """
        INSERT OR IGNORE INTO ohlcv_daily
            (asset_id, date, open, high, low, close, adj_close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        records,
    )
    conn.commit()
    inserted = cursor.rowcount if cursor.rowcount > 0 else len(records)

    logger.info("  [OK] OHLCV '%s': %d filas descargadas, %d insertadas", ticker, len(records), inserted)
    return inserted


# ---------------------------------------------------------------------------
# Ingesta de datos fundamentales
# ---------------------------------------------------------------------------

def _safe_float(value) -> Optional[float]:
    """Convierte un valor a float de forma segura, retornando None si no es posible."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return round(float(value), 6)
    except (ValueError, TypeError):
        return None


def _compute_ebitda_growth(ebitda_series: pd.Series) -> pd.Series:
    """
    Calcula el crecimiento porcentual del EBITDA período a período.
    La serie debe estar ordenada cronológicamente (más antiguo primero).
    """
    growth = ebitda_series.pct_change() * 100
    return growth


def ingest_fundamentals(conn: sqlite3.Connection, ticker: str, asset_id: int) -> int:
    """
    Descarga ratios fundamentales trimestrales y anuales desde Yahoo Finance
    y los almacena en fundamental_ratios.

    Retorna el número de registros insertados.
    """
    yf_ticker = yf.Ticker(ticker)
    info = yf_ticker.info or {}
    total_inserted = 0

    # --- Datos trimestrales ---
    try:
        quarterly_financials = yf_ticker.quarterly_financials
        quarterly_balance = yf_ticker.quarterly_balance_sheet
        quarterly_income = yf_ticker.quarterly_income_stmt

        if quarterly_financials is not None and not quarterly_financials.empty:
            records = _build_fundamental_records(
                asset_id=asset_id,
                financials=quarterly_financials,
                balance_sheet=quarterly_balance,
                income_stmt=quarterly_income,
                info=info,
                period_type="quarterly",
            )
            total_inserted += _insert_fundamental_records(conn, records)
            logger.info("  [OK] Fundamentales trimestrales '%s': %d registros", ticker, len(records))
    except Exception as e:
        logger.warning("  [!] Error obteniendo datos trimestrales de '%s': %s", ticker, e)

    # --- Datos anuales ---
    try:
        annual_financials = yf_ticker.financials
        annual_balance = yf_ticker.balance_sheet
        annual_income = yf_ticker.income_stmt

        if annual_financials is not None and not annual_financials.empty:
            records = _build_fundamental_records(
                asset_id=asset_id,
                financials=annual_financials,
                balance_sheet=annual_balance,
                income_stmt=annual_income,
                info=info,
                period_type="annual",
            )
            total_inserted += _insert_fundamental_records(conn, records)
            logger.info("  [OK] Fundamentales anuales '%s': %d registros", ticker, len(records))
    except Exception as e:
        logger.warning("  [!] Error obteniendo datos anuales de '%s': %s", ticker, e)

    return total_inserted


def _get_row_value(df: Optional[pd.DataFrame], row_label: str, col) -> Optional[float]:
    """Extrae un valor de un DataFrame de yfinance por nombre de fila y columna."""
    if df is None or df.empty:
        return None
    # yfinance usa nombres de fila como 'EBITDA', 'Total Revenue', etc.
    # Los nombres pueden variar ligeramente; probamos varias variantes
    labels = [row_label]
    if row_label == "EBITDA":
        labels.extend(["Ebitda", "Normalized EBITDA"])
    elif row_label == "Total Revenue":
        labels.extend(["Revenue", "Total Revenue"])
    elif row_label == "Net Income":
        labels.extend(["Net Income Common Stockholders", "Net Income From Continuing Operations"])
    elif row_label == "Total Debt":
        labels.extend(["Total Debt", "Long Term Debt"])
    elif row_label == "Stockholders Equity":
        labels.extend(["Total Stockholder Equity", "Stockholders Equity",
                        "Common Stock Equity", "Total Equity Gross Minority Interest"])
    elif row_label == "Current Assets":
        labels.extend(["Total Current Assets", "Current Assets"])
    elif row_label == "Current Liabilities":
        labels.extend(["Total Current Liabilities", "Current Liabilities"])

    for label in labels:
        if label in df.index:
            try:
                val = df.loc[label, col]
                return _safe_float(val)
            except (KeyError, IndexError):
                continue
    return None


def _build_fundamental_records(
    asset_id: int,
    financials: pd.DataFrame,
    balance_sheet: Optional[pd.DataFrame],
    income_stmt: Optional[pd.DataFrame],
    info: dict,
    period_type: str,
) -> list[tuple]:
    """
    Construye registros de fundamentales a partir de los DataFrames de yfinance.
    Calcula métricas derivadas (ebitda_growth, roe, debt_to_equity, current_ratio).
    """
    records = []

    # Ordenar columnas cronológicamente (más antiguo primero)
    cols = sorted(financials.columns)

    # Pre-calcular EBITDA por período para computar crecimiento
    ebitda_values = {}
    for col in cols:
        ebitda_values[col] = _get_row_value(financials, "EBITDA", col)

    # Calcular crecimiento del EBITDA
    ebitda_series = pd.Series(ebitda_values)
    ebitda_growth_series = _compute_ebitda_growth(ebitda_series)

    for col in cols:
        period_end = pd.Timestamp(col).strftime("%Y-%m-%d")

        ebitda = ebitda_values.get(col)
        ebitda_growth = _safe_float(ebitda_growth_series.get(col))
        revenue = _get_row_value(financials, "Total Revenue", col)
        net_income = _get_row_value(income_stmt, "Net Income", col) if income_stmt is not None else None

        # Métricas de balance
        total_debt = _get_row_value(balance_sheet, "Total Debt", col) if balance_sheet is not None else None
        stockholders_equity = _get_row_value(balance_sheet, "Stockholders Equity", col) if balance_sheet is not None else None
        current_assets = _get_row_value(balance_sheet, "Current Assets", col) if balance_sheet is not None else None
        current_liabilities = _get_row_value(balance_sheet, "Current Liabilities", col) if balance_sheet is not None else None

        # Ratios derivados
        roe = None
        if net_income is not None and stockholders_equity is not None and stockholders_equity != 0:
            roe = round((net_income / stockholders_equity) * 100, 4)

        debt_to_equity = None
        if total_debt is not None and stockholders_equity is not None and stockholders_equity != 0:
            debt_to_equity = round(total_debt / stockholders_equity, 4)

        current_ratio = None
        if current_assets is not None and current_liabilities is not None and current_liabilities != 0:
            current_ratio = round(current_assets / current_liabilities, 4)

        # WACC y ratios de valoración desde info (estáticos, mismos para todos los períodos)
        wacc = _safe_float(info.get("wacc"))
        pe_ratio = _safe_float(info.get("trailingPE") or info.get("forwardPE"))
        pb_ratio = _safe_float(info.get("priceToBook"))

        records.append((
            asset_id,
            period_end,
            period_type,
            _safe_float(ebitda),
            ebitda_growth,
            _safe_float(revenue),
            _safe_float(net_income),
            wacc,
            roe,
            debt_to_equity,
            current_ratio,
            pe_ratio,
            pb_ratio,
        ))

    return records


def _insert_fundamental_records(conn: sqlite3.Connection, records: list[tuple]) -> int:
    """Inserta registros fundamentales con idempotencia (INSERT OR IGNORE)."""
    cursor = conn.executemany(
        """
        INSERT OR IGNORE INTO fundamental_ratios
            (asset_id, period_end, period_type,
             ebitda, ebitda_growth, revenue, net_income,
             wacc, roe, debt_to_equity, current_ratio,
             pe_ratio, pb_ratio)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        records,
    )
    conn.commit()
    return cursor.rowcount if cursor.rowcount > 0 else len(records)


# ---------------------------------------------------------------------------
# Validación post-ingesta
# ---------------------------------------------------------------------------

def print_summary(conn: sqlite3.Connection, db_path: Path = DB_PATH) -> None:
    """Imprime un resumen de los datos cargados en la base de datos."""
    print("\n" + "=" * 70)
    print("  RESUMEN DE CARGA INICIAL")
    print("=" * 70)

    # Activos
    cursor = conn.execute("SELECT COUNT(*) FROM assets")
    n_assets = cursor.fetchone()[0]

    cursor = conn.execute("SELECT ticker, name, sector FROM assets ORDER BY ticker")
    assets = cursor.fetchall()

    print(f"\n  [ASSETS] Activos registrados: {n_assets}")
    for ticker, name, sector in assets:
        print(f"     * {ticker:6s} | {name or 'N/A':40s} | {sector or 'N/A'}")

    # OHLCV por activo
    print(f"\n  [OHLCV] Datos OHLCV diarios:")
    cursor = conn.execute("""
        SELECT a.ticker,
               COUNT(o.id) as rows,
               MIN(o.date) as first_date,
               MAX(o.date) as last_date
        FROM assets a
        LEFT JOIN ohlcv_daily o ON a.id = o.asset_id
        GROUP BY a.ticker
        ORDER BY a.ticker
    """)
    for ticker, rows, first_date, last_date in cursor.fetchall():
        print(f"     * {ticker:6s} | {rows:>6,} filas | {first_date} -> {last_date}")

    # Fundamentales por activo
    print(f"\n  [FUNDAMENTALS] Datos fundamentales:")
    cursor = conn.execute("""
        SELECT a.ticker,
               f.period_type,
               COUNT(f.id) as rows
        FROM assets a
        LEFT JOIN fundamental_ratios f ON a.id = f.asset_id
        GROUP BY a.ticker, f.period_type
        ORDER BY a.ticker, f.period_type
    """)
    for ticker, period_type, rows in cursor.fetchall():
        pt = period_type or "N/A"
        print(f"     * {ticker:6s} | {pt:10s} | {rows:>3} registros")

    # Tamaño de la DB
    db_size_mb = db_path.stat().st_size / (1024 * 1024)
    print(f"\n  [DB] Tamano de la base de datos: {db_size_mb:.2f} MB")
    print(f"  [DB] Ubicacion: {db_path}")
    print("=" * 70 + "\n")


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Inicializa la base de datos del Motor de Backtesting con datos de Yahoo Finance.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=DEFAULT_TICKERS,
        help=f"Lista de tickers a cargar (default: {', '.join(DEFAULT_TICKERS)})",
    )
    parser.add_argument(
        "--years",
        type=int,
        default=DEFAULT_YEARS,
        help=f"Años de datos históricos a descargar (default: {DEFAULT_YEARS})",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Ruta personalizada para la base de datos",
    )
    args = parser.parse_args()

    # Determinar rutas efectivas sin usar global
    effective_db_path = Path(args.db_path) if args.db_path else DB_PATH
    effective_db_dir = effective_db_path.parent

    tickers = [t.upper() for t in args.tickers]
    years = args.years

    print("\n" + "=" * 70)
    print("  MOTOR DE BACKTESTING -- INICIALIZACION DE BASE DE DATOS")
    print("=" * 70)
    print(f"  Tickers:  {', '.join(tickers)}")
    print(f"  Ventana:  {years} anos")
    print(f"  DB:       {effective_db_path}")
    print("=" * 70 + "\n")

    # 1. Crear esquema
    logger.info("Paso 1/3: Creando esquema de base de datos...")
    conn = create_database_at(effective_db_path, effective_db_dir)

    # 2. Procesar cada ticker
    for i, ticker in enumerate(tickers, 1):
        logger.info("Paso 2/3: Procesando ticker %d/%d: %s", i, len(tickers), ticker)

        # 2a. Registrar activo
        asset_id = register_asset(conn, ticker)

        # 2b. Descargar e insertar OHLCV
        ingest_ohlcv(conn, ticker, asset_id, years)

        # 2c. Descargar e insertar fundamentales
        ingest_fundamentals(conn, ticker, asset_id)

    # 3. Resumen
    logger.info("Paso 3/3: Validación y resumen...")
    print_summary(conn, effective_db_path)

    conn.close()
    logger.info("[OK] Inicializacion completada exitosamente.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
