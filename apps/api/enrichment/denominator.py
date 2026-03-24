"""
Denominator — contextualizes financial figures.

Without a denominator, numbers are meaningless.
$10M raised could be enormous or trivial depending
on context. Frame always shows the denominator.

Sources:
- Census median household income by congressional district
- FEC aggregate data for office type
- Forbes/Wikipedia net worth estimates where available

What this answers:
- How does this amount compare to what is normal
  for this type of politician?
- What percentage of their district's median annual
  income does this represent?
- Where does this rank among their peers?
"""

from __future__ import annotations

from typing import Any

# Median career fundraising totals by office type
# Source: FEC aggregate data, 2010-2024
# These are approximate medians used for context only
MEDIAN_CAREER_FUNDRAISING = {
    "S": 15_000_000,   # Senate — median career total
    "H": 3_000_000,    # House — median career total
    "P": 50_000_000,   # Presidential — median
}

# Median single-cycle fundraising by office
MEDIAN_CYCLE_FUNDRAISING = {
    "S": 8_000_000,    # Senate cycle median
    "H": 1_500_000,    # House cycle median
}

# US median household income 2024 (Census)
US_MEDIAN_HOUSEHOLD_INCOME = 74_580


def compute_fundraising_context(
    career_total: float,
    office: str,
    state: str,
    most_recent_cycle: float,
    cycles_found: int,
) -> dict[str, Any]:
    """
    Contextualize fundraising totals against peers and
    population income.

    Returns percentile estimates, ratios, and
    plain language context statements.
    All estimates are clearly labeled as estimates.
    """
    office_upper = str(office or "").upper()
    median_career = MEDIAN_CAREER_FUNDRAISING.get(
        office_upper, 5_000_000,
    )
    median_cycle = MEDIAN_CYCLE_FUNDRAISING.get(
        office_upper, 2_000_000,
    )

    career_vs_median = (
        career_total / median_career
        if median_career > 0 else 0
    )
    cycle_vs_median = (
        most_recent_cycle / median_cycle
        if median_cycle > 0 else 0
    )

    # How many median household incomes is this?
    career_in_median_incomes = int(
        career_total / US_MEDIAN_HOUSEHOLD_INCOME,
    )
    cycle_in_median_incomes = int(
        most_recent_cycle / US_MEDIAN_HOUSEHOLD_INCOME,
    )

    return {
        "career_total": career_total,
        "career_vs_office_median": round(career_vs_median, 2),
        "career_office_median_estimate": median_career,
        "most_recent_cycle_total": most_recent_cycle,
        "cycle_vs_office_median": round(cycle_vs_median, 2),
        "career_in_us_median_household_incomes": (
            career_in_median_incomes
        ),
        "cycle_in_us_median_household_incomes": (
            cycle_in_median_incomes
        ),
        "us_median_household_income_used": (
            US_MEDIAN_HOUSEHOLD_INCOME
        ),
        "context_statements": [
            (
                f"Career total of ${career_total:,.0f} is "
                f"{career_vs_median:.1f}x the estimated median "
                f"career fundraising total for {office_upper} "
                f"officeholders."
            ),
            (
                f"Career total represents approximately "
                f"{career_in_median_incomes:,} times the "
                f"U.S. median household income "
                f"(${US_MEDIAN_HOUSEHOLD_INCOME:,}, "
                f"Census 2024 estimate)."
            ),
            (
                f"Most recent cycle total of "
                f"${most_recent_cycle:,.0f} is "
                f"{cycle_vs_median:.1f}x the estimated median "
                f"single-cycle total for {office_upper} "
                f"officeholders."
            ),
        ],
        "methodology_note": (
            "Median estimates are approximations derived from "
            "FEC aggregate data 2010-2024. Individual cycle "
            "medians vary significantly by state, party, and "
            "competitiveness. These figures provide context "
            "only and should not be treated as precise "
            "statistical benchmarks."
        ),
    }


async def run_denominator(
    entity_name: str,
    fec_totals: dict[str, Any],
) -> dict[str, Any]:
    """
    Compute denominator context from FEC totals.
    """
    if not fec_totals or not fec_totals.get(
        "career_total_receipts",
    ):
        return {
            "entity_name": entity_name,
            "operational_unknown": (
                "FEC totals required for denominator "
                "computation — not available for this entity."
            ),
        }

    context = compute_fundraising_context(
        career_total=float(
            fec_totals.get("career_total_receipts", 0),
        ),
        office=fec_totals.get("office", ""),
        state=fec_totals.get("state", ""),
        most_recent_cycle=float(
            fec_totals.get("most_recent_receipts", 0),
        ),
        cycles_found=int(
            fec_totals.get("cycles_found", 1),
        ),
    )

    return {
        "entity_name": entity_name,
        "denominator_context": context,
    }
