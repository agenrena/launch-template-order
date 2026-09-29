# Agenrena Order

一份完整、可獨立客製的點餐 App，一間店一套。它由 **Business Core 的副本 + 點餐業務** 組成，和 `business_core`、`booking` 同層，但執行時不依賴它們。

這間店在 Agenrena 上是一個 Business Profile，這套 App 是它的軟體。同一套點餐核心有三個入口：顧客掃 QR code 自己點、店家的 Agent 在對話裡幫顧客準備訂單、店員在後台接單與代改。連鎖店每間店各自部署一套。

## 能力與資料歸屬

| 能力 | 設計 |
|---|---|
| 核心 | 這間店（名稱、介紹、地址、電話、時區）、獨立登入、owner/admin、團隊、Agent 金鑰／權限表、Agenrena 連接、操作紀錄 |
| 菜單 | 分類、餐點、價格、介紹、給 Agent 的說明；售完與下架分開 |
| 選項 | 單層選項群組（甜度、冰塊、加料、大小）：可設必選與最多幾個、加價；群組建一次可掛多道菜，選項可個別售完 |
| 營業 | 每週多段營業時間、打烊前停止接單、外帶／內用開關、暫停接單（15／30／60 分鐘或直到恢復） |
| 桌位 | 桌號與 QR code；同桌共用一張帳單，可一直加點 |
| 訂單 | 帳單（Tab）與每次送出（Round）；名稱、價格與選項快照；外帶每日取餐號；總覽顯示今日已接單金額 |
| 顧客 | QR 點餐匿名；外帶必留電話；Agenrena 顧客以 `bcr_` 對應核心身分 |
| MCP | 3 個核心工具 + 5 個點餐工具，預設同一顧客服務權限組 |
| Agenrena | 從 Agenrena 來的訂單，送出、接單、修改、拒單、完成、取消都以卡片送進顧客與這間店的對話 |

每次送出的餐點都先進「待確認」，由店家接單、拒單或代改。不做即時庫存：售完標示擋得住一般顧客，但同時搶最後一份時，由店家確認時處理。

這是全新資料庫的 schema，沒有舊資料升級路徑；原本 `Documents/order` 專案的資料不會搬過來。

## 啟動

**這個模板要放在伺服器上。** 顧客用自己的手機打開點餐頁（掃桌上 QR code、或 Agent 傳來的確認連結），所以 App 需要一個對外的 HTTPS 網址；只在店內電腦上執行時顧客連不到。business_core 與 booking 預設在店家電腦上執行，order 刻意不提供這條路線。

需要 Docker Compose 與 Python 3。原始碼開發使用 Python 3.13、Node 22.12+、PostgreSQL 14+。

```sh
python3 scripts/setup.py
docker compose up --build -d
docker compose exec backend python manage.py create_owner --username owner
```

第三步私下設定第一位擁有者的密碼。

- 顧客點餐頁：**http://localhost:8084/**（外帶）、`/?table=A1`（內用）
- 商家後台：**http://localhost:8084/console**

依序：商家資料 → 菜單 → 桌位與營業（營業時間、QR code）→ 開始接單。沒有預設帳密、金鑰、菜單或顧客；`setup.py` 拒絕覆蓋 `.env`。

登入使用獨立 Django session，不接 Agenrena SSO，也不共用 Firebase。忘記密碼時由部署管理者執行 `docker compose exec backend python manage.py changepassword <username>`。

## 三個入口

**QR 點餐**（`/api/web/`，不登入）

- 外帶：選餐 → 留電話 → 送出，拿到取餐號與狀態頁 `/o/<token>`。
- 內用：掃桌上的 QR code，同桌的人看到同一張帳單，可以一直加點；店員結帳關帳後才換下一組客人。
- 點餐頁只做瀏覽與下單。想問推薦、辣度或過敏原，頁面引導顧客到 Agenrena 問這間店的 Agent（在「桌位與營業」填 Agenrena 商家代碼後出現）。

**Agent**（`/mcp`，Bearer `abc_…`）

| Tool | 能力 |
|---|---|
| `get_business` | 這間店的介紹、地址、電話、時區 |
| `get_customer_profile` / `update_customer_profile` | 顧客的最小身分資料 |
| `get_shop` | 營業時間、是否接單中、外帶／內用 |
| `get_menu` | 整份菜單、價格、選項（以文字說明必選幾個）、售完，以及店家給 Agent 的說明 |
| `create_order_link` | 準備外帶購物車，回傳確認連結 `/d/<token>`；**不會下單** |
| `list_orders` | 這位顧客在這間店的訂單 |
| `cancel_order` | 店家接單前取消 |

Agent 只準備購物車；顧客在確認頁檢查、留電話、按送出後才成立訂單並取號，再由店家接單。新顧客第一次要提供稱呼。Agent 不能改價，也不能修改已送出的訂單。只做外帶：內用的人桌上就有 QR code。

**後台**（`/console`）

- 訂單：待確認、製作中、待結帳、已結束。接單、拒單（寫原因給顧客）、完成、結帳／關帳；有問題先聯絡顧客，談妥後「修改」（可改數量、選項、價格），可順便接單。忙不過來時暫停接單。
- 菜單：分類與餐點；選項群組；餐點與選項的售完一鍵切換。
- 總覽：今天已接單的張數與金額（不含待確認、拒單與取消，不是實收金額）。
- 桌位與營業：外帶／內用、幣別、停止接單時間、Agenrena 商家代碼、每週營業時間、桌號與 QR code。

## Agenrena

部署注入 `AGENRENA_VENDOR_ID`／`AGENRENA_VENDOR_SECRET` 後，擁有者在「商家資料」連接 Agenrena（見 [部署](docs/deployment.md)）。連接後，透過 Agent 確認連結成立的訂單，進度會以卡片送進顧客與這間店的對話：取餐號、餐點、金額，拒單時附店家說明。QR 點餐的顧客是匿名的，不發送；發送失敗不影響訂單。

`customer_ref` 由店家授權的 Agent 轉交，不是簽章憑證；這是第一版刻意接受的信任邊界。

## 範圍

這個模板刻意停在「最簡單但真的能用」的訂餐：菜單與選項、營業時間與暫停、三個入口下單、店家接單與代改、顧客看得到進度、老闆知道今天賣了多少。

`Documents/order` 還有但**刻意不放進模板**、留給商家依需求客製的：

- 套餐引用其他餐點、巢狀選項（套餐可做成一道菜加「主餐選擇」選項群組）
- 特殊日期營業（用暫停接單或暫時改營業時間）
- 菜單版本鎖（訂單先待確認且有價格快照，店家接單時看得到價格）
- 找回訂單、完整銷售報表與訂單查詢頁、排序拖拉介面
- 營運設備配對（櫃檯平板用配對碼登入）與 Firebase 登入：屬於各店自己的登入方式，做法與安全規則見 [客製開發](docs/development.md)

照片之後視需要再議。刻意不做：付款、廚房出單系統、完整庫存、外送、會員點數、簡訊。

## 程式結構

```text
backend/core/                   共同能力的本地副本（見 docs/core-copy.md）
backend/ordering/models.py      菜單、桌位、營業時間、帳單／每次送出、確認連結草稿
backend/ordering/services.py    下單、接單、代改、關帳、Agent 草稿與取消；三個入口共用
backend/ordering/hours.py       是否接單與原因
backend/ordering/notifications.py 訂單卡片
backend/ordering/views.py       QR / 後台 / Agent 三組 API
frontend/src/theme.css          顏色、字體、圓角與暗色模式（換品牌只改這裡，後台與顧客頁一起變）
frontend/src/customer/          顧客點餐、確認連結、訂單狀態
frontend/src/ordering/          後台：訂單、菜單、桌位與營業
mcp/src/server.ts               點餐工具，組合 mcp/src/core.ts 的核心工具
```

## 驗證

```sh
# 已設定專用測試 PostgreSQL 的 DATABASE_URL / SECRET_KEY
.venv/bin/python backend/manage.py test core.tests ordering.tests --noinput
.venv/bin/python backend/manage.py makemigrations --check --dry-run
npm run build --prefix frontend
npm test --prefix mcp
# 自行建立及刪除獨立 smoke database，需開發用 CREATEDB 權限
.venv/bin/python scripts/http_smoke.py
```

[產品決策](docs/product-decisions.md) · [客製開發](docs/development.md) · [Agent 契約](docs/agent.md) · [部署](docs/deployment.md) · [核心副本](docs/core-copy.md) · [驗證紀錄](docs/verification.md)
