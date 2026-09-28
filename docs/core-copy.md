# Business Core 副本關係

來源：同層 business_core，2026-09-28 版本（一間店一套 App、Agenrena 連接）。本專案是完整副本，沒有執行期跨資料夾 import、symlink 或共用套件依賴。

與 business_core 不同的地方都是點餐的明確延伸點：

- core/permissions.py 在 owner/admin 上增加 menu.read、menu.write、orders.read、orders.manage、ordering.settings。
- ordering/migrations/0002_ordering_permissions.py 將 menu.read、order.read、order.create、order.cancel 加到同一個 customer_service role，並建立 OrderingSettings。
- core 測試的預設權限清單隨此模板新增能力調整，其餘核心測試（含 test_agenrena）沿用。
- config/settings.py 加入 ordering app、ordering.api_errors 例外處理、ordering 節流，以及 ORDER_PUBLIC_BASE_URL、ORDER_DRAFT_TTL_MINUTES、AGENRENA_SHARE_BASE_URL；config/urls.py 納入 ordering.urls。
- 前端 main.tsx 依網址分流顧客頁（/、/d/、/o/）與後台（/console）；App.tsx 增加訂單、菜單、桌位與營業；Overview、Audit、style.css 保留點餐項目。其他核心頁面與 business_core 相同。
- mcp/src/core.ts 保留共同工具，server.ts 再註冊點餐工具；api.ts 的 OrderApi 繼承共用傳輸。

維護官方模板時，先比較上游核心變更，再把適用修正整合到這些副本；不得直接覆蓋商家自己的客製版本。
