# NVIDIA Telemetry Catalog Prototype

This is a lightweight prototype for turning the Excel telemetry workbook into a structured catalog plus chatbot/search interface.

## Why this approach

The workbook is mostly structured operational data: telemetry GUIDs, devices, DCGM/NVML/nvidia-smi mappings, Redfish URIs, platform applicability, log collectors, and configuration values. That is better modeled as SQL + full-text search than as pure vector RAG.

## Run locally

```bash
python ingest.py "Telemetry_Catalog_v4.1 (1).xlsx" --db telemetry_catalog.sqlite
pip install -r requirements.txt
streamlit run app.py
```

## What it builds

- Raw tables for every workbook sheet
- `catalog_docs`: one searchable document per row
- SQLite FTS5 index for retrieval
- `telemetry_metrics` view for the main telemetry catalog
- `log_collectors` view for the log catalog

## Next step for a production chatbot

Add an LLM layer that receives the top retrieved records and answers with source references: sheet name, source row, metric GUID, URI, and collection path.
