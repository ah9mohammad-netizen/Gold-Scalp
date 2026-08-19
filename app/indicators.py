"""Dependency-free technical indicators used by the live v7 market feed."""
from __future__ import annotations

import math
from typing import List, Tuple


class TechnicalIndicators:
    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> float:
        if not prices:
            return 0.0
        if len(prices) < period:
            return prices[-1]
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
        return ema

    @staticmethod
    def calculate_sma(prices: List[float], period: int) -> float:
        if not prices:
            return 0.0
        window = prices[-period:] if len(prices) >= period else prices
        return sum(window) / len(window)

    @staticmethod
    def calculate_stdev(prices: List[float], period: int) -> float:
        if len(prices) < 2:
            return 0.0
        window = prices[-period:] if len(prices) >= period else prices
        mean = sum(window) / len(window)
        variance = sum((price - mean) ** 2 for price in window) / len(window)
        return math.sqrt(variance)

    @staticmethod
    def calculate_atr(
        highs: List[float], lows: List[float], closes: List[float], period: int = 14
    ) -> float:
        if len(highs) < period + 1:
            return 1.80
        true_ranges = [
            max(
                highs[index] - lows[index],
                abs(highs[index] - closes[index - 1]),
                abs(lows[index] - closes[index - 1]),
            )
            for index in range(1, len(closes))
        ]
        if len(true_ranges) < period:
            return sum(true_ranges) / len(true_ranges) if true_ranges else 1.80
        atr = sum(true_ranges[:period]) / period
        for true_range in true_ranges[period:]:
            atr = (atr * (period - 1) + true_range) / period
        return atr

    @staticmethod
    def atr_series(
        highs: List[float], lows: List[float], closes: List[float], period: int = 14
    ) -> List[float]:
        if len(closes) < period + 1:
            return []
        true_ranges = [
            max(
                highs[index] - lows[index],
                abs(highs[index] - closes[index - 1]),
                abs(lows[index] - closes[index - 1]),
            )
            for index in range(1, len(closes))
        ]
        atr = sum(true_ranges[:period]) / period
        output = [atr]
        for true_range in true_ranges[period:]:
            atr = (atr * (period - 1) + true_range) / period
            output.append(atr)
        return output

    @staticmethod
    def calculate_rsi(closes: List[float], period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0
        gains: List[float] = []
        losses: List[float] = []
        for index in range(1, len(closes)):
            change = closes[index] - closes[index - 1]
            gains.append(max(change, 0.0))
            losses.append(max(-change, 0.0))
        average_gain = sum(gains[:period]) / period
        average_loss = sum(losses[:period]) / period
        for index in range(period, len(gains)):
            average_gain = (average_gain * (period - 1) + gains[index]) / period
            average_loss = (average_loss * (period - 1) + losses[index]) / period
        if average_loss == 0:
            return 100.0
        relative_strength = average_gain / average_loss
        return 100.0 - (100.0 / (1.0 + relative_strength))

    @staticmethod
    def calculate_adx(
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int = 14,
    ) -> Tuple[float, float, float]:
        if len(closes) < period + 2:
            return 20.0, 20.0, 20.0
        plus_dm: List[float] = []
        minus_dm: List[float] = []
        true_ranges: List[float] = []
        for index in range(1, len(closes)):
            up = highs[index] - highs[index - 1]
            down = lows[index - 1] - lows[index]
            plus_dm.append(up if up > down and up > 0 else 0.0)
            minus_dm.append(down if down > up and down > 0 else 0.0)
            true_ranges.append(
                max(
                    highs[index] - lows[index],
                    abs(highs[index] - closes[index - 1]),
                    abs(lows[index] - closes[index - 1]),
                )
            )

        def wilder(values: List[float]) -> List[float]:
            if len(values) < period:
                return []
            output = [sum(values[:period])]
            for value in values[period:]:
                output.append(output[-1] - output[-1] / period + value)
            return output

        atr_smooth = wilder(true_ranges)
        plus_smooth = wilder(plus_dm)
        minus_smooth = wilder(minus_dm)
        if not atr_smooth or not plus_smooth or not minus_smooth:
            return 20.0, 20.0, 20.0

        dx_values: List[float] = []
        for index, atr in enumerate(atr_smooth):
            divisor = atr or 1e-9
            plus_di = 100.0 * plus_smooth[index] / divisor
            minus_di = 100.0 * minus_smooth[index] / divisor
            total = plus_di + minus_di
            dx_values.append(100.0 * abs(plus_di - minus_di) / total if total else 0.0)
        if len(dx_values) < period:
            adx = sum(dx_values) / len(dx_values)
        else:
            adx = sum(dx_values[:period]) / period
            for dx in dx_values[period:]:
                adx = (adx * (period - 1) + dx) / period
        last_atr = atr_smooth[-1] or 1e-9
        return (
            round(adx, 2),
            round(100.0 * plus_smooth[-1] / last_atr, 2),
            round(100.0 * minus_smooth[-1] / last_atr, 2),
        )
