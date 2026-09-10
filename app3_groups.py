"""Application 3 - geopolitical groupings and the economic profile of subjects.

Question: do euro-area territories differ from the other high-income and from the middle-income
UNECE territories in green-transition readiness and sustainable economic performance?

The subjects module links every country to the economic groupings it belongs to (Economy
individuals reached through hasEconomy: EURO AREA, HIGH INCOME, UPPER/LOWER MIDDLE INCOME, ...).
The analyst declares three crisp group concepts on those individuals and composes them with the
fuzzy concepts of the ontology:

    EuroAreaTerritory      = some hasLocation (some hasEconomy EuroArea)
    EuroAreaGreenReadiness = EuroAreaTerritory and GreenTransitionReadiness      (Lukasiewicz and)

so that the membership degree of a snapshot in EuroAreaGreenReadiness is its GreenTransitionReadiness
degree when the country is in the euro area and 0 otherwise. Output: results/app3.json, tables/app3.tex.
"""

import statistics

import sdf_fuzzy as sf

# Application 3 axioms and concept definitions for geopolitical groupings and economic profiles.
AXIOMS = """
(instance CL10344_EURO_AREA EuroArea 1.0)
(instance CL10351_1_HIGH_INCOME HighIncome 1.0)
(instance CL10352_2_UPPER_MIDDLE_INCOME MiddleIncome 1.0)
(instance CL10353_3_LOWER_MIDDLE_INCOME MiddleIncome 1.0)
(define-concept EuroAreaTerritory (some hasLocation (some hasEconomy EuroArea)))
(define-concept HighIncomeTerritory (some hasLocation (some hasEconomy HighIncome)))
(define-concept MiddleIncomeTerritory (some hasLocation (some hasEconomy MiddleIncome)))
(define-concept EuroAreaGreenReadiness (and EuroAreaTerritory GreenTransitionReadiness))
(define-concept MiddleIncomeStructuralStress (and MiddleIncomeTerritory StructuralDevelopmentStress))
"""
# List of all concepts used in the reasoning process.
CONCEPTS = [
    "EuroAreaTerritory",
    "HighIncomeTerritory",
    "MiddleIncomeTerritory",
    "GreenTransitionReadiness",
    "SustainableEconomicPerformance",
    "StructuralDevelopmentStress",
    "EuroAreaGreenReadiness",
    "MiddleIncomeStructuralStress",
]


def main():
    # Select all snapshots for the year 2021.
    snapshots = sf.select_snapshots(2021)
    # Prepare the queries for all snapshots and all concepts.
    queries = [f"(min-instance? {s} {c})" for s in snapshots for c in CONCEPTS]
    # Extract the list of countries from the snapshots.
    countries = sorted({s.rsplit("_", 1)[0] for s in snapshots})
    # Prepare the list of individuals for the reasoning process, including snapshots and countries.
    individuals = [sf.snapshot(s) for s in snapshots] + [
        sf.country(c) for c in countries
    ]  # countries: object links
    # Run the reasoning process with the prepared individuals, axioms, and queries.
    report = sf.run("app3", individuals, AXIOMS, queries, prune=True)
    # Extract the number of concepts for later use in indexing the results.
    k = len(CONCEPTS)
    # Extract the degrees of membership for each snapshot and each concept.
    deg = {
        s: {c: sf.value(report["results"], i * k + j) for j, c in enumerate(CONCEPTS)}
        for i, s in enumerate(snapshots)
    }
    # Group the snapshots based on their membership in the Euro area, high-income outside the Euro area, and middle-income categories.
    groups = {
        "Euro area": [s for s in snapshots if deg[s]["EuroAreaTerritory"] >= 1],
        "High income, outside the euro area": [
            s
            for s in snapshots
            if deg[s]["HighIncomeTerritory"] >= 1 and deg[s]["EuroAreaTerritory"] < 1
        ],
        "Middle income": [s for s in snapshots if deg[s]["MiddleIncomeTerritory"] >= 1],
    }
    # Generate the LaTeX table summarizing the group statistics.
    with open(sf.TABLES / "app3.tex", "w") as f:
        f.write("\\begin{tabularx}{\\textwidth}{lCCCCCC}\n\\toprule\n")
        f.write(
            "\\textbf{Group (2021 snapshots)} & \\textbf{n} & \\multicolumn{2}{c}{\\textbf{GTR}} & \\multicolumn{2}{c}{\\textbf{SEP}} & \\textbf{SDS}\\\\\n"
        )
        f.write(" & & mean & max & mean & max & mean\\\\\n\\midrule\n")
        for g, members in groups.items():
            if not members:
                continue
            gtr = [deg[s]["GreenTransitionReadiness"] for s in members]
            sep = [deg[s]["SustainableEconomicPerformance"] for s in members]
            sds = [deg[s]["StructuralDevelopmentStress"] for s in members]
            f.write(
                f"{g} & {len(members)} & {statistics.mean(gtr):.3f} & {max(gtr):.3f} & {statistics.mean(sep):.3f} & {max(sep):.3f} & {statistics.mean(sds):.3f}\\\\\n"
            )
        f.write("\\bottomrule\n\\end{tabularx}\n")
        for g, members in groups.items():
            f.write(f"% {g}: {', '.join(members)}\n")
    with open(sf.TABLES / "app3_members.tex", "w") as f:
        f.write("\\begin{tabularx}{\\textwidth}{lCCC}\n\\toprule\n")
        f.write(
            "\\textbf{Snapshot} & \\textbf{EuroArea\\-Green\\-Readiness} & \\textbf{MiddleIncome\\-Structural\\-Stress} & \\textbf{SEP}\\\\\n\\midrule\n"
        )
        rows = sorted(
            snapshots,
            key=lambda s: (
                -deg[s]["EuroAreaGreenReadiness"],
                -deg[s]["MiddleIncomeStructuralStress"],
                s,
            ),
        )
        for s in rows:
            d = deg[s]
            if d["EuroAreaGreenReadiness"] > 0 or d["MiddleIncomeStructuralStress"] > 0:
                f.write(
                    f"{s.replace('_', ' ')} & {d['EuroAreaGreenReadiness']:.3f} & {d['MiddleIncomeStructuralStress']:.3f} & {d['SustainableEconomicPerformance']:.3f}\\\\\n"
                )
        f.write("\\bottomrule\n\\end{tabularx}\n")
    # Print the group statistics to the console for quick reference.
    for g, members in groups.items():
        print(g, len(members), members)
    # Print the degrees of the first few snapshots for quick inspection.
    for s in snapshots[:6]:
        print(s, deg[s])


if __name__ == "__main__":
    main()
