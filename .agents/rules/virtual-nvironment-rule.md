---
trigger: always_on
---

# Python 執行與環境規範 (Virtual Environment Rule)

- 本專案已在本地建立虛擬環境 `.venv`。
- 當你需要使用終端機執行任何 `python`, `pytest`, `pip` 或專案內的腳本（例如 `cli.py`）時，**必須嚴格遵守以下兩種執行方式之一**：
  1. 使用虛擬環境直譯器的明確路徑，例如：`.venv/bin/python scripts/gen_api_doc.py`。
  2. 在同一行指令中先啟動虛擬環境，例如：`source .venv/bin/activate && python ...`。
- **嚴格禁止**：在未啟動虛擬環境或未指定虛擬環境路徑的情況下，直接呼叫全域的 `python` 指令。
- **嚴格禁止**：任意安裝套件，一定要經過我的評估同意。