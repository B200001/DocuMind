"""
Small, dependency-free table printer shared by retrieval_eval.py and
run_eval.py, so both scripts produce a consistent-looking summary at the
end of a run without needing to pull in a table-formatting library.
"""

from __future__ import annotations


def print_table(title: str, headers: list[str], rows: list[list[str]]) -> None:
    """
    Print a simple fixed-width table to stdout.

    Parameters
    ----------
    title:
        A heading printed above the table.
    headers:
        Column header labels.
    rows:
        Each row is a list of pre-formatted string cells, same length as headers.
    """
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))

    def format_row(cells: list[str]) -> str:
        return "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(cells))

    total_width = sum(widths) + 2 * (len(widths) - 1)

    print()
    print(title)
    print("=" * max(len(title), total_width))
    print(format_row(headers))
    print("-" * total_width)
    for row in rows:
        print(format_row(row))
    print()


def format_pct(value: float) -> str:
    """Format a 0-1 float as a percentage string, e.g. 0.834 -> '83.4%'."""
    return f"{value * 100:.1f}%"


def format_score(value: float) -> str:
    """Format a 0-1 float as a fixed-precision score, e.g. 0.834 -> '0.834'."""
    return f"{value:.3f}"
