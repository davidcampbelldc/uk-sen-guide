---
title: "Attributions and licensing for UK SEND guidance sources, models and libraries"
date: 2026-04-20
status: PARTIAL
question: "What are the copyright licences, attribution requirements and reuse terms for the source content, models and libraries used in this repository?"
topic: docs
backfilled: 2026-10-05
---

# Attributions

This repository ingests publicly-published UK Special Educational Needs
guidance for research and evaluation purposes. All retrieved content
remains the property of its original publisher; this project claims no
authorship of the source material, only the pipeline, indices, and
evaluation code.

## Source content

### Crown copyright (Open Government Licence v3.0)

All content from `*.gov.uk` domains and
`assets.publishing.service.gov.uk` is Crown copyright and is licensed
under the
**[Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/)**
(OGL-3.0). This covers:

- The **SEND Code of Practice: 0 to 25 years** (2015, Department for
  Education and Department of Health).
- Gov.uk SEND topic pages, guidance, and linked PDFs discovered via
  the gov.uk public search API.
- DfE Special Educational Needs statistics (XLSX attachments on
  gov.uk/government/statistics publications).

Attribution statement per OGL-3.0:
> Contains public sector information licensed under the Open Government
> Licence v3.0.

### Local Authority content

Local Authority Local Offer content (Birmingham, Bradford, Brighton &
Hove, Bath & North East Somerset, Croydon, Hackney, Islington, Leeds,
Leicester, Lewisham, Manchester, Newcastle, Oxfordshire, Sheffield,
Southwark, Stockport) is published by the respective Local Authority.
Most is released under OGL-3.0; a subset carries council-specific terms
that permit reproduction with attribution. Each chunk's `metadata.url`
points back to the originating page.

### Charity guidance

Articles from **IPSEA** (*Independent Provider of Special Education
Advice*, `ipsea.org.uk`) and **Contact** (`contact.org.uk`) are
reproduced under each charity's standard content-reuse terms (fair use
for research and advocacy; attribution required and provided). Each
chunk's metadata identifies the charity and the originating URL.

## Models

| Model | Licence | Role |
|---|---|---|
| `BAAI/bge-large-en-v1.5` | MIT | Dense embedding (encoder) |
| `BAAI/bge-reranker-base` | MIT | Cross-encoder reranker |

## Libraries

Dependencies are listed in `pyproject.toml`; all are released under
permissive open-source licences (MIT / Apache-2.0 / BSD). Notable:

| Library | Licence | Role |
|---|---|---|
| `qdrant-client` | Apache-2.0 | Vector database client |
| `sentence-transformers` | Apache-2.0 | Embedding + cross-encoder runtime |
| `bm25s` | MIT | BM25 index |
| `fastapi` | MIT | HTTP API |
| `prometheus-fastapi-instrumentator` | ISC | Metrics instrumentation |
| `structlog` | Apache-2.0 / MIT | JSON logging |
| `pypdf` / `pdfplumber` | BSD / MIT | PDF parsing |
| `openpyxl` | MIT | XLSX parsing |
| `beautifulsoup4` / `lxml` | MIT / BSD | HTML parsing |

## Scope disclaimer

Nothing ingested or retrieved here constitutes legal advice. The
retrieval layer surfaces source material produced by government and
charity bodies; any deployment of this system for parent-facing use
must add an explicit "not legal advice" disclaimer and route
escalations to appropriate advice services (IPSEA / Contact /
SEND Tribunal self-help, etc.).
