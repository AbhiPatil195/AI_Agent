# Multi-Agent Utilities

This repository provides a modular Python CLI with several lightweight agents:

- InsightAgent – analyze .txt/.log/.csv files and produce quick stats, charts, and a 1-page summary.
- DocFormatterAgent – convert text/research results into Markdown, DOCX, or PDF with branding.
- AutoNoteAgent – capture key chat insights into local memory, grouped by day.
- TaskPlannerAgent – turn goals into a prioritized task list with time estimates.
- MediaAnalyzerAgent – inspect images/audio for metadata, basic captions/transcriptions.

## Quick Start

1. Create and activate a virtual environment (Windows):
   ```powershell
   py -3.10 -m venv .venv
   .venv\\Scripts\\Activate.ps1
   ```
2. Install dependencies (optional heavy deps are safe to skip):
   ```powershell
   pip install -r requirements.txt
   ```
3. Run the CLI:
   ```powershell
   python -m src.main --help
   ```

### Web UI (Streamlit)

1. Install requirements (include streamlit):
   ```powershell
   pip install -r requirements.txt
   ```
2. Launch the app:
   ```powershell
   streamlit run src/ui/app.py
   ```
   3. Use the sidebar to switch between agents.

## Commands

- InsightAgent:
  - `python -m src.main insight <path-to-.txt|.log|.csv> [--no-charts]`
  - Writes Markdown summary to `src/output/insight/<stem>/<stem>_summary.md`
  - Saves charts to `src/output/insight/<stem>/*_{levels,timeline,hist}.png` when enabled
  - Patterns via `src/templates/log_patterns.json` (multi-format timestamps, levels, HTTP)

- DocFormatterAgent:
  - `python -m src.main docfmt <input.txt|.md> --format md|docx|pdf [--branding name]`
  - Writes into `src/output/docfmt/`

- AutoNoteAgent:
  - Add note: `python -m src.main autonote "Message here" [--topic tag]`
  - Resummarize today: `python -m src.main autonote --resummarize`
  - Weekly summary: `python -m src.main autonote --weekly`
  - Stores raw in `src/memory/raw/` and summaries in `src/memory/summaries/`

- TaskPlannerAgent:
  - `python -m src.main plan create "Your goal"`
  - `python -m src.main plan list --status todo|done|all`
  - `python -m src.main plan done --id 1`

- MediaAnalyzerAgent:
  - `python -m src.main media <path-to-image-or-audio>`
  - Writes JSON report to `src/output/media/` and extras (histogram/transcript) when available

## Examples

- Sample files live under `examples/`:
  - `examples/logs/example.log`
  - `examples/logs/syslog.log`
  - `examples/data/sample.csv`
  - `examples/text/notes.md`
- See `smoke_tests.md` for quick validation commands.

## Output Layout

- Insight: `src/output/insight/<stem>/...`
- DocFormatter: `src/output/docfmt/...`
- Media: `src/output/media/...`
- Tasks DB: `src/output/tasks.json`
- AutoNote memory: `src/memory/raw/YYYY-MM-DD.jsonl`, `src/memory/summaries/YYYY-MM-DD.md`, `src/memory/summaries/YYYY-Www.md`

## Architecture

- See `docs/architecture.md` for a detailed overview of components, data flows, and sequence diagrams.

## Customizing Log Patterns

Edit `src/templates/log_patterns.json` to add or tune:
- `timestamps`: list of objects with `regex`, `format` (strptime), and optional `infer_year`.
  - Examples included: ISO (`%Y-%m-%d %H:%M:%S`), syslog (`%b %d %H:%M:%S`), Apache (`%d/%b/%Y:%H:%M:%S %z`).
- `levels`: map of level name to regex (case-insensitive).
- `http_error`: regex to detect HTTP error codes.

## Project Layout

- `src/main.py` – CLI entry with subcommands: `insight`, `docfmt`, `autonote`, `plan`, `media`.
- `src/agents/` – individual agent modules.
- `src/templates/` – branding/templates for DocFormatterAgent.
- `src/memory/` – local storage for AutoNoteAgent.
- `src/output/` – generated outputs and reports.

## Notes

- Heavy model integrations (e.g., `faster-whisper`) are optional; the CLI degrades gracefully if not installed.
- Python 3.10+ is recommended for best compatibility with listed versions.
