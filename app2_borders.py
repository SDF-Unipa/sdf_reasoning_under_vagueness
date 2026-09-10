"""Application 2 - stress across land borders.

Question: to what degree is a territory bordered by an economically stressed territory, and
which are the most asymmetric borders?

The slice contains the complete 2021 snapshots, their countries (selected explicitly, so that their
object links are part of the slice) and the Distance individuals of the subjects module (one per pair of bordering countries, distance 0). The analyst concept

    StressedNeighbourhood = some hasLocation (some hasDistance (some isLocationOf EconomicStress))

chains the snapshot -> country -> bordering country -> its 2021 snapshot -> EconomicStress; with
crisp roles its degree is the maximum EconomicStress degree among the neighbouring snapshots
(existential restriction = supremum of a t-norm). The reasoner also answers the crisp questions
"do France and Italy share a border?" and "is Distance_France_Italy a BorderingDistance?".
Output: results/app2.json and tables/app2.tex.
"""

import sdf_fuzzy as sf

# Axioms for the application (defines the concepts used in the reasoning process)
AXIOMS = """
(symmetric borders)
(define-concept StressedNeighbourhood (some hasLocation (some borders (some isLocationOf EconomicStress))))
(define-concept BasicNeedsNeighbourhood (some hasLocation (some borders (some isLocationOf BasicNeedsStress))))
(define-concept LandReachableStress (some hasLocation (some hasDistance (some isLocationOf EconomicStress))))
"""


def border_pairs(countries: set[str]) -> list[tuple[str, str, str]]:
    """
    (Distance local name, country A, country B) for the bordering pairs among ``countries``.

    Args:
        countries: A set of country names to consider for bordering pairs.

    Returns:
        A sorted list of tuples, each containing the local name of the Distance individual and the two countries it connects.
    """
    # Create an index for querying the RDF store.
    c = sf.index()
    ends = {}
    # Extract the distance information for each Distance individual.
    for p in ("distanceFrom", "distanceTo"):
        for s, o in c.execute(
            "SELECT s, o FROM stmt WHERE p = ?", (sf.BASE + "/object-property#" + p,)
        ):
            # Store the local names of the countries connected by this Distance individual.
            ends.setdefault(s, {})[p] = o.rsplit("#")[-1]
    out = []
    # Filter the Distance individuals to include only those connecting countries in the given set.
    for d, e in ends.items():
        # Skip Distance individuals that do not have both distanceFrom and distanceTo information.
        a, b = e.get("distanceFrom"), e.get("distanceTo")
        if a in countries and b in countries:
            # Include this Distance individual as it connects two countries in the given set.
            out.append((d, a, b))
    # Return the sorted list of valid Distance individuals connecting countries in the given set.
    return sorted(out)


def main():
    # Select all snapshots for the year 2021.
    snapshots = sf.select_snapshots(2021)
    # Extract the set of countries from the snapshots.
    countries = {s.rsplit("_", 1)[0] for s in snapshots}
    # Determine the bordering pairs among the selected countries.
    pairs = border_pairs(countries)
    # the countries are selected explicitly: only selected individuals keep their object links
    # (hasDistance, hasEconomy, ...); neighbours contribute their data values and degrees
    # Prepare the list of individuals to be included in the reasoning process.
    individuals = [sf.snapshot(s) for s in snapshots] + [
        sf.country(c) for c in sorted(countries)
    ]
    # Include the Distance individuals corresponding to the bordering pairs.
    individuals += [d for d, _, _ in pairs]
    # Prepare the queries for the reasoning process.
    # Queries for the own EconomicStress of each snapshot.
    queries = [f"(min-instance? {s} EconomicStress)" for s in snapshots]
    # Queries for the StressedNeighbourhood of each snapshot.
    queries += [f"(min-instance? {s} StressedNeighbourhood)" for s in snapshots]
    # Queries for the BasicNeedsNeighbourhood of each snapshot.
    queries += [f"(min-instance? {s} BasicNeedsNeighbourhood)" for s in snapshots]
    # Additional specific queries for certain snapshots and distances.
    queries += [
        "(min-instance? Armenia_2021 LandReachableStress)",
        "(min-instance? Italy_2021 LandReachableStress)",
        "(min-related? Italy France hasDistance)",
        "(min-instance? Distance_France_Italy BorderingDistance)",
        "(min-instance? Distance_France_Italy ShortDistance)",
        "(min-instance? Distance_France_Italy LongDistance)",
    ]
    # Add axioms stating that the countries in each bordering pair are related by the 'borders' relation.
    axioms = AXIOMS + "".join(f"(related {a} {b} borders 1.0)\n" for _, a, b in pairs)
    # Run the reasoning process with the prepared individuals, axioms, and queries.
    report = sf.run("app2", individuals, axioms, queries, prune=True)
    # Extract the number of snapshots for later use in indexing the results.
    n = len(snapshots)
    # Extract the values of the own EconomicStress for each snapshot.
    own = {s: sf.value(report["results"], i) for i, s in enumerate(snapshots)}
    # Extract the values of the StressedNeighbourhood for each snapshot.
    neigh = {s: sf.value(report["results"], n + i) for i, s in enumerate(snapshots)}
    # Extract the values of the BasicNeedsNeighbourhood for each snapshot.
    bneigh = {
        s: sf.value(report["results"], 2 * n + i) for i, s in enumerate(snapshots)
    }
    # the neighbour that realises the supremum (for the table): highest own degree among bordering countries
    nb = {}
    for d, a, b in pairs:
        # Build the neighbour list for each country based on the bordering pairs.
        nb.setdefault(a, []).append(b)
        nb.setdefault(b, []).append(a)
    rows = []
    for s in snapshots:
        # Determine the country corresponding to the current snapshot.
        cty = s.rsplit("_", 1)[0]
        # Determine the candidate neighbours and select the one with the highest own EconomicStress.
        cands = [(own.get(f"{x}_2021", 0.0), x) for x in nb.get(cty, [])]
        best = max(cands) if cands else (0.0, "-")
        # Append the snapshot data along with the best neighbour and the gap between neighbourhood and own stress.
        rows.append((s, own[s], neigh[s], bneigh[s], best[1], abs(neigh[s] - own[s])))
    # Sort the rows primarily by neighbourhood stress (descending), then by the gap (descending), and finally by snapshot name.
    rows.sort(key=lambda r: (-r[2], -r[5], r[0]))
    # Write the sorted data to a LaTeX table.
    with open(sf.TABLES / "app2.tex", "w") as f:
        f.write("\\begin{tabularx}{\\textwidth}{lCCCl}\n\\toprule\n")
        f.write(
            "\\textbf{Snapshot} & \\textbf{ES (own)} & \\textbf{ES (neighbourhood)} & \\textbf{BNS (neighbourhood)} & \\textbf{Most stressed neighbour}\\\\\n\\midrule\n"
        )
        for s, o, ne, bn, best, gap in rows:
            if ne > 0 or o > 0 or bn > 0:
                f.write(
                    f"{s.replace('_', ' ')} & {o:.3f} & {ne:.3f} & {bn:.3f} & {best.replace('_', ' ')}\\\\\n"
                )
        f.write("\\bottomrule\n\\end{tabularx}\n")
        crisp = report["results"][
            3 * n :
        ]  # LandReachableStress examples + crisp checks
        f.write(
            "% crisp checks: "
            + "; ".join(f"{r['query']} -> {r['value']}" for r in crisp)
            + "\n"
        )
    # Print the top 12 rows for quick inspection.
    for r in rows[:12]:
        print(
            f"{r[0]:28} own {r[1]:.3f}  neighbourhood {r[2]:.3f}  bns-neigh {r[3]:.3f}  via {r[4]}"
        )
    # Print the crisp checks for quick inspection.
    for r in report["results"][3 * n :]:
        print(r["query"], "->", r["value"])


if __name__ == "__main__":
    main()
