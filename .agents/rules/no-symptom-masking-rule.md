---
trigger: always_on
---

# 無破壞性除錯與合約保護原則 (No Symptom Masking Rule)

- 當單元測試、整合測試或系統功能發生失敗時，Agent **嚴禁採用掩蓋症狀的修補手段**：
  1. 嚴禁透過註解掉測試斷言 (Commenting Out Assertions)、降低測試比對標準來強行通過測試。
  2. 嚴禁使用無意義的空 `try...except: pass` 吞掉例外。
  3. 嚴禁在 API 失敗時回傳預設的 Dummy 假資料遮蔽底層錯誤。
  4. 嚴禁直接刪除失敗的單元測試案例。
- **強制規定**：當測試或功能失敗時，必須深入追溯 Upstream 數據源與底層 API/ORM 合約根因，提供實質性修復，確保系統合約與行為正確。
