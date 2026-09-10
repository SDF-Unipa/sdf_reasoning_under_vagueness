"""Query the SDF fuzzy ontology with fuzzy-dl-owl2.

Pipeline used by every application script of the paper (app1_… app4_…):

1. ``select_snapshots(year)``  – the country-year TerritorialSystem snapshots of the closure that
   carry all six fuzzy features (poverty, unemployment, growth, food insecurity, digital and clean
   energy access), read from the SQLite index of the closure built once by ``sdf_index.py``;
2. ``build_kb(individuals, workdir, axioms)`` – a *slice* of the ontology (the whole TBox/RBox of
   the schema modules plus the selected individuals with their one-hop neighbourhood, materialised
   degrees included) is written by ``build_slice`` as a temporary OWL 2 file and translated into a
   fuzzyDL knowledge base by ``FuzzyOwl2ToFuzzyDL``; analyst axioms in fuzzyDL syntax are appended;
3. ``solve(kb, queries)`` – the queries are appended to the KB, which is parsed by ``DLParserFast``
   and solved with the MILP provider configured in CONFIG.ini (Gurobi in the paper).

Only the *conversion* step touches OWL 2: reasoning happens on the fuzzyDL knowledge base, so any
fuzzyDL construct (weighted sums, OWA, modifiers, datatype restrictions, inverse roles, …) can be
used in analyst axioms and queries without changing the ontology.
"""

import json
import os
import pathlib
import re
import shutil
import sqlite3
import time
import typing

import rdflib
import sdf_index
from rdflib.namespace import OWL, RDF, RDFS, XSD

# Paths and namespaces for the fuzzy ontology.
ROOT = sdf_index.ROOT  # fuzzy_ontology/
# Directory of the current script.
CODE = pathlib.Path(__file__).resolve().parent
# Directory for generated LaTeX tables.
TABLES = CODE.parent / "tables"  # LaTeX tables included by main.tex
TABLES.mkdir(parents=True, exist_ok=True)  # standalone clones: created on first use
# Base IRI and namespaces for the fuzzy ontology.
BASE = "http://www.semanticweb.org/ontologies/fuzzydl_ontology"
# Dictionary of namespace prefixes to full IRIs.
NS = {
    "territories": BASE + "/territories#",
    "individuals": BASE + "/individuals#",
    "subjects": BASE + "/subjects#",
    "dp": BASE + "/data-property#",
}
# URIRef for the fuzzy label used in the ontology.
FUZZY_LABEL = rdflib.URIRef(BASE + "#fuzzyLabel")
# List of features considered in the fuzzy ontology.
FEATURES = (
    "povertyRate",
    "unemploymentRate",
    "economicGrowthRate",
    "foodInsecurityRate",
    "digitalAccessRate",
    "cleanEnergyAccessRate",
)


def index() -> sqlite3.Connection:
    """SQLite connection to the index of the closure (built on first use, see sdf_index).

    Returns:
        sqlite3.Connection: A connection object to the SQLite database.
    """
    return sdf_index.connect()


def local(iri: rdflib.URIRef) -> str:
    """Local name of an IRI (after the last '#' or, failing that, the last '/').

    Args:
        iri (rdflib.URIRef): The IRI to extract the local name from.

    Returns:
        str: The local name of the IRI.
    """
    return str(iri).rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def fdl_safe(name: str) -> str:
    """
    FuzzyDL identifier: parentheses dropped (as the converter does), characters outside the
    lexer's set replaced by '_', all-digit or empty names prefixed with '_'.

    Args:
        name (str): The original name to be converted to a FuzzyDL identifier.

    Returns:
        str: The FuzzyDL-safe identifier.
    """
    s = re.sub(r"[()]", "", name)
    s = re.sub(r"[^A-Za-z0-9_'/.:<>@$!?\-]", "_", s)
    return "_" + s if not s or s.isdigit() else s


def select_snapshots(year: int) -> list[str]:
    """
    Local names of the TerritorialSystem snapshots of ``year`` that have all six features.

    Args:
        year (int): The year to filter the snapshots by.

    Returns:
        list[str]: A sorted list of local names of the snapshots matching the criteria.
    """
    # Connect to the SQLite index and select snapshots that have all six features.
    marks = ",".join("?" * len(FEATURES))
    # Prepare the SQL query to select snapshots that have all six features.
    rows = sdf_index.connect().execute(
        f"SELECT s FROM stmt WHERE p IN ({marks}) GROUP BY s HAVING COUNT(DISTINCT p) = ?",
        [NS["dp"] + f for f in FEATURES] + [len(FEATURES)],
    )
    # Fetch all rows from the executed query.
    return sorted(local(s) for (s,) in rows if local(s).endswith("_" + str(year)))


def build_slice(individuals: set[str], out: pathlib.Path) -> dict[str, set[str]]:
    """
    Write the slice of the closure for ``individuals`` (full IRIs) to the OWL file ``out``.

    The slice is the TBox/RBox of the schema modules (owl:imports removed, rdf:PlainLiteral ranges
    mapped to xsd:string, ``Class(IRI)`` in fuzzy labels shortened to local names) plus every
    statement of the selected individuals and of the individuals they refer to (one hop), with
    the owl:Axiom annotations that carry the materialised degrees; rdfs:comment is left out.
    Local names that are not FuzzyDL identifiers are renamed with ``fdl_safe``.
    Returns {"schema_files", "individuals" (copied, neighbours included), "triples", "renamed"}.

    Args:
        individuals (set[str]): A set of full IRIs of the individuals to include in the slice.
        out (pathlib.Path): The path to the output OWL file.

    Returns:
        dict[str, set[str]]: A dictionary containing the schema files, individuals (including neighbors), triples, and renamed local names.
    """
    # Connect to the SQLite index and create an RDF graph for the slice.
    c = sdf_index.connect()
    # Initialize the RDF graph for the slice.
    g = rdflib.Graph()
    # Load the schema modules into the RDF graph.
    schema = [f for (f,) in c.execute("SELECT file FROM modules WHERE role = 'schema'")]
    try:
        # schema sources embedded in the index: the slice needs no ontology file on disk
        for f, xml in c.execute("SELECT file, xml FROM schema_files"):
            g.parse(data=xml, format="xml")
    except sqlite3.OperationalError:
        # older index without the schema_files table: fall back to the files in ROOT
        for f in schema:
            g.parse(ROOT / f, format="xml")
    # Remove owl:imports statements from the ontology nodes and adjust fuzzy labels for classes.
    for o in list(g.subjects(RDF.type, OWL.Ontology)):
        g.remove((o, OWL.imports, None))
    # Replace rdf:PlainLiteral ranges with xsd:string.
    for s, p, o in list(g.triples((None, RDFS.range, RDF.PlainLiteral))):
        g.remove((s, p, o))
        g.add((s, p, XSD.string))
    # Adjust fuzzy labels for classes in the RDF graph.
    for s, p, o in list(g.triples((None, FUZZY_LABEL, None))):
        if "Class(" in str(o):
            g.remove((s, p, o))
            g.add(
                (
                    s,
                    p,
                    rdflib.Literal(
                        re.sub(r"Class\(([^)]*)\)", lambda m: local(m.group(1)), str(o))
                    ),
                )
            )
    # Determine which individuals are selected and initialize the processing queue.
    is_individual = lambda iri: c.execute(
        "SELECT 1 FROM individuals WHERE iri = ?", (iri,)
    ).fetchone()
    # Filter the input individuals to include only those present in the index.
    selected = {iri for iri in individuals if is_individual(iri)}
    # Initialize the processing queue and the set of seen individuals.
    queue, seen = list(selected), set()
    while queue:
        # Pop the next individual from the queue for processing.
        iri = queue.pop()
        if iri in seen:
            # Skip this individual if it has already been seen.
            continue
        # Mark this individual as seen and create an RDF URIRef for it.
        seen.add(iri)
        s_ = rdflib.URIRef(iri)
        # Retrieve all statements for this individual from the SQLite index.
        for p, o, lit, dt, lang in c.execute(
            "SELECT p, o, lit, dt, lang FROM stmt WHERE s = ?", (iri,)
        ):
            if p == str(RDFS.comment):
                # Skip adding rdfs:comment statements to the RDF graph.
                continue
            if lit is not None:
                # Add literal statements to the RDF graph with appropriate datatype and language.
                g.add(
                    (
                        s_,
                        rdflib.URIRef(p),
                        rdflib.Literal(
                            lit,
                            datatype=rdflib.URIRef(dt) if dt else None,
                            lang=lang or None,
                        ),
                    )
                )
                continue
            # Add non-literal statements to the RDF graph as URIRefs.
            g.add((s_, rdflib.URIRef(p), rdflib.URIRef(o)))
            # If this individual is selected and the object is a new individual, add it to the processing queue.
            if (
                iri in selected and o not in seen and is_individual(o)
            ):  # only the selected ones pull neighbours
                queue.append(o)
            # Retrieve any annotations for this statement from the axiom_ann table.
            anns = c.execute(
                "SELECT prop, value FROM axiom_ann WHERE s = ? AND p = ? AND o = ?",
                (iri, p, o),
            ).fetchall()
            if (
                anns
            ):  # materialised degree on the reified assertion (otherwise the converter asserts 1.0)
                # Create a blank node to represent the reified statement and add the annotations.
                bn = rdflib.BNode()
                g.add((bn, RDF.type, OWL.Axiom))
                g.add((bn, OWL.annotatedSource, s_))
                g.add((bn, OWL.annotatedProperty, rdflib.URIRef(p)))
                g.add((bn, OWL.annotatedTarget, rdflib.URIRef(o)))
                for prop, value in anns:
                    # Add each annotation as a property-value pair to the reified statement.
                    g.add((bn, rdflib.URIRef(prop), rdflib.Literal(value)))
    # Rename any terms in the RDF graph that contain unsafe characters in their fragment identifiers.
    renamed = {}
    # Iterate over all subjects and objects in the RDF graph to identify terms with unsafe characters.
    for term in set(g.subjects()) | set(g.objects()):
        # Check if the term is a URIRef with a fragment identifier that may need renaming.
        if isinstance(term, rdflib.URIRef) and "#" in str(term):
            # Split the URI into namespace and fragment to process the fragment safely.
            ns, frag = str(term).rsplit("#", 1)
            # Generate a safe fragment identifier using the fdl_safe function.
            safe = fdl_safe(frag)
            if safe != frag:
                # Record the renaming and update all triples that reference the old term.
                renamed[safe] = frag
                # Create a new URIRef with the safe fragment identifier.
                new = rdflib.URIRef(ns + "#" + safe)
                # Replace all occurrences of the old term with the new safe term in the RDF graph.
                for t in list(g.triples((term, None, None))):
                    g.remove(t)
                    g.add((new, t[1], t[2]))
                # Replace all occurrences of the old term in the object position as well.
                for t in list(g.triples((None, None, term))):
                    g.remove(t)
                    g.add((t[0], t[1], new))
    # After renaming all unsafe terms, serialize the RDF graph to the specified output file.
    g.serialize(
        destination=str(out), format="xml"
    )  # plain RDF/XML: pretty-xml may duplicate list cells
    # Return a summary of the processing, including the number of schema files, individuals, triples, and renamed terms.
    return {
        "schema_files": schema,
        "individuals": len(seen),
        "triples": len(g),
        "renamed": renamed,
    }


def prune_slice(
    owl: pathlib.Path,
    drop_prefixes: tuple[str, ...] = ("Cluster_",),
    drop_properties: tuple[str, ...] = ("isElementOf",),
) -> int:
    """
    Remove from the slice OWL file the individuals whose local name starts with one of
    ``drop_prefixes`` (with every triple that mentions them) and the triples of ``drop_properties``.

    Used by the applications that select the countries: a country carries ~100 cluster-membership
    records (one per model and cluster type) that the questions never use and that would multiply
    the translation time of the Fuzzy OWL 2 converter (see the paper, Section 3.7). Returns the number of triples removed.

    Args:
        owl (pathlib.Path): The path to the slice OWL file to be pruned.
        drop_prefixes (tuple[str, ...], optional): Prefixes of individual local names to drop. Defaults to ("Cluster_",).
        drop_properties (tuple[str, ...], optional): Properties whose triples should be dropped. Defaults to ("isElementOf",).

    Returns:
        int: The number of triples removed.
    """
    import rdflib

    # Load the OWL file into an RDF graph.
    g = rdflib.Graph()
    g.parse(owl)
    # Initialize a set to keep track of triples to be removed.
    props = {rdflib.URIRef(BASE + "/object-property#" + p) for p in drop_properties}
    # Keep track of the triples that will be removed.
    gone = set()
    for s, p, o in g:
        # Check if the triple should be removed based on the property or the subject/object prefixes.
        if p in props or any(
            str(x).rsplit("#")[-1].startswith(drop_prefixes)
            for x in (s, o)
            if isinstance(x, rdflib.URIRef)
        ):
            # Mark the triple for removal.
            gone.add((s, p, o))
    # Remove the marked triples from the graph.
    for t in gone:
        g.remove(t)
    # Serialize the updated graph back to the OWL file.
    g.serialize(owl, format="xml")
    return len(gone)


def build_kb(
    individuals: set[str], workdir: pathlib.Path, axioms="", patches=(), prune=False
) -> tuple[pathlib.Path, dict]:
    """
    Write the slice OWL file, convert it to fuzzyDL and append the analyst ``axioms`` (fuzzyDL text).

    Args:
        individuals (set[str]): Full IRIs of the individuals to include in the slice.
        workdir (pathlib.Path): The working directory where the slice and KB files will be created.
        axioms (str, optional): FuzzyDL axioms to append to the KB. Defaults to "".
        patches (tuple[tuple[str, str], ...], optional): Text substitutions to apply to the translated KB before appending axioms. Defaults to ().
        prune (bool, optional): Whether to prune the slice by removing cluster-membership records. Defaults to False.

    Returns:
        tuple[pathlib.Path, dict]: The path to the generated KB and a dictionary of statistics.
    """
    # Ensure the working directory exists and copy the configuration file.
    workdir = pathlib.Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    # Copy the configuration file to the working directory.
    shutil.copy(
        CODE / "CONFIG.ini", workdir / "CONFIG.ini"
    )  # fuzzy-dl-owl2 reads it from the cwd
    # Define the path to the slice OWL file.
    owl = workdir / "slice.owl"
    t0 = time.time()
    # Build the slice OWL file with the specified individuals.
    stats = build_slice(individuals, owl)
    if prune:
        # Prune the slice by removing cluster-membership records if requested.
        stats["pruned_triples"] = prune_slice(owl)
    # Record the time taken to build and optionally prune the slice.
    stats["slice_seconds"] = round(time.time() - t0, 2)
    # Change the current working directory to the workdir for the translation process.
    cwd = os.getcwd()
    os.chdir(workdir)
    # Translate the slice OWL file to fuzzyDL format.
    try:
        from fuzzy_dl_owl2.fuzzyowl2.fuzzyowl2_to_fuzzydl import FuzzyOwl2ToFuzzyDL

        t0 = time.time()
        # Record the start time for the translation process.
        FuzzyOwl2ToFuzzyDL(
            str(owl), "kb.fdl", base_iri=BASE + "#"
        ).translate_owl2ontology()
        # Record the time taken for the translation process.
        stats["owl2fdl_seconds"] = round(time.time() - t0, 2)
    finally:
        # Restore the original working directory.
        os.chdir(cwd)
    # Define the path to the generated KB file.
    kb = workdir / "results" / "kb.fdl"
    # Apply text patches and append analyst axioms to the KB.
    text = kb.read_text()
    # Apply each text patch to the KB content.
    for old, new in patches:
        # Ensure the old text exists in the KB before applying the patch.
        assert old in text, old
        # Apply the patch by replacing the old text with the new text.
        text = text.replace(old, new)
    # Append the analyst axioms to the KB content.
    text = (
        text.rstrip("\n") + "\n\n# ---- analyst axioms ----\n" + axioms.strip() + "\n"
    )
    # Write the modified KB content back to the file.
    kb.write_text(text)
    # Count the number of lines in the KB for statistics.
    stats["kb_lines"] = text.count("\n")
    return kb, stats


def solve(
    kb: pathlib.Path,
    queries: list[str],
    workdir: pathlib.Path = None,
    fresh: bool = False,
) -> tuple[list[dict[str, object]], float]:
    """Append ``queries`` (fuzzyDL query lines) to the KB and solve them one by one.

    Returns [{"query", "value", "seconds"}] in the order of the queries; ``value`` is None when the KB is inconsistent for that query. With ``fresh`` every query is answered on a freshly parsed KB: the workaround used with fuzzy-dl-owl2 1.0.27, whose ABox-free clone inherited the ``processed_assertions`` of the expanded base KB (TBox queries after an instance query returned trivial bounds) and whose shallow clone of the blocking bookkeeping crashed in batch mode; bothare fixed in the patched version used for the paper, so the default is a single batch.

    Args:
        kb: Path to the KB file.
        queries: List of fuzzyDL query lines.
        workdir: Working directory for the solver.
        fresh: Whether to answer each query on a freshly parsed KB.

    Returns:
        A tuple containing a list of dictionaries with query results and the total time taken.
    """
    if fresh:
        # If fresh is True, solve each query on a freshly parsed KB.
        out, secs = [], 0.0
        for q in queries:
            # Solve the current query on a freshly parsed KB.
            r, ps = solve(kb, [q], workdir)
            # Accumulate the results and time taken for the current query.
            out += r
            # Round the accumulated time to two decimal places for consistency.
            secs += ps
        # Return the accumulated results and total time taken for all queries.
        return out, round(secs, 2)
    # If fresh is False, solve all queries in a single batch.
    kb = pathlib.Path(kb).resolve()
    # Ensure the working directory exists.
    workdir = pathlib.Path(
        workdir or kb.parent.parent
    ).resolve()  # absolute: the solver runs with cwd = workdir
    # Prepare the KB file with appended queries for the solver.
    kbq = workdir / "kb_query.fdl"
    # Write the KB with queries to the file.
    kbq.write_text(
        kb.read_text().rstrip("\n")
        + "\n\n# ---- queries ----\n"
        + "\n".join(queries)
        + "\n"
    )
    # Change the current working directory to the solver's working directory.
    cwd = os.getcwd()
    os.chdir(workdir)
    try:
        from fuzzy_dl_owl2.fuzzydl.parser import DLParserFast

        t0 = time.time()
        # Parse the KB and extract the queries.
        kb_obj, qs = DLParserFast.get_kb(str(kbq))
        # Solve the KB to prepare it for query answering.
        kb_obj.solve_kb()
        # Record the time taken to parse and solve the KB.
        parse_seconds = round(time.time() - t0, 2)
        out = []
        # Solve each query and record the time taken for each.
        for q in qs:
            t0 = time.time()
            # Record the start time for solving the current query.
            sol = q.solve(kb_obj)
            # Solve the current query against the KB object.
            out.append(
                {
                    "query": str(q),
                    "value": sol.get_solution() if sol.is_consistent_kb() else None,
                    "seconds": round(time.time() - t0, 3),
                }
            )
    finally:
        # Restore the original working directory.
        os.chdir(cwd)
    # Return the query results and the time taken to parse and solve the KB.
    return out, parse_seconds


def run(
    name: str,
    individuals: set[str],
    axioms: list[str],
    queries: list[str],
    patches: tuple = (),
    prune: bool = False,
    fresh: bool = False,
) -> dict[str, typing.Any]:
    """
    Build the slice KB for ``individuals``, solve ``queries`` and save results/<name>.json.

    Args:
        name: The name of the result file.
        individuals: A set of individual IRIs to include in the KB slice.
        axioms: A list of axioms to include in the KB.
        queries: A list of queries to solve against the KB.
        patches: Optional tuple of patches to apply to the KB.
        prune: Whether to prune the KB.
        fresh: Whether to force a fresh solve.

    Returns:
        A dictionary containing the report with statistics and query results.
    """
    workdir = CODE / "work" / name
    # Build the KB slice and collect statistics.
    kb, stats = build_kb(individuals, workdir, axioms, patches, prune)
    # Solve the queries against the built KB and record the time taken.
    results, parse_seconds = solve(kb, queries, workdir, fresh)
    # Prepare the report dictionary with statistics and query results.
    report = {
        "name": name,
        "stats": stats,
        "parse_seconds": parse_seconds,
        "results": results,
    }
    # Save the report to a JSON file in the results directory.
    (CODE / "results").mkdir(exist_ok=True)
    (CODE / "results" / f"{name}.json").write_text(json.dumps(report, indent=1))
    # Print a summary of the statistics and query results.
    print(
        f"{name}: {stats['individuals']} individuals, {stats['triples']} triples (pruned {stats.get('pruned_triples', 0)}), "
        f"slice {stats['slice_seconds']} s, owl2fdl {stats['owl2fdl_seconds']} s, "
        f"parse+solve_kb {parse_seconds} s, {len(results)} queries in "
        f"{sum(r['seconds'] for r in results):.2f} s"
    )
    # Return the report dictionary containing the statistics and query results.
    return report


def snapshot(name: str) -> str:
    """
    Full IRI of a territorial snapshot from its local name (e.g. Italy_2021).

    Args:
        name: The local name of the territorial snapshot.

    Returns:
        The full IRI of the territorial snapshot.
    """
    return NS["territories"] + name


def country(name: str) -> str:
    """
    Full IRI of a UNECE country individual (e.g. Italy).

    Args:
        name: The local name of the country.

    Returns:
        The full IRI of the country individual.
    """
    return NS["individuals"] + name


def value(results: list[dict], i: int) -> float:
    """
    Numeric value of the i-th result (None → 0.0, i.e. no positive degree entailed).

    Args:
        results: A list of query result dictionaries.
        i: The index of the result to retrieve the numeric value for.

    Returns:
        The numeric value of the i-th result, or 0.0 if the value is None.
    """
    v = results[i]["value"]
    return 0.0 if v is None else float(v)
