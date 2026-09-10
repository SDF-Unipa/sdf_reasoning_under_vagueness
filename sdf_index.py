"""
Lightweight SQLite index of the SDF ontology closure, used by the reasoning pipeline.

The closure (SDF_fuzzy_annotated.owl and its imports, 4.5 million triples) is parsed once with rdflib (about two minutes) and reduced to what the pipeline needs:

- ``modules``:     role of each module ('schema': declares classes/properties/datatypes and no individual; 'abox': declares individuals; 'annotations': neither);
- ``individuals``: IRIs of the named individuals;
- ``stmt``:        the statements whose subject is a named individual (object IRI or literal);
- ``axiom_ann``:   the annotations of reified object assertions (owl:Axiom), i.e. the materialised membership degrees.

Usage: ``python3 sdf_index.py`` (or ``sdf_index.connect()``, which builds the index on demand).
"""

import os
import pathlib
import sqlite3
import time
import typing

import rdflib
from rdflib.namespace import OWL, RDF, RDFS

# directory holding the ontology modules: two levels above this script by default,
# overridable with the SDF_ONTOLOGY_DIR environment variable
ROOT = pathlib.Path(os.environ.get("SDF_ONTOLOGY_DIR", "").strip() or pathlib.Path(__file__).resolve().parents[2])
DB = pathlib.Path(__file__).resolve().parent / "work" / "index.db"
MODULES = (  # import closure of SDF_fuzzy_annotated.owl, ABox modules first
    "SDF_individuals.owl",
    "SDF_territories.owl",
    "SDF_subjects.owl",
    "SDF_ext.owl",
    "SDF_fuzzy_annotated.owl",
)
# RDF types considered part of the schema
SCHEMA_TYPES = {OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty, RDFS.Datatype}
# RDF terms used for reification of object assertions
REIFICATION = {
    RDF.type,
    OWL.annotatedSource,
    OWL.annotatedProperty,
    OWL.annotatedTarget,
}
# SQL schema for the index tables
DDL = """
CREATE TABLE modules(file TEXT PRIMARY KEY, role TEXT);
CREATE TABLE schema_files(file TEXT PRIMARY KEY, xml TEXT);
CREATE TABLE individuals(iri TEXT PRIMARY KEY);
CREATE TABLE stmt(s TEXT, p TEXT, o TEXT, lit TEXT, dt TEXT, lang TEXT);
CREATE TABLE axiom_ann(s TEXT, p TEXT, o TEXT, prop TEXT, value TEXT);
CREATE INDEX stmt_s ON stmt(s);
CREATE INDEX stmt_p ON stmt(p);
CREATE INDEX axiom_ann_spo ON axiom_ann(s, p, o);
"""


def module_role(g: rdflib.Graph) -> str:
    """
    Determine the role of a module based on the declarations found in the module graph.

    Args:
        g (rdflib.Graph): The RDF graph of the module.

    Returns:
        str: 'abox', 'schema' or 'annotations' based on the module graph.
    """
    kinds = set(g.objects(None, RDF.type))
    if OWL.NamedIndividual in kinds:
        return "abox"
    return "schema" if kinds & SCHEMA_TYPES else "annotations"


def axiom_annotations(
    g: rdflib.Graph,
) -> typing.Generator[typing.Tuple[str, str, str, str, str], None, None]:
    """
    Yield the annotations of every reified object assertion in the graph.

    Args:
        g (rdflib.Graph): The RDF graph to inspect.

    Yields:
        Tuple[str, str, str, str, str]: (source, property, target, annotation property, value) of every reified object assertion.
    """
    # Iterate over all reified object assertions in the graph.
    for bn in g.subjects(RDF.type, OWL.Axiom):
        # Get the source, property, and target of the reified object assertion.
        s = g.value(bn, OWL.annotatedSource)
        p = g.value(bn, OWL.annotatedProperty)
        o = g.value(bn, OWL.annotatedTarget)
        # Skip if any of the source, property, or target is missing.
        if not all(isinstance(t, rdflib.URIRef) for t in (s, p, o)):
            continue  # anonymous or literal target: not an object assertion of an individual
        # Yield all annotations for the reified object assertion.
        for prop, value in g.predicate_objects(bn):
            # Skip the reification properties themselves.
            if prop in REIFICATION:
                continue
            yield str(s), str(p), str(o), str(prop), str(value)


def build(db: pathlib.Path = DB) -> None:
    """
    Parse the modules and write the index to ``db`` (replaced if it exists).

    This function will create a new SQLite database at the specified path and populate it with the parsed RDF data from the modules.

    Args:
        db (pathlib.Path): The path to the SQLite database file. If the file exists, it will be replaced.
    """
    # Ensure the database directory exists and remove any existing database file.
    db = pathlib.Path(db)
    # Convert the database path to a pathlib.Path object.
    db.parent.mkdir(parents=True, exist_ok=True)
    # Remove any existing database file.
    db.unlink(missing_ok=True)
    # Connect to the new database and initialize it with the DDL.
    c = sqlite3.connect(db)
    # Execute the DDL script to create the necessary tables and schema.
    c.executescript(DDL)
    # Keep track of known individuals across all modules.
    known = (
        set()
    )  # individuals declared so far (a later module may add statements about them)
    for name in MODULES:
        # Record the start time for processing this module.
        t0 = time.time()
        # Parse the RDF graph for this module.
        g = rdflib.Graph()
        g.parse(ROOT / name, format="xml")
        # Insert the module metadata into the database.
        role = module_role(g)
        c.execute("INSERT INTO modules VALUES(?,?)", (name, role))
        if role == "schema":
            # embed the schema source: the slice builder needs the full TBox/RBox and can
            # then work from the index alone, without the ontology files on disk
            c.execute("INSERT INTO schema_files VALUES(?,?)", (name, (ROOT / name).read_text(encoding="utf-8")))
        # Identify and insert declared individuals into the database.
        declared = {
            s
            for s in g.subjects(RDF.type, OWL.NamedIndividual)
            if isinstance(s, rdflib.URIRef)
        }
        # Insert the declared individuals into the database, ignoring duplicates.
        c.executemany(
            "INSERT OR IGNORE INTO individuals VALUES(?)", [(str(s),) for s in declared]
        )
        # Update the set of known individuals with the newly declared ones.
        known |= {str(s) for s in declared}
        # Collect the statements to be inserted into the database.
        rows = []
        for s, p, o in g:
            # Skip statements where the subject is not a known individual or the object is a blank node.
            if (
                not isinstance(s, rdflib.URIRef)
                or str(s) not in known
                or isinstance(o, rdflib.BNode)
            ):
                continue
            # Handle literal objects separately from URI objects.
            if isinstance(o, rdflib.Literal):
                # Append the literal object to the rows with its datatype and language information.
                rows.append(
                    (
                        str(s),
                        str(p),
                        None,
                        str(o),
                        str(o.datatype) if o.datatype else None,
                        o.language,
                    )
                )
            else:
                # Append the URI object to the rows with placeholders for literal-specific fields.
                rows.append((str(s), str(p), str(o), None, None, None))
        # Insert the collected statements into the database.
        c.executemany("INSERT INTO stmt VALUES(?,?,?,?,?,?)", rows)
        # Insert the collected axiom annotations into the database.
        c.executemany(
            "INSERT INTO axiom_ann VALUES(?,?,?,?,?)", list(axiom_annotations(g))
        )
        # Commit the changes to the database.
        c.commit()
        # Print a summary of the indexing process for this module.
        print(
            f"{name}: {len(g)} triples, {len(rows)} statements indexed in {time.time() - t0:.0f} s"
        )
    # Close the database connection after processing all modules.
    c.close()


def connect(db: pathlib.Path = DB) -> sqlite3.Connection:
    """
    Connection to the index, built on first use.
    Args:
        db (pathlib.Path): The path to the SQLite database file.
    Returns:
        sqlite3.Connection: A connection object to the SQLite database.
    """
    # Check if the database file exists, and build it if it doesn't.
    if not pathlib.Path(db).exists():
        build(db)
    # Return a connection to the SQLite database.
    return sqlite3.connect(db)


if __name__ == "__main__":
    build()
