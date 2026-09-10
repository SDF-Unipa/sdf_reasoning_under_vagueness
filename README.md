# SDF reasoning under vagueness

Reproducible fuzzy-ontology reasoning pipeline over Sustainable Development Goal data, and the
five geopolitical applications of the companion paper (*Fuzzy Ontology Reasoning over
Sustainable Development Data*). Everything is plain Python; the only dependencies are
[`fuzzy-dl-owl2`](https://github.com/SDF-Unipa/fuzzy_dl_owl2) (>= 1.0.30), `rdflib`, and a MILP
solver supported by the library (Gurobi 12 in the reference runs).

## Ontology

The pipeline reasons over the import closure of the SDF fuzzy OWL 2 ontology, five RDF/XML
modules distributed separately (never through this repository):

| Module | Content |
| ------ | ------ |
| `SDF_ext.owl` | schema: TBox/RBox and the fuzzy layer (Fuzzy OWL 2 annotations) |
| `SDF_individuals.owl` | UNECE SDG observations |
| `SDF_territories.owl` | country-year snapshots with the six features and materialised degrees |
| `SDF_subjects.owl` | geopolitical layer: subjects, economies, distances |
| `SDF_fuzzy_annotated.owl` | documentation annotations (imports the other four) |

There are two ways to reproduce the results:

1. **From the ontology** — point the pipeline at the directory containing the five files with
   the `SDF_ONTOLOGY_DIR` environment variable (default: two directories above this one); the
   first run builds the SQLite index (`work/index.db`, ~5 minutes).
2. **From the prebuilt index** — download `index.db.zst` from the
   [releases page](https://github.com/SDF-Unipa/sdf_reasoning_under_vagueness/releases) and
   unpack it into `work/`:

   ```sh
   zstd -d index.db.zst -o work/index.db
   ```

   The index embeds the schema module, so the whole pipeline runs from it alone, with no
   ontology file on disk.

## Layout

| File | Role |
| ------ | ------ |
| `sdf_index.py` | Builds `work/index.db`, the SQLite index of the import closure. |
| `sdf_fuzzy.py` | The pipeline: snapshot selection, slice extraction, OWL 2 → fuzzyDL translation, query solving, shared driver. |
| `app1_profiling.py` … `app5_trajectories.py` | The five applications; one self-contained script each. |
| `CONFIG.ini` | Settings read by `fuzzy-dl-owl2` from the working directory (copied next to every generated KB). |
| `work/` | Generated (git-ignored): the index and the per-application working directories (`slice.owl`, `results/kb.fdl`, `kb_query.fdl`). |
| `results/` | One JSON report per application — the reference values of the paper (rerunning overwrites them). |

## The SQLite index (`sdf_index.py`)

Parsing the whole closure with `rdflib` (4.5 M triples, ~1 GB of RDF/XML) takes minutes, so it is
done once: `sdf_index.build()` parses the five modules and writes four tables:

- `modules(file, role)` — role of each module, derived from its declarations:
  `schema` (classes/properties/datatypes, no individual), `abox` (declares individuals),
  `annotations` (neither);
- `individuals(iri)` — the 418,637 named individuals;
- `stmt(s, p, o, lit, dt, lang)` — the 4.2 M statements whose subject is a named individual
  (object IRI, or literal value with datatype and language);
- `axiom_ann(s, p, o, prop, value)` — the 57,656 `owl:Axiom` reifications, i.e. the materialised
  membership degrees of the graded assertions;
- `schema_files(file, xml)` — the RDF/XML source of the schema modules, embedded so that slice
  extraction works from the index alone.

The database (`work/index.db`, ~2.4 GB) is created on first use (`sdf_index.connect()`); building
it takes about five minutes on a laptop. Delete the file to force a rebuild after the ontology
changes.

## The pipeline (`sdf_fuzzy.py`)

1. **Selection** — `select_snapshots(year)` returns the country--year `TerritorialSystem`
   snapshots that carry all six features (poverty, unemployment, growth, food insecurity,
   digital access, clean-energy access): one SQL `GROUP BY` on `stmt`. `snapshot(name)` and
   `country(name)` build full IRIs.
2. **Slice** — `build_slice(individuals, out)` writes a self-contained OWL 2 file: the schema
   modules parsed in full (with three sanitisations: `owl:imports` removed,
   `rdf:PlainLiteral` ranges → `xsd:string`, `Class(IRI)` inside Fuzzy OWL 2 labels → local
   names), plus every statement of the selected individuals and of the individuals they
   reference (one hop — only *selected* individuals pull their neighbours), plus the
   `owl:Axiom` annotations carrying the degrees (without them the translator would assert
   degree 1.0). Local names that are not valid fuzzyDL identifiers are renamed (`fdl_safe`,
   reversible map in the returned stats). Serialised as plain RDF/XML (`pretty-xml` may
   duplicate RDF list cells).
3. **Translation** — `build_kb(individuals, workdir, axioms, patches=(), prune=False)` runs
   `build_slice`, then `FuzzyOwl2ToFuzzyDL` on the slice (this dominates the running time), and
   appends the analyst `axioms` (a string in fuzzyDL syntax) to `results/kb.fdl`.
   `patches` are `(old, new)` text substitutions applied to the translated KB (a general
   mechanism, not used by the applications); `prune=True` calls `prune_slice`, which drops the
   `Cluster_*` membership records and `isElementOf` links (~23 k triples) that selected
   countries would otherwise bring along, multiplying the translation time.
4. **Solving** — `solve(kb, queries, workdir)` appends the query lines to a copy of the KB
   (`kb_query.fdl`), parses it once with `DLParserFast`, calls `solve_kb()`, then solves each
   query (one MILP each). Returns one record per query: `{"query", "value", "seconds"}`;
   `value` is `None` when the KB is inconsistent for that query (read it as "no positive degree
   entailed": `value(results, i)` maps it to 0.0).
5. **Driver** — `run(name, individuals, axioms, queries, …)` chains the steps, saves
   `results/<name>.json` (slice/translation statistics and per-query values and times), writes
   the LaTeX tables into a `tables/` directory created next to this one, and prints a summary.

`CONFIG.ini` keys: `epsilon` (rounding of query answers), `milpProvider` (`gurobi`),
`owlAnnotationLabel = fuzzyLabel` (the Fuzzy OWL 2 annotation property of the SDF schema),
`maxIndividuals = -1`, `debugPrint = False`.

## The applications

Every script has the same structure: docstring with the question, constants (countries, analyst
axioms in fuzzyDL syntax, queried concepts), a `main()` that selects the individuals, calls
`sdf_fuzzy.run(...)`, and generates the LaTeX tables directly from the results.

| Script | Question | Specifics |
| -------- | ---------- | ----------- |
| `app1_profiling.py` | Socio-economic stress of the 2021 snapshots under four aggregation policies (BNS, ES, SDS, BSES). | Reference slice: 31 snapshots, no analyst axiom. |
| `app2_borders.py` | Stress across land borders (direct neighbours vs land-reachable). | Selects countries and reads the `Distance` individuals from the index (`border_pairs`) to assert one crisp `borders` link per bordering pair; `LandReachableStress` uses the transitive `hasDistance` of the schema; `prune=True`. |
| `app3_groups.py` | Euro-area vs high-income vs middle-income readiness and performance. | Crisp group concepts asserted on the `Economy` nodes (`EuroArea`, `HighIncome`, `MiddleIncome`); countries selected for their object links; `prune=True`. |
| `app4_analyst.py` | Analyst-defined concepts, the hedge `very`, OWA at query time, graded TBox checks. | Mixes `min-instance?`, `min-subs?` and `max-sat?` in one batch. |
| `app5_trajectories.py` | Trajectories 2015–2023 of five southern-European countries. | Selects the complete snapshots of every year; `Recovery = SEP ⊓ ¬ES`. |

## Running

```sh
python3 app1_profiling.py        # first run builds work/index.db (~5 min), then ~7 min
```

No arguments. Approximate times on an Apple-silicon laptop (after the index exists): app1 ~7 min,
app2 ~8 min, app3 ~15 min, app4 ~7 min, app5 ~11 min — the OWL 2 → fuzzyDL translation and the
MILPs dominate. Outputs: `results/<name>.json` and the generated `.tex` tables.

## Notes

- All returned degrees are **lower bounds** (`min-instance?` semantics); a missing feature
  contributes 0 to a weighted sum. The applications therefore use only snapshots carrying all
  six features.
- The 2021 reference slice contains 31 snapshots (248 individuals, 12,048 triples,
  ~1,900 fuzzyDL axioms).
- Requires fuzzy-dl-owl2 >= 1.0.30: earlier releases crash or return trivial bounds when several
  queries are answered on the same knowledge base, mis-handle `q-owa` concepts, and make the KB
  inconsistent when a feature appears in an equivalence with an interval of datatype restrictions.
