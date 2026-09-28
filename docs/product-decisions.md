# 已確認產品決策

2026-09-27；Agenrena 連接：2026-09-28。

1. 這是 Agenrena 旗下產品。共通基礎名為 business_core，與 booking、order 同層；Booking、Order 是可選模板，不是所有 App 的底座。
2. 核心範圍：Business（這間店）、使用者、登入、基本後台、Agent 接入、Agenrena 連接、操作紀錄。
3. **一間店，一套 App。** Business 就是這間店，沒有 Location／分店結構，也不是 multi-tenant。連鎖或加盟時每間店各自部署一套 App（2026-09-28 取代原本的「一個 Business 多個 Location」）。
4. 登入預設獨立 Django 帳號密碼。沒有 Agenrena SSO，不共用 Agenrena Firebase；商家自行客製其他登入方式。
5. 人預設 owner / admin。第一位 owner 私下設定密碼或由 Runtime 提供隨機初始憑證。禁止移除最後一位有效 owner。
6. Coding Agent 修改程式與處理部署；Business Agent 預設面對顧客，並非管理後台的營運代理。
7. Agent 有獨立權限表，預設一個 customer_service 權限組。各功能明確檢查操作與資料範圍，後續角色由商家自行修改。
8. Agenrena 提供固定 customer_ref。App 以可空且有值時唯一的 agenrena_customer_ref 對應內部顧客身分 UUID（見 17）。手動顧客可沒有 reference，不按姓名／電話自動合併。
9. 第一版信任授權 Agent 正確帶入 Agenrena 對話 reference，不增加簽章。其隨機性由 Agenrena 產生器決定，本專案不宣稱已驗證不可猜測性。
10. CustomerIdentity 僅示範身分對應與顧客範圍，不含 CRM、訂單或預約。業務模板自行增加其功能。
11. 特殊規則由商家改程式；不為所有可能需求加入 Settings、plugins 或 workflow engine。
12. Runtime 負責託管；商家與自己的 Coding Agent 負責客製、測試與維護。不自動替商家合併 Base 更新。

## 一間店與 Agenrena（2026-09-28）

模板示範的是我們認為的未來：顧客面對的是「店」，店在 Agenrena 上有代表它的 Agent；Agent 的能力來自店的軟體，軟體掌握事實並把結果推回對話。最乾淨的形狀是：**一間店 = Agenrena 上的一個 Business Profile = 一套 App = 一個 Vendor = 一筆授權 = 一隻客服 Agent。**

13. **App 是這間店的 Vendor。** Vendor 憑證（`AGENRENA_VENDOR_ID`／`AGENRENA_VENDOR_SECRET`）只從部署環境注入，不進原始碼、log、API 回應或前端。每個部署出去的 App 各有自己的 Vendor，預設打開；沒有設定時 Agenrena 功能關閉，其他功能照常。Vendor 的建立與輪替在模板之外（目前由 Agenrena admin 發給，之後可由 Runtime 自動化）。這正是 Agenrena 所說「沒有開發商的商家，自己就是 Vendor」。
14. **拿掉 Location。** 情境比較後決定：單店不需要據點概念；加盟店共用一套 App 會缺少依店的權限；單店客製會牽動其他店；Agenrena 本來就把每間店當成不同的 Business Profile 與不同的顧客 reference。只有「同一老闆的多間分店想共用菜單、合併報表」受影響，這屬於品牌層需求，留給 Agenrena 的品牌層（BusinessGroup／group_ref）或之後另外處理，不塞進每套 App。地址、電話併入 Business。
15. **授權一次。** 這間店最多一筆 grant（scope 只有 `messages:send`），由 owner 在「商家資料」產生授權連結，該店在 Agenrena 上的 owner/admin 用 App 掃描同意。admin 只能查看狀態。
16. **Agent 金鑰代表這間店。** 客服 Agent 只替這間店服務；顧客想去其他分店，由那間店自己的 App 與 Agent 服務。
17. **顧客關係屬於這間店。** `customer_ref` 是 Agenrena 以店發給的 `bcr_` 值；同一個人在另一間店（另一套 App）是另一段關係，不跨 App 合併。
18. **通知是核心能力，事件由業務模板決定。** 核心提供 `notify_customer`，在交易提交後送進顧客與這間店的對話；送達失敗不影響業務資料，店家撤銷授權後自動停止。核心本身不主動發訊息。
19. **不在這一版：** identity link（有簽章的顧客身分連結）、Runtime 自動建立 Vendor 與輪替、接收顧客訊息（inbound webhook）、品牌層跨店識別與合併報表。

## Order 模板已確認決策（2026-09-28）

- 以 business_core 的完整副本加上 ordering 業務建立，不做執行期共用依賴；來源專案 `Documents/order` 不修改、不搬資料，也不帶入其 .env、服務帳戶、照片或虛擬環境。
- 一間店一套 App（決策 3、14）：order 原本的多 Shop 結構改為單一 Business；菜單、桌位、營業時間、取餐號都屬於這間店。
- 登入改用核心的 Django 帳密；order 的 owner/staff 對應核心 owner/admin，兩者都能接單、管理菜單與營業設定，成員、金鑰與 Agenrena 連接仍只限 owner。
- 顧客身分改用核心 CustomerIdentity（取代 order 的 orders.Customer 與 Tab.agenrena_customer_ref）；通知改用核心的 Agenrena 連接與 notify_customer（取代 order 自己的 integrations）。
- 分兩階段移植。第一階段（2026-09-29）：菜單與售完、QR 外帶與內用加點、Agent 確認連結、店家接單／拒單／代改／完成／關帳、每週營業時間與停止接單、訂單通知。
- 第二階段縮小為「最簡單但真的能用」的訂餐（2026-09-29）：**單層選項**（甜度、冰塊、加料、大小；群組屬於整間店、可掛在多道餐點、選項可個別售完）、**暫停接單**（15／30／60 分鐘或直到恢復，附顧客看得到的原因）、**今日營收**（總覽顯示已接單張數與金額）。
- 不移植（留給商家客製）：套餐引用其他餐點與巢狀選項（套餐以一道菜加「主餐選擇」選項群組表達）、特殊日期營業（用暫停或暫時改營業時間）、菜單版本鎖（訂單先待確認且有價格快照）、找回訂單（取餐號與 Agent 對話已足夠）、排序管理介面（用排序數字）、完整銷售報表與訂單查詢頁。照片之後視需要再議。
- 營運設備配對不放進模板：它是另一種登入方式，和 Firebase 同屬商家自行客製的範圍（決策 4、11）。開發文件寫明做法與安全規則，由商家的 Coding Agent 實作。
- 沿用 order 的產品決策：QR 頁只做瀏覽與下單，問答留在 Agent 對話並以連結導向 Agenrena；Agent 只準備購物車，由顧客確認送出；每次送出都先待確認；不做即時庫存；外帶必留電話；有問題由店家聯絡顧客後代改；Agent 接單後不能取消。
- 全新 schema，沒有舊資料升級路徑。
