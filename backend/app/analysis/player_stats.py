"""Developer command for inspecting one persisted user's statistics."""

import argparse
import sys

from sqlalchemy.exc import SQLAlchemyError

from backend.app.analysis.statistics import (
    PlayerNotFoundError,
    PlayerStatistics,
    get_player_statistics,
)


def _format_average(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}"


def _format_accuracy(value: float | None) -> str:
    return "N/A" if value is None else f"{value * 100:.2f}%"


def print_statistics(statistics: PlayerStatistics) -> None:
    """Print a compact human-readable statistics report."""
    print(f"Player: {statistics.username} ({statistics.user_id})")
    print(f"Persisted top plays: {statistics.top_play_count}")
    print(f"Average PP: {_format_average(statistics.average_pp)}")
    print(f"Average accuracy: {_format_accuracy(statistics.average_accuracy)}")
    print(f"Average stars: {_format_average(statistics.average_star_rating)}")
    print(f"Average AR: {_format_average(statistics.average_approach_rate)}")
    print(f"Average BPM: {_format_average(statistics.average_bpm)}")

    print("\nExact mod combinations:")
    if statistics.exact_mod_combinations:
        for combination in statistics.exact_mod_combinations:
            label = "".join(combination.mods) if combination.mods else "NM"
            print(f"{label}: {combination.count}")
    else:
        print("(none)")

    print("\nIndividual mods:")
    if statistics.individual_mods:
        for mod in statistics.individual_mods:
            print(f"{mod.acronym}: {mod.count}")
    else:
        print("(none)")


def main() -> int:
    """Load and display statistics without fetching or mutating osu! data."""
    parser = argparse.ArgumentParser(
        description="Calculate statistics from a persisted osu! user's top plays."
    )
    parser.add_argument("username", help="persisted osu! username to analyze")
    arguments = parser.parse_args()

    try:
        statistics = get_player_statistics(arguments.username)
    except PlayerNotFoundError as error:
        print(str(error), file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"Configuration or input error: {error}", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print(
            "Statistics query failed. Check the PostgreSQL connection and schema.",
            file=sys.stderr,
        )
        return 1

    print_statistics(statistics)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
