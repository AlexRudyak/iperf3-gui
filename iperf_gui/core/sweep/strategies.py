"""Strategies for generating the parameter values a sweep will step through.

The original implementation hard-coded ``range(start, end + step, step)``,
which could overshoot the requested end value when the step did not divide the
span evenly, and admitted no other progression. Expressing the progression as a
strategy makes a logarithmic sweep -- the natural choice for window sizes -- a
new class rather than another branch.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

#: Guard against a misconfigured sweep scheduling an unbounded run of tests.
MAX_SWEEP_POINTS = 1000


class SweepError(ValueError):
    """Raised when sweep parameters cannot produce a valid sequence of values."""


class SweepStrategy(ABC):
    """Produces the ordered parameter values for a sweep."""

    @abstractmethod
    def values(self) -> list[int]:
        """Return the values to test, in order.

        Raises:
            SweepError: if the configured parameters are not usable.
        """

    @abstractmethod
    def describe(self) -> str:
        """Short human-readable description, used in log output."""


@dataclass(frozen=True)
class LinearSweep(SweepStrategy):
    """Steps from ``start`` to ``end`` in fixed increments of ``step``.

    ``end`` is included when it falls on a step boundary, and is never
    overshot when it does not.
    """

    start: int
    end: int
    step: int

    def values(self) -> list[int]:
        if self.step <= 0:
            raise SweepError("Step value must be greater than zero.")
        if self.start > self.end:
            raise SweepError(
                f"Start value ({self.start}) must not exceed end value ({self.end})."
            )

        count = (self.end - self.start) // self.step + 1
        if count > MAX_SWEEP_POINTS:
            raise SweepError(
                f"This sweep would run {count} tests; the maximum is "
                f"{MAX_SWEEP_POINTS}. Increase the step value."
            )
        return [self.start + index * self.step for index in range(count)]

    def describe(self) -> str:
        return f"linear {self.start}..{self.end} step {self.step}"


@dataclass(frozen=True)
class ExponentialSweep(SweepStrategy):
    """Multiplies by ``factor`` each step, never exceeding ``end``.

    Suited to parameters whose interesting range spans orders of magnitude,
    such as the TCP window size.
    """

    start: int
    end: int
    factor: float = 2.0

    def values(self) -> list[int]:
        if self.start < 1:
            raise SweepError("Start value must be at least 1 for an exponential sweep.")
        if self.factor <= 1.0:
            raise SweepError("Factor must be greater than 1.")
        if self.start > self.end:
            raise SweepError(
                f"Start value ({self.start}) must not exceed end value ({self.end})."
            )

        values: list[int] = []
        current = float(self.start)
        while int(current) <= self.end:
            value = int(current)
            # Rounding can repeat a value for small starts and factors close
            # to 1; keep the sequence strictly increasing.
            if not values or value > values[-1]:
                values.append(value)
            if len(values) > MAX_SWEEP_POINTS:
                raise SweepError(
                    f"This sweep would run more than {MAX_SWEEP_POINTS} tests. "
                    "Increase the factor."
                )
            current *= self.factor
        if not values:
            raise SweepError("These parameters produce no values to test.")
        return values

    def describe(self) -> str:
        return f"exponential {self.start}..{self.end} x{self.factor:g}"


@dataclass(frozen=True)
class ExplicitSweep(SweepStrategy):
    """Tests an explicit, user-supplied list of values."""

    raw_values: tuple[int, ...]

    def values(self) -> list[int]:
        if not self.raw_values:
            raise SweepError("No values supplied.")
        if len(self.raw_values) > MAX_SWEEP_POINTS:
            raise SweepError(f"At most {MAX_SWEEP_POINTS} values may be tested.")
        return list(self.raw_values)

    def describe(self) -> str:
        return f"explicit [{', '.join(str(v) for v in self.raw_values)}]"

    @classmethod
    def from_text(cls, text: str) -> "ExplicitSweep":
        """Build from a comma or whitespace separated list of integers."""
        tokens = [t for t in text.replace(",", " ").split() if t]
        try:
            return cls(tuple(int(token) for token in tokens))
        except ValueError as exc:
            raise SweepError(f"Not a valid list of integers: {text!r}") from exc
