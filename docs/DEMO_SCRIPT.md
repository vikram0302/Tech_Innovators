# Demo script — Claims Audit Workbench

## 1. Regulations (required first)

1. Open **Regulations** tab.
2. Upload `sample_data/Claims_Handling_Standards.pdf` (and any other regulation PDFs).
3. Confirm **Active regulation set** appears; click a file to preview.

## 2. Audit workspace

1. Open **Audit** tab.
2. Upload three claims files:
   - `sample_data/adjuster_notes.json`
   - `sample_data/communication_logs.json`
   - `sample_data/sample.xlsx`
3. Send a message to start the audit (with Planning Mode on, Approve & Start first).
4. Watch **Task Panel** progress and **Live Preview** findings.
5. Download **combined PDF report**.

## 3. Chat (optional)

- With Planning Mode on, ask: “Audit all claims against the regulations” — approve then execute via UI.
- With Planning Mode off, chat triggers immediate batch run when dataset is loaded.

## API smoke test

```bash
curl http://localhost:8001/api/regulations/active
curl http://localhost:8001/api/dataset/active
```
