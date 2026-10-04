"""
chartist_engine.py -- Motor Cuantitativo de Senales Chartistas Multi-Factor
===========================================================================
Implementa la jerarquia de 4 prioridades para analisis tecnico cuantitativo:

Prioridad 1: Tendencia por Estructura de Swings
    - Identifica Swing Highs y Swing Lows mediante fractales de orden N.
    - Higher Highs (HH) + Higher Lows (HL) -> TENDENCIA ALCISTA (BULLISH).
    - Lower Highs (LH) + Lower Lows (LL) -> TENDENCIA BAJISTA (BEARISH).

Prioridad 2: Agresividad del Giro (Vueltas en V / Climax)
    - Mide el numero de sesiones que el precio permanece en maximos/minimos
      antes de girar violentamente. Giros en 1-3 sesiones indican clímax institucional.

Prioridad 3: Figuras Chartistas Exclusivas
    - Taza con Asa (Cup & Handle): Detectada como CAMBIO DE TENDENCIA (reversal),
      no como simple continuacion. Desencadena cambio de sesgo a alcista.
    - Cuñas (Falling Wedge / Rising Wedge): Identificadas mediante convergencia
      de lineas de tendencia de pivotes.

Prioridad 4: Climax de Volatilidad por Rango Relativo de Velas
    - Compara el True Range (High - Low) de cada vela contra el percentil historico
      y la media movil del rango (Relative Candle Range).
    - Expansiones extremas (> 2.0x rango medio o > P90) senalizan fin de tendencia/agotamiento.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
import numpy as np
import pandas as pd


@dataclass
class SwingPoint:
    index: int
    date: str
    price: float
    point_type: str  # 'HIGH' or 'LOW'


@dataclass
class ChartistPattern:
    pattern_type: str  # 'CUP_AND_HANDLE', 'FALLING_WEDGE', 'RISING_WEDGE'
    start_date: str
    end_date: str
    breakout_date: str
    breakout_price: float
    target_price: float
    stop_price: float
    description: str


@dataclass
class DailyRegime:
    date: str
    trend: str                   # 'BULLISH', 'BEARISH', 'SIDEWAYS'
    swing_structure: str         # 'HH_HL', 'LH_LL', 'MIXED'
    turn_aggression: float       # Indice de agresividad (1.0 = vuelta en V extrema)
    volatility_climax: bool      # True si el rango relativo de la vela indica fin de tendencia
    relative_candle_range: float # Rango relativo vs media de 20 periodos
    active_patterns: List[str] = field(default_factory=list)


class ChartistAnalyzer:
    """Analizador geometrico y cuantitativo segun las 4 prioridades del trader."""

    def __init__(
        self,
        swing_window: int = 5,
        range_ma_window: int = 20,
        range_climax_multiplier: float = 2.0,
        max_v_turn_sessions: int = 3,
    ):
        self.swing_window = swing_window
        self.range_ma_window = range_ma_window
        self.range_climax_multiplier = range_climax_multiplier
        self.max_v_turn_sessions = max_v_turn_sessions

    def detect_swings(self, df: pd.DataFrame) -> List[SwingPoint]:
        """
        Prioridad 1 (Parte 1): Detecta puntos de giro (Swing Highs y Swing Lows)
        usando un filtro fractal de orden k.
        """
        swings: List[SwingPoint] = []
        k = self.swing_window
        highs = df["high"].values
        lows = df["low"].values
        dates = [d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d) for d in df.index]

        for i in range(k, len(df) - k):
            # Swing High
            if all(highs[i] > highs[i - j] for j in range(1, k + 1)) and \
               all(highs[i] >= highs[i + j] for j in range(1, k + 1)):
                swings.append(SwingPoint(index=i, date=dates[i], price=highs[i], point_type="HIGH"))

            # Swing Low
            if all(lows[i] < lows[i - j] for j in range(1, k + 1)) and \
               all(lows[i] <= lows[i + j] for j in range(1, k + 1)):
                swings.append(SwingPoint(index=i, date=dates[i], price=lows[i], point_type="LOW"))

        return sorted(swings, key=lambda s: s.index)

    def evaluate_swing_trend(self, swings: List[SwingPoint]) -> Tuple[str, str]:
        """
        Prioridad 1 (Parte 2): Evalua la tendencia segun Higher Highs/Lows o Lower Highs/Lows.
        """
        high_swings = [s for s in swings if s.point_type == "HIGH"]
        low_swings = [s for s in swings if s.point_type == "LOW"]

        if len(high_swings) < 2 or len(low_swings) < 2:
            return "SIDEWAYS", "MIXED"

        h_curr, h_prev = high_swings[-1].price, high_swings[-2].price
        l_curr, l_prev = low_swings[-1].price, low_swings[-2].price

        is_hh = h_curr > h_prev
        is_hl = l_curr > l_prev
        is_lh = h_curr < h_prev
        is_ll = l_curr < l_prev

        if is_hh and is_hl:
            return "BULLISH", "HH_HL"
        elif is_lh and is_ll:
            return "BEARISH", "LH_LL"
        else:
            return "SIDEWAYS", "MIXED"

    def evaluate_turn_aggression(self, df: pd.DataFrame, swings: List[SwingPoint], current_idx: int) -> float:
        """
        Prioridad 2: Agresividad del Giro.
        Mide cuantas sesiones tomo el precio en maximos/minimos relativos antes de girar.
        Giro rapido (1-3 sesiones) con gran expansion = 1.0 (Muy Agresivo).
        Consolidacion dilatada (> 8 sesiones) = 0.2 (Giro Lento / Rango).
        """
        past_swings = [s for s in swings if s.index <= current_idx]
        if not past_swings:
            return 0.5

        last_swing = past_swings[-1]
        bars_since = current_idx - last_swing.index

        if bars_since <= 0:
            return 0.5

        # Factor de velocidad: menor duracion en el vertice = mayor agresividad
        if bars_since <= self.max_v_turn_sessions:
            aggression = 1.0
        elif bars_since <= 6:
            aggression = 0.7
        elif bars_since <= 10:
            aggression = 0.4
        else:
            aggression = 0.2

        return aggression

    def evaluate_relative_candle_range(self, df: pd.DataFrame) -> Tuple[pd.Series, pd.Series]:
        """
        Prioridad 4: Mide el rango de la vela (High - Low) y lo compara
        con la media movil del rango (Relative Candle Range).
        """
        candle_range = (df["high"] - df["low"]).abs()
        range_ma = candle_range.rolling(window=self.range_ma_window, min_periods=5).mean()
        relative_range = candle_range / range_ma.replace(0, np.nan)
        relative_range = relative_range.fillna(1.0)

        # Climax de volatilidad: cuando el rango relativo supera el multiplicador
        is_climax = relative_range >= self.range_climax_multiplier
        return relative_range, is_climax

    def detect_cup_and_handle(self, df: pd.DataFrame, swings: List[SwingPoint]) -> List[ChartistPattern]:
        """
        Prioridad 3: Taza con Asa tratada como CAMBIO DE TENDENCIA (Reversal).
        Estructura:
        1. Tendencia bajista previa o suelo en formacion.
        2. Borde izquierdo (Swing High A).
        3. Fondo redondeado (Swing Low central).
        4. Borde derecho (Swing High B, similar a A).
        5. Asa (retroceso menor del 30-50% de la profundidad de la taza).
        6. Ruptura de la resistencia.
        """
        patterns: List[ChartistPattern] = []
        highs = [s for s in swings if s.point_type == "HIGH"]
        lows = [s for s in swings if s.point_type == "LOW"]

        if len(highs) < 2 or len(lows) < 1:
            return patterns

        for i in range(len(highs) - 1):
            left_rim = highs[i]
            right_rim = highs[i + 1]

            # Tiempo suficiente para formar la taza (minimo 15 barras, maximo 120 barras)
            distance = right_rim.index - left_rim.index
            if distance < 15 or distance > 150:
                continue

            # Los dos bordes deben estar a un nivel similar (diferencia < 5%)
            rim_diff = abs(left_rim.price - right_rim.price) / left_rim.price
            if rim_diff > 0.06:
                continue

            # Buscar el fondo de la taza entre ambos bordes
            cup_bottoms = [l for l in lows if left_rim.index < l.index < right_rim.index]
            if not cup_bottoms:
                continue
            bottom = min(cup_bottoms, key=lambda l: l.price)

            cup_depth = min(left_rim.price, right_rim.price) - bottom.price
            if cup_depth <= 0:
                continue

            # Profundidad razonable de la taza (entre 8% y 40%)
            depth_pct = cup_depth / left_rim.price
            if depth_pct < 0.08 or depth_pct > 0.45:
                continue

            # Buscar el asa posterior al borde derecho
            handle_lows = [l for l in lows if l.index > right_rim.index and l.index <= right_rim.index + 25]
            if not handle_lows:
                continue
            handle_bottom = min(handle_lows, key=lambda l: l.price)

            # El asa no debe retroceder mas del 50% de la profundidad de la taza
            handle_drop = right_rim.price - handle_bottom.price
            if handle_drop > 0.55 * cup_depth or handle_drop < 0.02 * cup_depth:
                continue

            # Resistencia de ruptura: nivel del borde derecho
            resistance_level = max(left_rim.price, right_rim.price)

            # Buscar si el precio posterior supera la resistencia
            after_handle_df = df.iloc[handle_bottom.index: handle_bottom.index + 40]
            breakouts = after_handle_df[after_handle_df["close"] > resistance_level]

            if not breakouts.empty:
                bo_idx = df.index.get_loc(breakouts.index[0])
                bo_date = breakouts.index[0].strftime("%Y-%m-%d")
                bo_price = float(breakouts.iloc[0]["close"])
                target = bo_price + cup_depth
                stop = float(handle_bottom.price)

                patterns.append(ChartistPattern(
                    pattern_type="CUP_AND_HANDLE",
                    start_date=left_rim.date,
                    end_date=right_rim.date,
                    breakout_date=bo_date,
                    breakout_price=round(bo_price, 2),
                    target_price=round(target, 2),
                    stop_price=round(stop, 2),
                    description=f"Taza con Asa (Giro Alcista): Fondo en {bottom.date} a {bottom.price:.2f}, Ruptura en {bo_date}"
                ))

        return patterns

    def detect_wedges(self, df: pd.DataFrame, swings: List[SwingPoint]) -> List[ChartistPattern]:
        """
        Prioridad 3: Deteccion de Cuñas (Falling Wedge / Rising Wedge).
        Convergencia de dos lineas de tendencia sobre los ultimos 4-6 pivotes.
        """
        patterns: List[ChartistPattern] = []
        highs = [s for s in swings if s.point_type == "HIGH"]
        lows = [s for s in swings if s.point_type == "LOW"]

        if len(highs) < 3 or len(lows) < 3:
            return patterns

        # Evaluar ultimos 3 pivotes de cada lado
        h_pts = highs[-3:]
        l_pts = lows[-3:]

        h_slope = (h_pts[-1].price - h_pts[0].price) / (h_pts[-1].index - h_pts[0].index)
        l_slope = (l_pts[-1].price - l_pts[0].price) / (l_pts[-1].index - l_pts[0].index)

        # 1. Cuña Descendente (Falling Wedge): Ambas pendientes negativas, pero la linea inferior
        # desciende menos agresivamente que la superior (convergencia alcista).
        if h_slope < 0 and l_slope < 0 and l_slope > h_slope:
            last_date = df.index[-1].strftime("%Y-%m-%d")
            patterns.append(ChartistPattern(
                pattern_type="FALLING_WEDGE",
                start_date=h_pts[0].date,
                end_date=h_pts[-1].date,
                breakout_date=last_date,
                breakout_price=float(df.iloc[-1]["close"]),
                target_price=float(h_pts[0].price),
                stop_price=float(l_pts[-1].price),
                description="Cuña Descendente (Convergencia Alcista de Pivotes)"
            ))

        # 2. Cuña Ascendente (Rising Wedge): Ambas pendientes positivas, pero la superior
        # asciende con menor angulo que la inferior (convergencia bajista).
        elif h_slope > 0 and l_slope > 0 and h_slope < l_slope:
            last_date = df.index[-1].strftime("%Y-%m-%d")
            patterns.append(ChartistPattern(
                pattern_type="RISING_WEDGE",
                start_date=l_pts[0].date,
                end_date=l_pts[-1].date,
                breakout_date=last_date,
                breakout_price=float(df.iloc[-1]["close"]),
                target_price=float(l_pts[0].price),
                stop_price=float(h_pts[-1].price),
                description="Cuña Ascendente (Convergencia Bajista de Pivotes)"
            ))

        return patterns
