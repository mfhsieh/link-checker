"""
測試共用工具模組。

提供測試環境所需的基礎設施工具，包含檢查網路通訊埠 (TCP Port) 的佔用狀態、
以及用於同步測試流程的伺服器啟動等待功能。
"""

import socket
import time


def is_port_in_use(port: int) -> bool:
    """
    檢查指定的 TCP 通訊埠是否已經被佔用。

    此函式透過嘗試建立一個 AF_INET、SOCK_STREAM 的 Socket 連線至 localhost，
    並根據 `connect_ex` 回傳的錯誤碼是否為 0 來判斷通訊埠是否處於監聽 (Listen) 狀態。

    Args:
        port (int): 欲檢查的 TCP 通訊埠號碼。

    Returns:
        bool: 若通訊埠已被佔用或正在監聽中回傳 True，否則回傳 False。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


def wait_for_server(port: int, timeout: float = 5.0) -> bool:
    """
    循環等待指定的 TCP 伺服器就緒並成功綁定通訊埠。

    此函式會以 0.1 秒為間隔不斷輪詢 `is_port_in_use`，直到伺服器啟動成功
    或達到預設的超時時間。這在啟動外部測試伺服器程序後，用來確保後續測試步驟
    能正常連線。

    Args:
        port (int): 伺服器所監聽的 TCP 通訊埠。
        timeout (float): 最長等待超時時間（秒），預設為 5.0 秒。

    Returns:
        bool: 若伺服器在限時內啟動成功並就緒回傳 True，若發生超時則回傳 False。
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        if is_port_in_use(port):
            return True
        time.sleep(0.1)
    return False
