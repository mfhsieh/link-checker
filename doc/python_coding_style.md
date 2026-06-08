# Python 程式風格與開發規範 (Coding Style Guide)

為了確保「外部連結檢查系統」專案程式碼的品質、可讀性與維護性，本專案嚴格要求所有的 Python 程式碼提交前均須遵守以下四項核心風格標準：

## 1. 函式原型宣告與型別提示 (Type Hinting)

所有的函式 (Function)、方法 (Method) 以及類別屬性 (Class Attribute) 都必須明確標示輸入參數與回傳值的型別（Type Hints）。
* 採用 Python 3.10+ 的現代型別標註語法，不使用 `typing` 程式庫的型別定義（例如使用 `list[str]` 而非 `List[str]`，使用 `int | None` 而非 `Optional[int]`）。
* 即使函式沒有回傳值，也必須明確標示 `-> None`，不允許省略。

**範例：**
```python
def process_data(items: list[str], max_limit: int | None = None) -> bool:
    ...
```

## 2. Pydoc / Docstring 註釋規範

專案內所有的模組 (Module)、類別 (Class) 與函式 (Function) 都必須撰寫符合 PEP 257 規範的 Docstring。
* **格式**：推薦採用 Google Style，必須包含明確的功能描述，以及 `Args:`、`Returns:`、`Raises:`、`Yields:` 等區塊（若適用）。
* **模組層級**：每個 `.py` 檔案開頭必須有說明該模組用途的 Docstring。
* **清晰簡潔**：首行必須是簡短的總結說明，空一行後再補上詳細的邏輯描述。

**範例：**
```python
def fetch_url(url: str, timeout: int = 30) -> str:
    """
    獲取指定 URL 的網頁內容。

    若請求超時或發生網路異常，將拋出相對應的例外。

    Args:
        url (str): 目標網頁的完整網址。
        timeout (int): 請求超時時間（秒），預設為 30。

    Returns:
        str: 網頁的 HTML 原始碼。

    Raises:
        ValueError: 網址格式不正確時拋出。
        ConnectionError: 網路連線失敗時拋出。
    """
    ...
```

## 3. Pylint 滿分標準 (10/10)

所有提交的 Python 程式碼都必須通過 `pylint` 的嚴格檢查，並且達到滿分 (**10.0/10.0**) 的標準。
* 開發過程中請隨時在本地端執行 `pylint` 進行檢查。
* 若遇到特定情境下不可避免的警告（例如捕捉範圍較廣的 Exception、為了相容介面而未使用的參數等），允許使用單行註解區域性停用特定規則，但應合理評估並盡量減少使用。
  ```python
  try:
      ...
  except Exception as e:  # pylint: disable=broad-exception-caught
      logger.error("發生非預期錯誤: %s", e)
  ```

## 4. 程式碼排版風格 (Black Formatter)

本專案統一採用 **Black** 作為程式碼自動排版工具，以消弭開發者之間對於排版風格的爭議，保持全專案的高度一致性。
* 縮排、單行字數限制（預設 88 字元）、引號風格（雙引號 `""`）、空白行等，一切以 Black 的格式化結果為準。
* 不接受開發者手動進行與 Black 規則相悖的排版。

---

## 開發者檢驗工作流程 (Workflow)

開發者在完成功能實作後，請依序執行以下指令進行自我檢查：

```bash
# 1. 自動排版程式碼
black .

# 2. 執行 Pylint 進行靜態分析
pylint backend/ crawler/ cli.py
```
