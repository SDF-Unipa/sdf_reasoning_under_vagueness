"""Application 5 - temporal trajectories.

Question: has economic stress eased in the southern European territories since 2015, and which
territories improved most in sustainable economic performance?

The slice contains every complete snapshot (all six features) of five countries between 2015 and
2023; the same composite concepts are queried year by year and the degrees are read as trajectories.
Two analyst concepts complete the picture: JoblessGrowth (growth with high unemployment, as in
Application 4) and Recovery = SustainableEconomicPerformance and (not EconomicStress).
Output: results/app5.json and tables/app5.tex (one row per year, one column per country and concept).
"""

import sdf_fuzzy as sf

# This application analyzes the temporal trajectories of economic stress and sustainable economic performance for selected southern European countries over the period 2015-2023. It generates LaTeX tables summarizing the results for both the basic concepts and the analyst-defined concepts (JoblessGrowth and Recovery).

# The selected countries are Greece, Spain, Italy, Croatia, and Portugal.
COUNTRIES = ["Greece", "Spain", "Italy", "Croatia", "Portugal"]
# The years considered for the analysis range from 2015 to 2023.
YEARS = range(2015, 2024)
# The axioms define the analyst concepts JoblessGrowth and Recovery.
AXIOMS = """
(define-concept JoblessGrowth (and (some economicGrowthRate PositiveEconomicGrowth) (some unemploymentRate HighUnemployment)))
(define-concept Recovery (and SustainableEconomicPerformance (not EconomicStress)))
"""
# The list of concepts includes both the basic concepts and the analyst-defined concepts.
CONCEPTS = [
    "EconomicStress",
    "SustainableEconomicPerformance",
    "JoblessGrowth",
    "Recovery",
]


def main():
    # Select all snapshots for the specified years and countries.
    snapshots = [
        s
        for y in YEARS
        for s in sf.select_snapshots(y)
        if s.rsplit("_", 1)[0] in COUNTRIES
    ]
    # Prepare the list of queries for each snapshot and concept.
    queries = [f"(min-instance? {s} {c})" for s in snapshots for c in CONCEPTS]
    # Run the reasoning engine with the prepared snapshots, axioms, and queries.
    report = sf.run("app5", [sf.snapshot(s) for s in snapshots], AXIOMS, queries)
    # Extract the degrees of membership for each snapshot and concept from the reasoning report.
    k = len(CONCEPTS)
    # The number of concepts is used to correctly index the results in the reasoning report.
    deg = {
        s: [sf.value(report["results"], i * k + j) for j in range(k)]
        for i, s in enumerate(snapshots)
    }
    # The degrees of membership are now stored in the `deg` dictionary, keyed by snapshot identifiers.
    with open(sf.TABLES / "app5.tex", "w") as f:
        f.write(
            "\\begin{adjustwidth}{-\\extralength}{0cm}\n\\centering\n\\footnotesize\n"
        )
        f.write(
            "\\begin{tabularx}{\\fulllength}{l"
            + "C" * (2 * len(COUNTRIES))
            + "}\n\\toprule\n"
        )
        f.write(
            "\\textbf{Year} & "
            + " & ".join(
                f"\\multicolumn{{2}}{{c}}{{\\textbf{{{c}}}}}" for c in COUNTRIES
            )
            + "\\\\\n"
        )
        f.write(" & " + " & ".join("ES & SEP" for _ in COUNTRIES) + "\\\\\n\\midrule\n")
        for y in YEARS:
            cells = []
            for c in COUNTRIES:
                d = deg.get(f"{c}_{y}")
                cells.append(f"{d[0]:.2f} & {d[1]:.2f}" if d else "-- & --")
            f.write(f"{y} & " + " & ".join(cells) + "\\\\\n")
        f.write("\\bottomrule\n\\end{tabularx}\n\\end{adjustwidth}\n")
    # The main LaTeX table for the application has been written to `app5.tex`.
    with open(sf.TABLES / "app5_analyst.tex", "w") as f:
        f.write(
            "\\begin{tabularx}{\\textwidth}{l"
            + "C" * (2 * len(COUNTRIES))
            + "}\n\\toprule\n"
        )
        f.write(
            "\\textbf{Year} & "
            + " & ".join(
                f"\\multicolumn{{2}}{{c}}{{\\textbf{{{c}}}}}" for c in COUNTRIES
            )
            + "\\\\\n"
        )
        f.write(
            " & " + " & ".join("JG & Rec." for _ in COUNTRIES) + "\\\\\n\\midrule\n"
        )
        for y in YEARS:
            cells = []
            for c in COUNTRIES:
                d = deg.get(f"{c}_{y}")
                cells.append(f"{d[2]:.2f} & {d[3]:.2f}" if d else "-- & --")
            f.write(f"{y} & " + " & ".join(cells) + "\\\\\n")
        f.write("\\bottomrule\n\\end{tabularx}\n")
    # The analyst-specific LaTeX table for the application has been written to `app5_analyst.tex`.
    for s in snapshots:
        print(f"{s:20}", " ".join(f"{x:5.2f}" for x in deg[s]))


if __name__ == "__main__":
    main()
