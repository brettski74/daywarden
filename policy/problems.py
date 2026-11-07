"""Report every problem a check can find, not only the first.

A check that has independent parts runs each one through ``Collector.take``
and raises ``Problems`` at the end when any of them failed. ``Problems`` is a
``ValueError``, so a caller that only wants to know whether the check passed
handles it as before. ``str`` lists the problems one per line, first one first.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class Problems(ValueError):
    """One or more problems found by one check."""

    def __init__(self, *problems: str) -> None:
        self.problems = tuple(problems)
        super().__init__("\n".join(self.problems))


def problems_of(error: ValueError) -> tuple[str, ...]:
    """Return each problem ``error`` reports."""
    if isinstance(error, Problems) and error.problems:
        return error.problems
    return (str(error),)


class Collector:
    """Gathers the problems of the independent parts of one check."""

    def __init__(self) -> None:
        self.problems: list[str] = []

    def take(self, check: Callable[..., T], *args, **kwargs) -> T | None:
        """Return ``check(*args, **kwargs)``, or None after noting why it failed."""
        try:
            return check(*args, **kwargs)
        except ValueError as error:
            self.problems.extend(problems_of(error))
            return None

    def add(self, problem: str) -> None:
        self.problems.append(problem)

    def finish(self, error: type[Problems] = Problems) -> None:
        """Raise ``error`` with every problem noted, when there is one."""
        if self.problems:
            raise error(*self.problems)
