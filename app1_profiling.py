"""Application 1 - fuzzy territorial profiling.

Question: to what degree were the UNECE territories under socio-economic stress in 2021, and does
the answer depend on how the stress dimensions are aggregated?

For every complete 2021 snapshot the reasoner computes the lower bound of the membership degree
in four composite fuzzy concepts of the SDF ontology:
    - BasicNeedsStress            weighted sum   (food insecurity 0.40, poverty 0.35, unemployment 0.25)
    - EconomicStress              weighted sum   (economic decline 0.40, unemployment 0.35, poverty 0.25)
    - StructuralDevelopmentStress weighted sum   (five dimensions)
    - BroadSocioEconomicStress    OWA            (weights 0.5/0.25/0.125/0.125: "at least one dimension")
Output: results/app1.json and tables/app1.tex (ranking by EconomicStress).
"""

import sdf_fuzzy as sf

# List of fuzzy concepts to be queried for each snapshot.
CONCEPTS = [
    "BasicNeedsStress",
    "EconomicStress",
    "StructuralDevelopmentStress",
    "BroadSocioEconomicStress",
]


def main():
    # Select all snapshots for the year 2021.
    snapshots = sf.select_snapshots(2021)
    # Prepare the queries for each snapshot and concept.
    queries = [f"(min-instance? {s} {c})" for s in snapshots for c in CONCEPTS]
    # Run the reasoner with the prepared queries.
    report = sf.run("app1", [sf.snapshot(s) for s in snapshots], "", queries)
    # Extract the results for each snapshot and concept.
    rows = []
    for i, s in enumerate(snapshots):
        # Compute the membership degrees for the current snapshot.
        degrees = [
            sf.value(report["results"], i * len(CONCEPTS) + j)
            for j in range(len(CONCEPTS))
        ]
        # Append the snapshot and its membership degrees to the rows list.
        rows.append((s, degrees))
    # Sort the rows by EconomicStress, then BasicNeedsStress.
    rows.sort(
        key=lambda r: (-r[1][1], -r[1][0], r[0])
    )  # by EconomicStress, then BasicNeedsStress
    # Write the sorted results to a LaTeX table.
    with open(sf.TABLES / "app1.tex", "w") as f:
        f.write("\\begin{tabularx}{\\textwidth}{lCCCC}\n\\toprule\n")
        f.write(
            "\\textbf{Snapshot} & \\textbf{BNS} & \\textbf{ES} & \\textbf{SDS} & \\textbf{BSES (OWA)}\\\\\n\\midrule\n"
        )
        for s, d in rows:
            if any(x > 0 for x in d):
                f.write(
                    f"{s.replace('_', ' ')} & "
                    + " & ".join(f"{x:.3f}" for x in d)
                    + "\\\\\n"
                )
        zero = [s for s, d in rows if not any(x > 0 for x in d)]
        f.write("\\bottomrule\n\\end{tabularx}\n")
        f.write(
            f"% snapshots with degree 0 in all four concepts ({len(zero)}): {', '.join(zero)}\n"
        )
    # Print the top 12 snapshots with their membership degrees.
    for s, d in rows[:12]:
        print(f"{s:28}", " ".join(f"{x:6.3f}" for x in d))


if __name__ == "__main__":
    main()
