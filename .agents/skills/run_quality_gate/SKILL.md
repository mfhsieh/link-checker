---
name: Run Quality Gate
description: 執行專案的完整品質檢查流程（排版、靜態分析、型別檢查、單元測試）。遇到錯誤時，會自動嘗試修復並重試。
---

# 執行專案品質閘門 (Quality Gate)

本技能設計用來自動化執行 `doc/python_coding_style.md` 中規定的開發者檢驗工作流程。

當使用者要求「執行檢查」、「跑 CI」、「測試一下」或是呼叫 `Run Quality Gate` 時，你必須嚴格遵守以下流程：

## 1. 執行檢查腳本

請使用 `run_command` 工具執行以下腳本：
```bash
/home/mfhsieh/projects/python/link-checker/.agents/skills/run_quality_gate/scripts/check.sh
```
（該腳本已經內建了虛擬環境載入與 `set -e` 提早失敗機制）。

## 2. 自動修復迴圈 (Auto-Fix Loop)

如果腳本執行成功，終端機會印出 `All checks passed!`。這時請直接向使用者回報好消息。

**如果腳本執行失敗（退出碼非 0）：**
請發揮 Agent 的能力進行錯誤分析，但**必須在取得使用者同意後才能修改程式碼**：
1. **分析錯誤**：仔細閱讀終端機印出的錯誤訊息（例如 Pylint 的警告、Pytest 的斷言失敗，或是 Ruff 報出的排版/語法錯誤）。
2. **提出修復方案**：向使用者清晰地說明錯誤原因，並展示你預計修改的程式碼（Proposed Fix）。
3. **等待同意**：停止動作，等待使用者回覆「同意」或給予其他指示。
4. **執行與重新驗證**：在取得同意後，使用 `replace_file_content` 工具修改對應檔案，然後**再次呼叫** `check.sh` 腳本進行驗證，直到所有檢查完全通過。
