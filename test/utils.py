"""
測試共用工具模組。

包含檢查 TCP Port 是否佔用、等待伺服器啟動等功能。
"""

import socket
import time


def is_port_in_use(port: int) -> bool:
    """
    檢查指定的 TCP 通訊埠是否已經被佔用。

    Args:
        port (int): 欲檢查的通訊埠號碼。

    Returns:
        bool: 若通訊埠已被佔用回傳 True，否則回傳 False。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


def wait_for_server(port: int, timeout: float = 5.0) -> bool:
    """
    循環等待指定的 TCP 伺服器就緒並成功綁定通訊埠。

    Args:
        port (int): 伺服器所監聽的 TCP 通訊埠。
        timeout (float): 最長等待超時時間（秒），預設為 5 秒。

    Returns:
        bool: 若伺服器在限時內啟動成功並就緒回傳 True，否則回傳 False。
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        if is_port_in_use(port):
            return True
        time.sleep(0.1)
    return False
