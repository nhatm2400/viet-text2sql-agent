# External datasets — licences and version pins

**No dataset file is ever committed to this repository.** This directory contains download
scripts only. Everything they fetch lands in `data/external/`, which is git-ignored.

The scripts in this directory were **not executed** while scaffolding the repo.

## Why the pins matter

A 2026 audit ("Pervasive Annotation Errors Break Text-to-SQL Benchmarks and Leaderboards",
arXiv:2601.08778 / CIDR 2026) measured annotation error rates of **52.8% on BIRD Mini-Dev** and
**62.8% on Spider 2.0-Snow**, and found agent rankings shifting by up to ±9 positions once the
labels were corrected. Two consequences are treated here as methodology, not optional extras:

1. every external subset is **version-locked** to a specific commit or release tag;
2. a **sample of every subset is manually audited** before any number derived from it is reported.

Numbers from these sets are always reported separately from `core_vi`, never merged into a single
headline figure — the settings differ.

## ViText2SQL

- Source: <https://github.com/VinAIResearch/ViText2SQL>
- Paper: Nguyen A.T., Dao M.H., Nguyen D.Q. (2020), *A Pilot Study of Text-to-SQL Semantic Parsing
  for Vietnamese*, Findings of EMNLP 2020.
- Size: 9,691 questions / 5,263 SQL queries / 166 databases (Spider, manually translated).
- **Licence: research and educational purposes only. Redistribution in any form is not
  permitted.** The download script prints this notice before fetching anything, and the data
  directory is git-ignored. Do not commit it, do not mirror it, do not attach it to a release.
- Setting note: ViText2SQL translated **both** the questions **and** the schemas into Vietnamese.
  This project's setting is Vietnamese questions over an **English** schema, so results on this
  subset are a related-but-different measurement and are labelled as such.
- Pinned to: `VERSION_TAG` in `download_vitext2sql.py`.

## Spider 1.0 (dev subset)

- Source: <https://yale-lily.github.io/spider>
- Paper: Yu T. et al. (2018), EMNLP 2018.
- Licence: CC BY-SA 4.0.
- Role here: an **English sanity check only**. Spider 1.0 is effectively saturated for modern
  LLMs (~86–91% EX for GPT-4-class methods), so it is reported as a floor check, never as
  evidence of quality.
- Pinned to: `VERSION_TAG` in `download_spider_subset.py`.

## Out of scope

- **Spider 2.0** (632 enterprise workflow tasks, schemas often exceeding 1,000 columns) — out of
  scope for this MVP (proposal §3).
- **BIRD** — one BIRD database is planned as a wide-schema retrieval stress test, kept in its
  native SQLite. The harness accepts any SQLAlchemy URI read-only, so there is no Postgres port.
