# HARNESS PIPELINE

**An extensible research and portfolio-management pipeline for Alpha Harness and WorldQuant BRAIN.**

HARNESS PIPELINE is a Python-based research automation project designed to bridge Alpha Harness candidate discovery with WorldQuant BRAIN alpha retrieval, analysis, organization, diversification, correlation review, and controlled submission.

The project aims to transform manually discovered alpha candidates into a structured, traceable, and repeatable research workflow.

> **Project status:** Initial development. The pipeline is being developed incrementally. Components documented as planned are not necessarily implemented yet.

---

## Table of Contents

- [FIELD CACHING](fieldcaching)
- [Overview](#overview)
- [Objectives](#objectives)
- [Research Workflow](#research-workflow)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Technology Stack](#technology-stack)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration and Secrets](#configuration-and-secrets)
- [Pipeline Components](#pipeline-components)
- [Research Data Management](#research-data-management)
- [Correlation and Diversification](#correlation-and-diversification)
- [Submission Controls](#submission-controls)
- [Reliability and Recovery](#reliability-and-recovery)
- [Development Guidelines](#development-guidelines)
- [Testing and Validation](#testing-and-validation)
- [Troubleshooting](#troubleshooting)
- [Roadmap](#roadmap)
- [Disclaimer](#disclaimer)

---

## Overview

Alpha research often involves manually discovering candidates, copying identifiers, retrieving alpha information, comparing metrics, identifying redundant ideas, and checking correlation against an existing portfolio.

These activities can become difficult to manage when candidates are collected across multiple research sessions.

HARNESS PIPELINE is intended to provide a unified workflow for:

- Capturing alpha candidates discovered through Alpha Harness.
- Retrieving corresponding alpha records from WorldQuant BRAIN.
- Organizing candidates by underlying fields and research families.
- Comparing candidate performance metrics.
- Selecting diversified candidate pools.
- Maintaining a reference portfolio for correlation review.
- Tracking candidates through research and submission stages.
- Preserving research history across sessions.

The system is designed around **controlled automation**: automate repetitive research operations while keeping important approval and submission decisions explicit.

---

## Objectives

### Primary objectives

1. Reduce repetitive manual alpha-management work.
2. Preserve alpha identifiers and associated research metadata.
3. Avoid selecting large numbers of structurally similar candidates.
4. Improve candidate selection through field-family diversification.
5. Maintain reproducible research runs.
6. Prevent accidental duplicate submissions.
7. Support recovery after interrupted workflows.
8. Separate candidate discovery, evaluation, correlation review, and submission.

### Non-goals

The pipeline is not intended to:

- Guarantee profitable or qualifying alphas.
- Automatically approve every generated candidate.
- Replace WorldQuant BRAIN's own simulation and validation.
- Treat high Sharpe as sufficient evidence of alpha quality.
- Assume that different expressions are statistically independent.
- Bypass BRAIN's submission requirements.

---

## Research Workflow

The intended end-to-end workflow:

```text
Alpha Harness
     |
     | User copies Submitable results
     v
Manual Alpha ID Input
     |
     v
alpha_ids.txt
     |
     v
WorldQuant BRAIN Alpha Retrieval
     |
     v
Raw Alpha Records
     |
     v
Field / Family Organization
     |
     v
Candidate Scoring and Diversification
     |
     v
Top Candidate Pool
     |
     v
Manual Correlation Review
     |
     v
Correlation Breaker (when needed)
     |
     v
Re-fetch and Re-evaluate
     |
     v
Approved Submission Queue
     |
     v
Controlled BRAIN Submission
     |
     v
Submission Tracking and Research History
```

The Alpha Harness discovery stage remains user-controlled. The pipeline begins when candidate results are provided to it.

---

## Architecture

The project follows a modular architecture. Each component should have one clear responsibility.

## BRAIN Field Metadata and Cache

HARNESS PIPELINE includes a field fetcher at `src/harness_pipeline/fields/fields.py`.
It requests BRAIN field metadata and stores it locally so later runs can reuse it.

### Cache location and naming

The cache is stored under `data/field_cache/` with region, universe, and delay
in the filename. For the default USA TOP3000, delay 1 settings, the file is:

```text
data/field_cache/fields_USA_TOP3000_d1.json
```

The fetcher creates the cache directory when needed. If the matching cache file
already exists, `fetch_fields()` loads it and skips the API request by default.
The current project already contains this cache file.

### Create or load the cache

From the project root in Git Bash, run:

```bash
PYTHONPATH=src python -m harness_pipeline.fields.fields
```

The module authenticates through the existing `auth.py`. On the first run, it
fetches the fields from BRAIN and writes the cache. Later runs load the cache.

### Refresh the cache

The module's command-line entry point does not force a refresh. To refresh a
cache, call `fetch_fields()` with `force_refresh=True`:

```bash
PYTHONPATH=src python - <<'PY'
from auth import WQSession
from harness_pipeline.fields.fields import fetch_fields

session = WQSession()
session.login()
fetch_fields(
    session.session,
    region="USA",
    universe="TOP3000",
    delay=1,
    force_refresh=True,
)
PY
```

This replaces the matching local cache file with the fields returned by BRAIN.
Change `region`, `universe`, or `delay` to fetch a different configuration.

### Catalog usage

`FieldCatalog` in `src/harness_pipeline/fields/catalog.py` reads the cached
metadata through `field_rules.py` and provides field lookup, type checks, and
expression validation. The organizer uses `FieldCatalog` to match expression identifiers against
the loaded cache.

### 1. Manual Alpha ID input

Alpha IDs are collected manually from Alpha Harness and stored one per line
in `data/alpha_ids.txt`. Include only IDs marked **Submitable** and preserve
their exact capitalization. This project does not extract IDs from copied
Alpha Harness text.

### 2. Alpha retrieval

Retrieves alpha details from WorldQuant BRAIN.

Responsibilities:

- Authenticate using local credentials.
- Fetch alpha records.
- Handle unavailable or invalid IDs.
- Record retrieval failures.
- Cache successful results.
- Avoid unnecessary repeated API requests.

### 3. Alpha organization

Groups candidates according to their underlying fields, expression structure, and research family.

Responsibilities:

- Identify referenced fields.
- Associate candidates with field groups.
- Preserve unmatched candidates.
- Produce machine-readable and human-readable reports.

### 4. Candidate selection

Evaluates candidates and produces a diversified shortlist.

Responsibilities:

- Compare performance metrics.
- Avoid excessive concentration in one field family.
- Preserve selection explanations.
- Generate a configurable shortlist, initially targeting 25 candidates.

### 5. Correlation review

Supports the user's manual correlation workflow.

Responsibilities:

- Maintain reference portfolio information.
- Track which candidates require correlation review.
- Record review outcomes.
- Distinguish original candidates from modified or breaker-processed candidates.

Correlation Breaker operations remain manual unless a future implementation explicitly supports them.

### 6. Submission management

`submit_queue.py` processes approved alpha IDs sequentially and asks for
confirmation before each submission. It depends on `submit.py`, which
provides the alpha retrieval, review summary, and submission functions used
by the queue.

Run the queue with IDs as arguments:

```bash
python submit_queue.py ID1 ID2 ID3
```

Or use a text file containing one ID per line:

```bash
python submit_queue.py --file data/submission_queue.txt
```

Type `yes` to submit the displayed alpha, `skip` to continue without
submitting it, or `stop` to end the queue. The queue reports submitted,
skipped, and failed IDs. It does not maintain a persistent submission
history.

## Project Structure

Current project files include:

```text
HARNESS-PIPELINE/
├── auth.py
├── fetch_alphas.py
├── organize_alphas.py
├── select_alphas.py
├── run_pipeline.py
├── submit_queue.py
├── submit.py
├── data/
│   ├── alpha_ids.txt
│   └── field_cache/
├── src/harness_pipeline/
│   ├── fields/       # Field fetcher, catalog, and field rules
│   └── state/        # Persistent run state manager
└── tests/
    └── test_state.py
```

The submission queue calls functions from `submit.py`; both files are
needed for queue-based submission. The field catalog and state manager
 are available as package components, but the standalone workflow scripts
do not currently call them.

## Technology Stack

| Technology | Purpose |
| --- | --- |
| Python | Core pipeline implementation |
| Requests | HTTP communication with BRAIN |
| WorldQuant BRAIN API | Alpha retrieval and submission |
| JSON | Structured research data and configuration |
| CSV | Human-readable candidate reports |
| Git | Version control |
| Git Bash | Windows development workflow |

---

## Prerequisites

- Windows development environment.
- Python 3.10 or newer.
- Git.
- Git Bash or another compatible terminal.
- WorldQuant BRAIN account with appropriate access.
- Valid BRAIN credentials.
- Internet access for API operations.

---

## Installation

### 1. Clone the repository

```bash
git clone <repository-url>
cd HARNESS-PIPELINE
```

Replace `<repository-url>` with the actual repository URL.

### 2. Create a virtual environment

```bash
python -m venv .venv
```

### 3. Activate the environment

For Git Bash on Windows:

```bash
source .venv/Scripts/activate
```

### 4. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 5. Verify the environment

```bash
python --version
pip --version
```

### 6. Verify authentication

```bash
python auth.py
```

Authentication should be confirmed before running API-dependent pipeline components.

Avoid sharing terminal output that contains credentials, account information, session tokens, or other sensitive details.

---

## Configuration and Secrets

### Credentials

The project uses local BRAIN credentials for authentication.

The local credential file is:

```text
credentials.json
```

This file must remain local and must never be committed to Git.

### Required Git exclusions

The `.gitignore` file should include:

```gitignore
# Secrets
credentials.json
.env
*.key
*.pem

# Python
.venv/
__pycache__/
*.py[cod]

# Runtime data
logs/
data/

# Temporary files
*.tmp
*.bak
```

Review the exclusions before committing.

Verify that credentials are ignored:

```bash
git check-ignore -v credentials.json
```

If Git reports that credentials are not ignored, stop before staging or committing.

### Security principles

- Never hardcode credentials in Python source files.
- Never print passwords, API keys, or authentication tokens.
- Never commit local credential files.
- Avoid logging authentication headers.
- Restrict access to local research artifacts where appropriate.
- Keep authentication and research logic separate.
- Treat API responses and external data as untrusted input.

A private repository is not a substitute for proper secret management.

---

## Pipeline Components

| Component | Current implementation |
| --- | --- |
| Manual ID input | `data/alpha_ids.txt`; IDs are entered manually |
| Alpha fetcher | `fetch_alphas.py`; writes fetched records under `data/` |
| Organizer | `organize_alphas.py`; groups records using the local field cache |
| Selector | `select_alphas.py`; writes a diversified shortlist of up to 25 |
| Pipeline runner | `run_pipeline.py`; coordinates stages and records run state |
| Field cache fetcher | `src/harness_pipeline/fields/fields.py`; fetches BRAIN metadata and caches it locally |
| Field catalog | `src/harness_pipeline/fields/catalog.py`; reusable field lookup and validation |
| Run manager | `src/harness_pipeline/state/manager.py`; reusable run tracking |
| Submission queue | `submit_queue.py`; uses `submit.py` and asks before each submission |

`run_pipeline.py` uses the field fetcher and `FieldCatalog`, then records
stage checkpoints, fetch failures, and selected candidates with `StateManager`.
The submission queue remains a separate, manually confirmed step.

### Manual Alpha ID input

Put one Alpha ID per line in `data/alpha_ids.txt`. Include only alphas marked
**Submitable** in Alpha Harness. Preserve exact capitalization; do not include
headings, fields, metrics, or other metadata.

### Research stages

From the project root, run the coordinated workflow:

```bash
python run_pipeline.py
```

The runner loads or fetches the USA TOP3000 delay 1 field cache, then runs
fetch, organization, and selection in order. It stores checkpoints, failures,
and selected candidates in `data/pipeline_state.json`. Outputs include
`data/top25_alphas.json` and `data/top25_alphas.csv`. If a stage fails, the run
is marked failed; fix the reported issue and run the command again.

Individual stage scripts can still be run directly when needed.

### Submission

After choosing IDs for submission, run:

```bash
python submit_queue.py ID1 ID2 ID3
```

The queue imports `get_alpha`, `show_summary`, and `submit_alpha` from
`submit.py`. It displays each alpha and requires a separate `yes`
confirmation before submitting it.

## Research Data Management

Research artifacts should be stored in structured formats.

Suggested runtime files:

```text
data/
├── alpha_ids.txt
├── fetched_alphas.json
├── fetched_alphas.csv
├── alphas_by_field.json
├── alphas_by_field.csv
├── top25_alphas.json
├── top25_alphas.csv
├── submission_queue.json
└── run_history.json
```

These files represent the intended data layout and may not all exist yet.

### Data preservation

The pipeline should:

- Preserve raw fetched records.
- Avoid overwriting original candidate data.
- Keep run-specific snapshots.
- Record failed requests.
- Track changes to selection decisions.
- Maintain clear relationships between original and processed candidates.

Runtime datasets may contain account-specific or proprietary research information and should not automatically be published.

---

## Correlation and Diversification

Alpha diversification is a central objective of the project.

Different alpha expressions can still represent similar underlying signals. Expression differences alone do not establish statistical independence.

The pipeline should consider:

- Underlying fields.
- Field families.
- Expression structure.
- Alpha performance.
- Existing portfolio exposure.
- Correlation review results.

### Manual correlation workflow

1. Generate the candidate shortlist.
2. Review candidates against the reference portfolio.
3. Identify candidates that require further correlation analysis.
4. Use Alpha Harness Correlation Breaker manually when appropriate.
5. Retrieve the resulting alpha records.
6. Re-evaluate candidates.
7. Record the review outcome.
8. Approve candidates for submission only after review.

A candidate should not automatically become submission-approved simply because it passes a selection score.

---

## Submission Controls

Submission is a controlled operation and should remain isolated from candidate generation.

Before submission, candidates should have:

- A valid alpha ID or approved expression.
- Successful retrieval or simulation history where applicable.
- Recorded performance metrics.
- Completed required review.
- Explicit submission approval.
- Duplicate-submission checks.

The pipeline should maintain a record of:

- Alpha ID.
- Submission timestamp.
- Submission status.
- API response.
- Retry attempts.
- Error details.
- Final outcome.

### Important

Do not submit candidates automatically merely because they appear in the top-ranked shortlist.

Selection, correlation review, and submission are separate decisions.

---

## Reliability and Recovery

The pipeline should be designed to recover from interruptions without losing research progress.

Recommended practices:

- Save results after each completed stage.
- Track the current pipeline stage.
- Use unique run IDs.
- Maintain a persistent submission history.
- Retry temporary network failures with bounded retries.
- Avoid repeating completed API requests unnecessarily.
- Preserve failed records for later inspection.
- Use atomic file writes where practical.
- Keep raw inputs available for reprocessing.

The system should prefer recoverable, auditable operations over long-running workflows that only save results at the end.

---

## Development Guidelines

### Code organization

- Keep modules focused on one responsibility.
- Avoid tightly coupling authentication, fetching, selection, and submission.
- Use explicit function interfaces.
- Prefer configuration over hardcoded settings.
- Use descriptive names.
- Document important assumptions.
- Keep API-specific behavior isolated.

### Error handling

- Handle expected API errors explicitly.
- Distinguish authentication failures from network failures.
- Preserve useful diagnostic information.
- Do not silently ignore unexpected errors.
- Avoid logging secrets.

### Research reproducibility

Where practical, record:

- Run timestamp.
- Input IDs.
- Selection parameters.
- Data universe and settings.
- Selection results.
- Failed operations.
- Software version or Git commit.

This makes it possible to understand why a candidate was selected in a previous run.

---

## Testing and Validation

Before enabling a new component in the full pipeline:

1. Test it against a small input.
2. Validate its output format.
3. Confirm that duplicate IDs are handled correctly.
4. Confirm that errors are recorded.
5. Confirm that existing research data is not overwritten.
6. Verify that credentials are not exposed.
7. Run the component against a larger dataset only after basic tests pass.

Submission functionality should be tested separately from research and selection functionality.

---

## Troubleshooting

### Authentication failure

- Verify that credentials are valid.
- Check that the credential file exists locally.
- Confirm that the virtual environment is active.
- Check network connectivity.
- Do not share credential contents when requesting help.

### Alpha retrieval failure

- Verify that the alpha ID is correct.
- Preserve capitalization.
- Check whether the alpha is accessible through the account.
- Review the recorded API response.
- Keep failed IDs for later retry.

### Missing Python dependency

```bash
pip install -r requirements.txt
```

### Virtual environment not active

```bash
source .venv/Scripts/activate
```

### Credentials appearing in Git status

```bash
git check-ignore -v credentials.json
```

Do not commit until the credential file is correctly excluded.

---

## Roadmap

- [x] Establish a dedicated project separate from the existing ALPHA project.
- [x] Create a Python virtual environment and install initial dependencies.
- [x] Establish local credential exclusions and BRAIN authentication.
- [x] Establish manual Alpha ID input through `data/alpha_ids.txt`.
- [x] Add BRAIN alpha retrieval, caching, and failure recording.
- [x] Add field-based organization.
- [x] Add diversified top-25 selection.
- [x] Add the sequential submission queue and its `submit.py` helper.
- [x] Add the field metadata fetcher, local cache, field catalog, and persistent run state manager.
- [x] Add tests for the state manager.
- [ ] Integrate correlation review tracking.
- [x] Add `run_pipeline.py` to connect the research stages to `FieldCatalog` and `StateManager`.
- [ ] Add persistent submission history and reporting.

## Disclaimer

HARNESS PIPELINE is a personal quantitative research and automation project.

It is intended to support research organization and workflow automation. It does not guarantee alpha qualification, statistical independence, future performance, or successful submission.

All candidates remain subject to WorldQuant BRAIN's evaluation, platform requirements, and applicable rules.

---

## Author

**HARNESS PIPELINE**

A modular quantitative research automation project focused on improving the organization, evaluation, diversification, and management of WorldQuant BRAIN alpha candidates.
