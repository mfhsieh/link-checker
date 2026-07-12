# Python 程式風格與開發規範 (Coding Style Guide)

為了確保「網站連結檢查系統」專案程式碼的品質、可讀性與維護性，本專案嚴格要求所有的 Python 程式碼提交前均須遵守以下核心風格標準：

## 1. 函式原型宣告與型別提示 (Type Hinting)

所有的函式 (Function)、方法 (Method) 以及類別屬性 (Class Attribute) 都必須明確標示輸入參數與回傳值的型別（Type Hints）。
* 採用 Python 3.10+ 的現代型別標註語法，原則上不使用 `typing` 程式庫的型別定義（例如使用 `list[str]` 而非 `List[str]`，使用 `int | None` 而非 `Optional[int]`）。
* **使用 `typing.cast` 與嚴格型別檢查**：為了保持型別系統的嚴謹性，**強烈建議避免使用 `# type: ignore` 與 `typing.Any`**。若遇到第三方套件或動態指派導致型別推斷錯誤時，應該使用 `typing.cast` 搭配正確的型別宣告（必要時可搭配 `typing.TYPE_CHECKING`）來滿足靜態分析工具。
* 即使函式沒有回傳值，也必須明確標示 `-> None`，不允許省略。
* **模組層級變數與泛型 (Generics)**：模組層級的變數亦須嚴格標示型別（如 `_IS_READY: bool = True`）。強烈鼓勵使用精確的泛型標註（例如 `_ACTIVE_PROCESSES: dict[str, subprocess.Popen] = {}`）以協助 IDE 靜態推斷。

**範例：**
```python
import subprocess

_IS_READY: bool = True
_ACTIVE_PROCESSES: dict[str, subprocess.Popen] = {}


def process_data(items: list[str], max_limit: int | None = None) -> bool: ...
```

## 2. Pydoc / Docstring 註釋規範

專案內所有的模組 (Module)、類別 (Class) 與函式 (Function) 都必須撰寫符合 PEP 257 規範的 Docstring。
* **格式**：推薦採用 Google Style，必須包含明確的功能描述，以及 `Args:`、`Returns:`、`Raises:`、`Yields:` 等區塊（若適用）。
* **模組層級**：每個 `.py` 檔案開頭必須有說明該模組用途的 Docstring。
* **清晰簡潔**：首行必須是簡短的總結說明，空一行後再補上詳細的邏輯描述。

**範例：**
```python
from collections.abc import Generator


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


def stream_pages(urls: list[str]) -> Generator[str, None, None]:
    """
    批次獲取多個 URL 的網頁內容，並以生成器方式逐一回傳。

    Args:
        urls (list[str]): 目標網頁的網址清單。

    Yields:
        str: 各個網頁的 HTML 原始碼。
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

## 4. 程式碼排版風格 (Ruff Formatter)

本專案統一採用 **Ruff** 作為程式碼自動排版工具，以保持全專案排版風格的高度一致性。
* 縮排、單行字數限制（考量現代寬螢幕與完整的型別提示，**放寬至 120 字元**）、引號風格（雙引號 `""`）、空白行等，一切以 Ruff 的格式化結果為準。
* 不接受開發者手動進行與 Ruff 規則相悖的排版。
* **工具配置**：在專案根目錄配置 `ruff.toml`，設定 `line-length = 120` 以覆寫工具預設的 88 字元限制。
* **Pylint 配合調整**：為避免排版工具與靜態檢查工具標準衝突，**必須**同步修改專案根目錄的 `.pylintrc`，於 `[FORMAT]` 區塊下將 `max-line-length` 設為 `120`。
* **匯入排序 (Import Sorting)**：模組匯入應依循 PEP 8 規範，按「標準函式庫 (Standard Library)」、「第三方套件 (Third-party)」、「本地模組 (Local Application)」分段空行並按字母排序。強烈建議搭配 Ruff 的 `isort` 檢查自動處理。

---

## 5. 開發者檢驗工作流程 (Workflow)

開發者在完成功能實作後，請依序執行以下指令進行自我檢查：

```bash
# 1. 自動排版程式碼、匯入排序與清理無效 noqa
ruff check --extend-select I,RUF100 --fix .
ruff format .

# 2. 執行 Pylint 進行靜態分析 (包含主程式與測試腳本)
pylint --load-plugins=pylint.extensions.docparams --enable=useless-suppression backend/ crawler/ cli.py scripts/ test/

# 3. 執行 Mypy 靜態型別檢查
mypy --explicit-package-bases backend/ crawler/ cli.py scripts/ test/

# 4. 執行 Pytest 整合測試
pytest test/ -v
```

## 附錄：特定框架開發補充規範 (Framework-Specific Guidelines)

### FastAPI 非同步與同步路由規範 (Async vs Sync)

在使用 FastAPI 開發 Web API 時，必須嚴格區分 `def` 與 `async def` 的使用時機，防範阻塞主事件迴圈 (Event Loop Blocking)：

* **必須使用 `def` (同步)**：當路由內部包含任何 **同步阻塞 (Synchronous Blocking)** 的操作時，包含 SQLAlchemy 資料庫查詢 (`Session.query`)、CPU 密集運算 (如 `bcrypt` 雜湊)、或是同步的網路請求 (如 `smtplib`、`requests`)。FastAPI 偵測到 `def` 時會自動將此類請求拋至底層 `ThreadPool` 執行，確保系統高併發安全。
* **可以使用 `async def` (非同步)**：當且僅當路由內部的所有耗時操作皆為非同步（例如使用 `httpx.AsyncClient`、`asyncio.sleep` 或非同步資料庫驅動），才可宣告為 `async def`。
