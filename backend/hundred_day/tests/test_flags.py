import json
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from django.test import SimpleTestCase

from hundred_day.services.flags import compute_high_low_flags


class HundredDayFlagTests(SimpleTestCase):
    window_size = 99

    def _dates(self, count):
        start = date(2026, 1, 1)
        return tuple(start + timedelta(days=index) for index in range(count))

    def _series(self, values):
        lengths = {len(series) for series in values.values()}
        self.assertEqual(len(lengths), 1, 'Each stock series must span the same date positions.')
        dates = self._dates(lengths.pop())
        return dates, {
            stock_code: {
                day: None if value is None else Decimal(str(value))
                for day, value in zip(dates, series)
            }
            for stock_code, series in values.items()
        }

    def test_fewer_than_100_trading_day_positions_returns_explicit_insufficiency(self):
        dates, closes = self._series({'600001': [10] * 99})

        result = compute_high_low_flags(dates, closes)

        self.assertFalse(result.has_sufficient_history)
        self.assertEqual(result.required_trading_day_positions, 100)
        self.assertEqual(result.available_trading_day_positions, 99)
        self.assertEqual(result.flags_by_date, {})

    def test_100th_position_compares_target_only_with_previous_99_positions(self):
        dates, closes = self._series({'600001': list(range(1, 100)) + [99]})

        result = compute_high_low_flags(dates, closes)

        target_flag = result.flags_by_date[dates[-1]][0]
        self.assertTrue(target_flag.is_new_high)
        self.assertFalse(target_flag.is_new_low)
        self.assertEqual(result.valid_stock_counts_by_date[dates[-1]], 1)

    def test_missing_history_is_zero_filled_but_missing_target_is_not_flagged(self):
        values = [5] * 99 + [0]
        values[10] = None
        halted = [5] * 99 + [None]
        dates, closes = self._series({'600001': values, '600002': halted})

        result = compute_high_low_flags(dates, closes)

        self.assertEqual(result.valid_stock_counts_by_date[dates[-1]], 1)
        self.assertEqual(len(result.flags_by_date[dates[-1]]), 1)
        low = result.flags_by_date[dates[-1]][0]
        self.assertEqual(low.stock_code, '600001')
        self.assertFalse(low.is_new_high)
        self.assertTrue(low.is_new_low)

    def test_new_listing_with_missing_history_can_be_new_high(self):
        dates, closes = self._series({'600001': [None] * 99 + [10]})

        result = compute_high_low_flags(dates, closes)

        flag = result.flags_by_date[dates[-1]][0]
        self.assertTrue(flag.is_new_high)
        self.assertFalse(flag.is_new_low)

    def test_equal_extrema_and_all_zero_history_follow_legacy_inclusive_rules(self):
        fixture_path = Path(__file__).parent / 'fixtures' / 'hundred_day_regression.json'
        fixture = json.loads(fixture_path.read_text())
        dates, closes = self._series(fixture['history'])

        result = compute_high_low_flags(dates, closes)

        flags = {flag.stock_code: flag for flag in result.flags_by_date[dates[-1]]}
        self.assertTrue(flags['EQMAX'].is_new_high)
        self.assertFalse(flags['EQMAX'].is_new_low)
        self.assertTrue(flags['ALLZERO'].is_new_high)
        self.assertTrue(flags['ALLZERO'].is_new_low)

    def test_flags_are_deterministically_ordered_by_stock_code(self):
        dates, closes = self._series({
            '600002': [None] * 99 + [1],
            '600001': [None] * 99 + [1],
        })

        result = compute_high_low_flags(dates, closes)

        self.assertEqual(
            [flag.stock_code for flag in result.flags_by_date[dates[-1]]],
            ['600001', '600002'],
        )

    def test_sliding_extrema_match_the_naive_window_on_random_series(self):
        """The deque optimisation must stay bit-for-bit equivalent to the plain window.

        The naive form (build one tuple per stock per trading day, then max/min) is
        the original implementation and is cheap enough for a small random sample,
        so it is kept here as the differential oracle for the fast path.
        """
        random_source = random.Random(20260908)
        positions = 130
        stock_count = 24
        series: dict[str, list] = {}
        for index in range(stock_count):
            series[f'{600000 + index}'] = [
                None if random_source.random() < 0.12 else random_source.choice([0, 5, 10, 10, 7, 3])
                for _ in range(positions)
            ]
        dates, closes = self._series(series)

        result = compute_high_low_flags(dates, closes)

        for position in range(self.window_size, positions):
            target_day = dates[position]
            history_days = dates[position - self.window_size:position]
            expected_flags = []
            expected_valid_count = 0
            for stock_code in sorted(series):
                stock_closes = closes[stock_code]
                target_close = stock_closes.get(target_day)
                if target_close is None:
                    continue
                expected_valid_count += 1
                history = tuple(
                    Decimal('0') if stock_closes.get(day) is None else stock_closes[day]
                    for day in history_days
                )
                is_new_high = target_close >= max(history)
                is_new_low = target_close <= min(history)
                if is_new_high or is_new_low:
                    expected_flags.append((stock_code, is_new_high, is_new_low))

            self.assertEqual(result.valid_stock_counts_by_date[target_day], expected_valid_count)
            self.assertEqual(
                [
                    (flag.stock_code, flag.is_new_high, flag.is_new_low)
                    for flag in result.flags_by_date[target_day]
                ],
                expected_flags,
                f'Mismatch at {target_day}',
            )
