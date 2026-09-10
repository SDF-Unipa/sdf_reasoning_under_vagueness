"""Application 4 - analyst-defined concepts, linguistic hedges and semantic checks.

An analyst can ask questions the ontology designers did not anticipate by defining concepts at query
time (in fuzzyDL syntax, without editing the OWL 2 ontology):

    JoblessGrowth   = (some economicGrowthRate PositiveEconomicGrowth) and (some unemploymentRate HighUnemployment)
    VeryHighUnemployment = some unemploymentRate (very HighUnemployment)      -- "very" = linear modifier
    SocialAlarm     = owa (0.6 0.3 0.1) (BasicNeedsStress EconomicStress StructuralDevelopmentStress)
    InclusiveRebound = w-sum (0.4 TerritoryWithHighEconomicGrowth) (0.3 TerritoryWithLowUnemployment) (0.3 TerritoryWithLowPoverty)

and by asking TBox-level questions: to what degree does a crisp "severe" concept of the ontology
imply its graded counterpart (min-subs?), and can two linguistic terms of the same feature hold at
the same time (max-sat?). Output: results/app4.json, tables/app4.tex.
"""

import sdf_fuzzy as sf

# Analyst-defined concepts, linguistic hedges, and semantic checks for the ontology.
# The AXIOMS string defines the new concepts and modifiers.
# The CONCEPTS list contains the names of the new concepts.
# The TBOX_QUERIES list contains the TBox-level queries to be asked.
AXIOMS = """
(define-modifier very linear-modifier(2.0))
(define-concept JoblessGrowth (and (some economicGrowthRate PositiveEconomicGrowth) (some unemploymentRate HighUnemployment)))
(define-concept VeryHighUnemployment (some unemploymentRate (very HighUnemployment)))
(define-concept SocialAlarm (owa (0.5 0.3 0.2) (BasicNeedsStress EconomicStress StructuralDevelopmentStress)))
(define-concept InclusiveRebound (w-sum (0.5 TerritoryWithHighEconomicGrowth) (0.25 TerritoryWithLowUnemployment) (0.25 TerritoryWithLowPoverty)))
"""
CONCEPTS = ["JoblessGrowth", "VeryHighUnemployment", "SocialAlarm", "InclusiveRebound"]
TBOX_QUERIES = [
    "(min-subs? BasicNeedsStress SevereBasicNeedsDeprivation)",
    "(min-subs? EconomicStress StructuralLockInRisk)",
    "(min-subs? StructuralDevelopmentStress SevereBasicNeedsDeprivation)",
    "(max-sat? (and (some povertyRate LowPoverty) (some povertyRate HighPoverty)))",
    "(max-sat? (and (some povertyRate ModeratePoverty) (some povertyRate HighPoverty)))",
    "(max-sat? (and (some unemploymentRate ModerateUnemployment) (some unemploymentRate HighUnemployment)))",
    "(max-sat? (and SevereBasicNeedsDeprivation (not BasicNeedsStress)))",
    "(max-sat? (and StructuralLockInRisk (not EconomicStress)))",
    "(max-sat? JoblessGrowth)",
]


def main():
    # Select all snapshots for the year 2021.
    snapshots = sf.select_snapshots(2021)
    # instance and TBox queries in one batch (fuzzy-dl-owl2 1.0.27 needed a freshly parsed KB per TBox query:
    # its ABox-free clone inherited processed_assertions from the expanded base KB; fixed locally)
    # Prepare the list of queries for the reasoning process, including both instance-level and TBox-level queries.
    queries = [
        f"(min-instance? {s} {c})" for s in snapshots for c in CONCEPTS
    ] + TBOX_QUERIES
    # Run the reasoning process with the prepared individuals, axioms, and queries.
    report = sf.run("app4", [sf.snapshot(s) for s in snapshots], AXIOMS, queries)
    # Extract the number of concepts for later use in indexing the results.
    k = len(CONCEPTS)
    # Extract the degrees of membership for each snapshot and each concept.
    rows = [
        (s, [sf.value(report["results"], i * k + j) for j in range(k)])
        for i, s in enumerate(snapshots)
    ]
    # Sort the rows based on the degrees of membership in specific concepts for display purposes.
    rows.sort(key=lambda r: (-r[1][2], -r[1][0], r[0]))
    # Generate the LaTeX table summarizing the snapshot degrees of membership.
    with open(sf.TABLES / "app4.tex", "w") as f:
        f.write(
            "\\begin{adjustwidth}{-\\extralength}{0cm}\n\\centering\n\\begin{tabularx}{\\fulllength}{lCCCC}\n\\toprule\n"
        )
        f.write(
            "\\textbf{Snapshot} & \\textbf{Jobless\\-Growth} & \\textbf{VeryHigh\\-Unemployment} & \\textbf{Social\\-Alarm} & \\textbf{Inclusive\\-Rebound}\\\\\n\\midrule\n"
        )
        for s, d in rows:
            if any(x > 0 for x in d[:3]) or d[3] >= 0.9:
                f.write(
                    f"{s.replace('_', ' ')} & "
                    + " & ".join(f"{x:.3f}" for x in d)
                    + "\\\\\n"
                )
        f.write("\\bottomrule\n\\end{tabularx}\n\\end{adjustwidth}\n")
    # Generate the LaTeX table summarizing the TBox query results.
    with open(sf.TABLES / "app4_tbox.tex", "w") as f:
        f.write(
            "\\begin{adjustwidth}{-\\extralength}{0cm}\n\\centering\n\\begin{tabularx}{\\fulllength}{Xc}\n\\toprule\n\\textbf{Query} & \\textbf{Answer}\\\\\n\\midrule\n"
        )
        for q, r in zip(TBOX_QUERIES, report["results"][len(snapshots) * k :]):
            qq = q.replace("_", "\\_").replace(
                " ", " \\allowbreak "
            )  # long queries may break at spaces
            f.write(f"\\texttt{{{qq}}} & {r['value']}\\\\\n")
        f.write("\\bottomrule\n\\end{tabularx}\n\\end{adjustwidth}\n")
    # Print the degrees of the first few snapshots for quick inspection.
    for s, d in rows[:10]:
        print(f"{s:28}", " ".join(f"{x:6.3f}" for x in d))
    # Print the results of the TBox queries for quick inspection.
    for r in report["results"][len(snapshots) * k :]:
        print(r["query"], "->", r["value"])


if __name__ == "__main__":
    main()
