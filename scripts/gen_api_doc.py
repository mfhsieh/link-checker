"""
自動產生 API 規格與路由清單。

從 FastAPI 的 OpenAPI Schema 萃取資料，分別產出 `doc/api.json`、`doc/api_spec.md` 與 `doc/api_routes.md`。
"""

import json
import os
import re
import sys

# 將專案根目錄加入 PYTHONPATH 以便載入 backend 模組
PROJECT_ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from backend.main import app  # pylint: disable=wrong-import-position,import-error # noqa: E402


def _format_description_markdown(desc: str) -> str:
    """將 Python docstring 中的 Args/Returns 等區段轉換為更適合 Markdown 呈現的格式。"""
    lines = desc.split("\n")
    out_lines = []
    in_section = False

    for line in lines:
        stripped = line.strip()
        if stripped in ("Args:", "Returns:", "Raises:", "Yields:"):
            out_lines.append("")
            out_lines.append(f"**{stripped[:-1]}**:")
            in_section = True
            continue

        if in_section:
            if not line.strip():
                in_section = False
                out_lines.append(line)
            elif line.startswith(" ") or line.startswith("\t"):
                match = re.match(r"^\s+([a-zA-Z0-9_]+)\s*\(([^)]+)\):\s*(.*)", line)
                if match:
                    name, type_, doc = match.groups()
                    out_lines.append(f"- `{name}` ({type_}): {doc}")
                else:
                    match_returns = re.match(r"^\s+([^:]+):\s*(.*)", line)
                    if match_returns:
                        type_or_name, doc = match_returns.groups()
                        out_lines.append(f"- `{type_or_name}`: {doc}")
                    else:
                        out_lines.append(f"- {line.strip()}")
            else:
                in_section = False
                out_lines.append(line)
        else:
            out_lines.append(line)

    return "\n".join(out_lines)


def _process_paths(schema: dict, lines: list[str]) -> None:
    """
    處理 OpenAPI Schema 中的所有 API 路徑，並將其轉換為 Markdown 格式附加至行列表中。

    逐一尋訪所有的端點與 HTTP 方法，提取摘要、說明與標籤，並呼叫其他輔助函式處理請求與回應細節。

    Args:
        schema (dict): 從 FastAPI 獲取的 OpenAPI Schema 字典。
        lines (list[str]): 用於收集 Markdown 文字行的列表，函式會將結果附加於此。
    """
    paths = schema.get("paths", {})
    for path, path_item in paths.items():
        for method, operation in path_item.items():
            lines.append(f"## {method.upper()} {path}")
            if "summary" in operation:
                lines.append(f"**摘要**: {operation['summary']}")
            if "description" in operation:
                lines.append("")
                formatted_desc = _format_description_markdown(operation["description"])
                lines.append(f"**說明**: {formatted_desc}")
            else:
                lines.append("")

            tags = operation.get("tags", [])
            if tags:
                lines.append(f"\n**標籤**: {', '.join(tags)}")

            _process_request_body(operation, lines)
            _process_responses(operation, lines)
            lines.append("---\n")


def _process_request_body(operation: dict, lines: list[str]) -> None:
    """
    處理單一 API 路由的 Request Body 資訊，並將對應的 Markdown 格式附加至行列表中。

    解析請求的 Content-Type 與對應的 Schema 參考名稱，若無 Request Body 則直接返回。

    Args:
        operation (dict): OpenAPI Schema 中單一操作（例如 POST /login）的字典結構。
        lines (list[str]): 用於收集 Markdown 文字行的列表，函式會將結果附加於此。
    """
    request_body = operation.get("requestBody")
    if not request_body:
        return
    lines.append("\n### 請求內容 (Request Body)")
    content = request_body.get("content", {})
    for content_type, media_type in content.items():
        lines.append(f"- **Content-Type**: `{content_type}`")
        schema_ref = media_type.get("schema", {}).get("$ref", "")
        if schema_ref:
            schema_name = schema_ref.split("/")[-1]
            lines.append(f"- **Schema**: `{schema_name}` (參考下方 Schema 定義)")


def _process_responses(operation: dict, lines: list[str]) -> None:
    """
    處理單一 API 路由的回應 (Responses) 資訊，並將其 Markdown 格式附加至行列表中。

    解析各個 HTTP 狀態碼與對應的敘述文字，若無 Responses 定義則直接返回。

    Args:
        operation (dict): OpenAPI Schema 中單一操作的字典結構。
        lines (list[str]): 用於收集 Markdown 文字行的列表，函式會將結果附加於此。
    """
    responses = operation.get("responses", {})
    if not responses:
        return
    lines.append("\n### 回應 (Responses)")
    for status_code, res in responses.items():
        res_desc = res.get("description", "")
        lines.append(f"- **{status_code}**: {res_desc}")


def _process_schemas(schema: dict, lines: list[str]) -> None:
    """
    處理 OpenAPI Schema 中的所有 Components Schemas，並將其轉換為 Markdown 表格附加至行列表中。

    提取所有定義的資料模型，包含屬性名稱、資料型態、是否必填以及屬性說明，輸出為 Markdown 表格形式。

    Args:
        schema (dict): 從 FastAPI 獲取的 OpenAPI Schema 字典。
        lines (list[str]): 用於收集 Markdown 文字行的列表，函式會將結果附加於此。
    """
    schemas = schema.get("components", {}).get("schemas", {})
    if not schemas:
        return
    for schema_name, schema_obj in schemas.items():
        lines.append(f"## {schema_name}")
        if "description" in schema_obj:
            lines.append(schema_obj["description"])
            lines.append("")

        lines.append("| 屬性名稱 | 類型 | 必填 | 說明 |")
        lines.append("|---|---|---|---|")

        properties = schema_obj.get("properties", {})
        required_fields = schema_obj.get("required", [])

        for prop_name, prop_details in properties.items():
            prop_type = prop_details.get("type", "any")
            if "$ref" in prop_details:
                prop_type = prop_details["$ref"].split("/")[-1]
            elif "anyOf" in prop_details:
                prop_type = "any"
                for option in prop_details["anyOf"]:
                    if "$ref" in option:
                        prop_type = option["$ref"].split("/")[-1]
                        break
                    if "type" in option and option["type"] != "null":
                        prop_type = option["type"]
                        break

            is_required = "是" if prop_name in required_fields else "否"
            desc = prop_details.get("description", "")
            desc = desc.replace("\n", " ").replace("\r", "").replace("|", "\\|").strip()

            lines.append(f"| `{prop_name}` | {prop_type} | {is_required} | {desc} |")

        lines.append("\n---\n")


def _generate_markdown(schema: dict) -> str:
    """
    將 OpenAPI Schema 轉換為 Markdown 格式的 API 規格書 (api_spec.md)。

    匯集了所有 API 路由的詳細參數、請求本體與回應結構，以及所有組件 Schema 的屬性表格。

    Args:
        schema (dict): 從 FastAPI 獲取的 OpenAPI Schema 字典。

    Returns:
        str: 格式化後的 Markdown 規格書字串。
    """
    lines = [
        "# API 完整規格書 (API Specification)",
        "",
        "本文件由系統自動從 FastAPI OpenAPI Schema 萃取產生，詳細記錄所有端點、參數及回傳格式。",
        "",
    ]

    _process_paths(schema, lines)
    _process_schemas(schema, lines)

    return "\n".join(lines).strip() + "\n"


def _get_route_permission(tag: str, path: str) -> str:
    """
    判斷並回傳 API 路由的存取權限字串。

    根據路由的標籤 (tag) 與具體路徑 (path)，判斷其所屬的權限等級，
    例如「管理員」、「公開」、「已登入」或「首次登入 Session」。

    Args:
        tag (str): API 所屬的標籤名稱（例如 "admin", "auth", "jobs"）。
        path (str): API 的完整路徑（例如 "/api/auth/login"）。

    Returns:
        str: 代表權限的字串敘述。
    """
    if tag == "admin":
        return "管理員"
    if path in ("/api/auth/login", "/api/health", "/api/openapi.json", "/api/docs", "/api/redoc"):
        return "公開"
    if path == "/api/auth/set-password":
        return "首次登入 Session"
    if tag == "jobs":
        if path == "/api/jobs/default-config":
            return "已登入"
        return "已登入（僅限自身任務）"
    return "已登入"


def _build_route_groups(schema: dict) -> dict[str, list[str]]:
    """
    從 OpenAPI Schema 中提取所有路由，並依據標籤進行分組。

    遍歷所有的路徑與方法，提取摘要說明與權限，並將格式化後的
    Markdown 表格列字串加入對應的標籤群組中。

    Args:
        schema (dict): 從 FastAPI 獲取的 OpenAPI Schema 字典。

    Returns:
        dict[str, list[str]]: 以標籤為鍵，包含 Markdown 表格資料列的列表為值的字典。
    """
    groups: dict[str, list[str]] = {}
    paths = schema.get("paths", {})
    for path, path_item in paths.items():
        for method, operation in path_item.items():
            tags = operation.get("tags", ["system"])
            tag = tags[0] if tags else "system"

            desc = operation.get("description", "")
            summary = desc.split("\n")[0] if desc else operation.get("summary", "")

            permission = _get_route_permission(tag, path)

            if tag not in groups:
                groups[tag] = []

            groups[tag].append(f"| `{method.upper()}` | `{path}` | {summary} | {permission} |")

    return groups


def _generate_routes_markdown(schema: dict) -> str:
    """
    將 OpenAPI Schema 轉換為 Markdown 格式的 API 路由清單 (api_routes.md)。

    依照 API 的標籤（auth、jobs、admin 等）進行分組，並整理出對應的方法、路徑、摘要說明以及存取權限。

    Args:
        schema (dict): 從 FastAPI 獲取的 OpenAPI Schema 字典。

    Returns:
        str: 格式化後的 Markdown 字串。
    """
    lines = [
        "# API 路由清單 (API Route Reference)",
        "",
        "本文件由系統自動從 OpenAPI Schema 萃取產生，列出前台與後台所需的核心 REST API 端點。所有端點均以 `/api/` 為前綴，回應格式為 JSON（除匯出路由外）。",
        "",
    ]

    tag_names = {
        "auth": "身分驗證 API (`/api/auth`)",
        "jobs": "任務管理 API (`/api/jobs`)",
        "admin": "系統管理台 API (`/api/admin`)",
        "system": "系統與文件 API",
    }

    groups = _build_route_groups(schema)

    ordered_tags = ["auth", "jobs", "admin", "system"]
    for t in list(groups.keys()):
        if t not in ordered_tags:
            ordered_tags.append(t)

    idx = 1
    for tag in ordered_tags:
        if tag not in groups:
            continue
        group_title = tag_names.get(tag, f"{tag.capitalize()} API")
        lines.append(f"## {idx}. {group_title}")
        lines.append("")
        lines.append("| 方法 | 路徑 | 說明 | 權限 |")
        lines.append("|------|------|------|------|")
        lines.extend(groups[tag])
        lines.append("")
        idx += 1

    return "\n".join(lines).strip() + "\n"


def generate_docs() -> None:
    """
    從 FastAPI 實例匯出 API 規格與路由清單，並儲存至 doc 目錄中。

    此函式會透過 FastAPI 的 openapi() 方法取得目前的 OpenAPI Schema，
    並將其匯出為以下三種格式檔案：
    1. `doc/api.json`: 原始的 OpenAPI Schema JSON 格式。
    2. `doc/api_spec.md`: 詳細的 API 規格書 (含 Schema 結構與請求參數)。
    3. `doc/api_routes.md`: 簡要的 API 路由清單 (依群組與權限分類)。

    Raises:
        OSError: 當寫入檔案發生錯誤時拋出。
    """
    doc_dir = os.path.join(PROJECT_ROOT, "doc")
    os.makedirs(doc_dir, exist_ok=True)

    openapi_schema = app.openapi()

    # 輸出為 JSON
    output_path = os.path.join(doc_dir, "api.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(openapi_schema, f, ensure_ascii=False, indent=2)
    print(f"✅ 成功匯出 API 規格 JSON 至 {output_path}")

    # 輸出為 Markdown
    md_output_path = os.path.join(doc_dir, "api_spec.md")
    md_content = _generate_markdown(openapi_schema)
    with open(md_output_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"✅ 成功匯出 API 規格 Markdown 至 {md_output_path}")

    # 輸出為路由清單 Markdown
    routes_output_path = os.path.join(doc_dir, "api_routes.md")
    routes_content = _generate_routes_markdown(openapi_schema)
    with open(routes_output_path, "w", encoding="utf-8") as f:
        f.write(routes_content)
    print(f"✅ 成功匯出 API 路由清單 Markdown 至 {routes_output_path}")


if __name__ == "__main__":
    generate_docs()
