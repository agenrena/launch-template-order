# 開發與客製

共同能力保持直接可修改。新增業務時在 backend 新增 domain app，讓 Booking/Order 等模型用 ForeignKey 指向 core.CustomerIdentity。一套 App 就是一間店，業務資料不需要店或分店欄位；要讓顧客在 Agenrena 對話裡收到進度，在寫入的交易裡呼叫 `core.services.notify_customer`（見 [Agent 與權限](agent.md)）。

## 開發環境

Python 3.13、Node 22.12+、PostgreSQL 14+。不使用 SQLite 代替 PostgreSQL 測試。

```sh
python3.13 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
# 私下設定 SECRET_KEY、DATABASE_URL；後端不自動讀取 .env。
.venv/bin/python backend/manage.py migrate
.venv/bin/python backend/manage.py create_owner --username owner
.venv/bin/python backend/manage.py runserver 127.0.0.1:8044
npm ci --prefix frontend
npm run dev --prefix frontend
```

Vite 使用 5192，代理 API 到 8044、MCP 到 8768。可用 ORDER_DEV_API / ORDER_DEV_MCP 覆寫。設定 COOKIE_SECURE=false、CSRF_TRUSTED_ORIGINS=http://localhost:5192,http://127.0.0.1:5192，以及 ORDER_PUBLIC_BASE_URL=http://127.0.0.1:5192（Agent 確認連結的網址）。MCP 另設定 ORDER_API_URL、PORT=8768 執行。顧客頁在 `/`，後台在 `/console`。

## 修改入口與驗證

- 新增共同欄位：models → migration → serializer → service → UI。
- 新增顧客工具：AgentPermission/Role migration → permissions/services → Agent API → MCP schema/tool description → PostgreSQL與 MCP 測試。
- 新增顧客資料讀寫：先取得 scoped_customer，再以其內部 UUID 限制所有查詢。測試 A 顧客不能讀寫 B 的資料。
- 新增顧客通知：決定事件與卡片內容，在業務寫入的交易裡呼叫 notify_customer，`message_id` 對同一事實保持穩定。測試用 `patch("core.agenrena._request", …)` 模擬平台，參考 core/tests/test_agenrena.py；不要在測試中連到真實 Agenrena。
- 更換登入：session/login/logout、authentication 與前端登入頁；保留 CSRF、Membership 授權及操作紀錄。Firebase 是商家可自行實作的客製，沒有預先整合。
- 新增角色：人的 HUMAN_PERMISSIONS 與 Membership choices/constraint；Agent 則改 AgentRole/AgentPermission 資料。兩者不要混用。
- 首次預設在 0002_defaults migration，只跑一次；不要每次啟動重設商家已修改的角色資料。
- 更新業務資料和成功操作紀錄在同一個 transaction。不要將完整輸入直接放入 audit.detail。

```sh
.venv/bin/python backend/manage.py test core.tests ordering.tests --noinput
.venv/bin/python backend/manage.py makemigrations --check --dry-run
npm run build --prefix frontend
npm test --prefix mcp
```

Role/Permission 是具體權限表，不是通用規則引擎。沒有分店結構：連鎖店每間店各自一套 App。本版本不新增業務插件、付款、會員、排班模型。

## 真實 HTTP 驗證

前端與 MCP 完成 npm ci / build 後，設定 DATABASE_URL 指向有 CREATEDB 權限的**開發用** PostgreSQL，再執行：

```sh
.venv/bin/python scripts/http_smoke.py
```

此腳本建立隨機命名的獨立 database，啟動暫時的 API、Vite 和 MCP，驗證登入、CSRF、代理轉送、MCP 工具、顧客範圍與撤銷金鑰；結束後關閉程序並刪除它建立的資料庫。它不修改既有 App 資料。

## 點餐的修改入口

- 規則：`ordering/services.py`（下單、接單、代改、關帳、Agent 草稿與取消）與 `ordering/hours.py`（是否接單）。三個入口都呼叫它們；新增規則時放這裡，並同時測 QR、後台與 Agent。
- 資料：`ordering/models.py`。訂單明細複製名稱與價格；改菜單不影響已送出的訂單。
- 三組 API：`ordering/views.py`（`/api/web/` 公開、`/api/console/` 後台、`/api/agent-api/` Agent），回應格式在 `ordering/payloads.py`。
- 通知：`ordering/notifications.py`。新增事件時沿用 `announce`，讓 `client_message_id` 對同一事實穩定。
- 前端：顧客頁 `frontend/src/customer/`（不登入、手機優先）；後台 `frontend/src/ordering/`。
- 更換外觀：只改 `frontend/src/theme.css`。換品牌色改 `--brand`（淺色品牌色時把 `--brand-fg` 改成深色），後台與顧客點餐頁的按鈕、淺底、連結都會跟著變；暗色模式在同檔的 `prefers-color-scheme` 區塊。`style.css`、`customer/customer.css` 與元件只能用 `var(--…)`，`npm run check:style`（build 也會跑）會擋下寫死的顏色。顧客頁較大的圓角由 `--radius-lg` 算出。訂單狀態：待確認用品牌淺底、完成用 `--ok`、拒單／打烊用 `--danger`。
- MCP：`mcp/src/server.ts`；工具描述就是 Agent 的說明書，行為改變時一起改。
- 選項：`OptionGroup`／`Option` 屬於整間店、以多對多掛在餐點上，只有一層；規則在 `services._choices`（必選、上限、售完、不屬於這道菜）。訂單以 `RoundItemChoice` 保存群組名、選項名與加價。
- 暫停接單：`OrderingSettings.orders_paused／paused_until／pause_reason`，由 `hours.accepting_orders` 在營業時間之前檢查；到期不需排程。
- README 列出 `Documents/order` 有但刻意不放進模板的功能；要加回時保留這裡的單店、核心身分與通知方式。

## 客製：共用設備與店員角色

模板只附 Django 帳號密碼與 owner/admin。櫃檯平板、店員權限或 Firebase 登入屬於各店自己的管理方式，由商家的 Coding Agent 依需求實作。常見做法與要守的規則：

- **店員角色**：在 `core/permissions.py` 的 `HUMAN_PERMISSIONS` 新增角色並列出權限，同時更新 `Membership` 的 choices 與 constraint（新增 migration）。業務規則只看權限，不必改。
- **共用設備（例如櫃檯平板用配對碼登入）**：新增一個 authentication class 與 `Actor` 種類（例如 `device`），在 `authorize` 為它給固定、較小的權限。
  - 設備憑證只存雜湊，放在 HttpOnly、SameSite=Strict、正式環境 Secure 的 cookie；寫入 cookie 的請求要驗 CSRF。
  - 每次請求重新檢查是否過期或停用，停用下一次請求就生效；每台設備可個別停用。
  - 配對碼要短時效、單次使用，並限制頻率；只知道畫面上的配對碼不能領走憑證（領取時要搭配發起配對的瀏覽器本身的憑證）。
  - 設備的操作寫入操作紀錄時記錄「哪台設備」，不要冒用授權它的人的身分。
- **Firebase 等外部登入**：替換 session/login/logout 與前端登入頁，保留 Membership 授權、CSRF 與操作紀錄。
