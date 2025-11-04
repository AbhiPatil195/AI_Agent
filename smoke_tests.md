# Smoke Tests

Use these quick commands to verify each agent.

Prereqs (optional heavy deps can be skipped):

```
py -3.10 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## InsightAgent

```
python -m src.main insight examples\logs\example.log
python -m src.main insight examples\data\sample.csv
python -m src.main insight examples\logs\syslog.log
```

- Outputs: `src/output/example_summary.md`, `src/output/sample_summary.md`

## DocFormatterAgent

```
python -m src.main docfmt examples\text\notes.md --format md
python -m src.main docfmt examples\text\notes.md --format docx --branding company
python -m src.main docfmt examples\text\notes.md --format pdf
```

- Outputs to `src/output/` (falls back to MD if library missing)

## AutoNoteAgent

```
python -m src.main autonote "Discussed experiment setup and metrics" --topic research
python -m src.main autonote "Fixed a bug in tokenizer" --topic bugs
python -m src.main autonote --resummarize
python -m src.main autonote --weekly
```

- Check: `src/memory/raw/YYYY-MM-DD.jsonl`, `src/memory/summaries/YYYY-MM-DD.md`

## TaskPlannerAgent

```
python -m src.main plan create "I want to publish my research paper"
python -m src.main plan list --status all
# mark a task done (replace ID):
python -m src.main plan done --id 1
```

- Check: `src/output/tasks.json`

## MediaAnalyzerAgent

Provide your own image/audio files (no binaries in repo).

```
python -m src.main media C:\path\to\your\image.jpg
python -m src.main media C:\path\to\your\audio.wav
```

- Check `src/output/` for JSON and any extra files.
