# Agenrena Order

一份完整、可獨立客製的點餐 App，一間店一套。它由 **Business Core 的副本 + 點餐業務** 組成，和 `business_core`、`booking` 同層，但執行時不依賴它們。

這間店在 Agenrena 上是一個 Business Profile，這套 App 是它的軟體。同一套點餐核心有三個入口：顧客掃 QR code 自己點、店家的 Agent 在對話裡幫顧客準備訂單、店員在後台接單與代改。連鎖店每間店各自部署一套。

## 能力與資料歸屬

| 能力 | 設計 |
|---|---|
| 核心 | 這間店（名稱、介紹、地址、電話、時區）、獨立登入、owner/admin、團隊、Agent 金鑰／權限表、Agenrena 連接、操作紀錄 |
| 菜單 | 分類、餐點、價格、介紹、給 Agent 的說明；售完與下架分開 |
| 照片 | 每道菜可多張，第一張為列表主圖；批次上傳、拖曳或按鈕排序、縮圖位置與移除；詳情滑動看完整照片 |
| 選項 | 單層選項群組（甜度、冰塊、加料、大小）：可設必選與最多幾個、加價；群組建一次可掛多道菜，選項可個別售完 |
| 營業 | 每週多段營業時間、打烊前停止接單、外帶／內用開關、暫停接單（15／30／60 分鐘或直到恢復） |
| 桌位 | 桌號與 QR code；同桌共用一張帳單，可一直加點 |
| 訂單 | 帳單（Tab）與每次送出（Round）；名稱、價格與選項快照；外帶每日取餐號；總覽顯示今日已接單金額 |
| 顧客 | QR 點餐匿名；外帶必留電話；Agenrena 顧客以 `bcr_` 對應核心身分 |
| MCP | 3 個核心工具 + 5 個點餐工具，預設同一顧客服務權限組 |
| Agenrena | 從 Agenrena 來的訂單，送出、接單、修改、拒單、完成、取消都以卡片送進顧客與這間店的對話 |

每次送出的餐點都先進「待確認」，由店家接單、拒單或代改。不做即時庫存：售完標示擋得住一般顧客，但同時搶最後一份時，由店家確認時處理。

這是全新資料庫的 schema，沒有舊資料升級路徑；原本 `Documents/order` 專案的資料不會搬過來。

## 在這台電腦上開始（預設）

一間店 = 一個資料夾。不需要 Docker 或資料庫伺服器，只需要 [uv](https://docs.astral.sh/uv/) 與 Node.js 22.12+；沒有的話請 Agent 安裝。

- macOS：點兩下 `start.command`（或在終端機執行 `./start.command`）
- Windows：點兩下 `start.bat`

第一次會自動產生這台電腦專用的 `.env`、安裝套件、建置畫面並建立資料庫，完成後打開後台 **http://127.0.0.1:8084/console/**，在畫面上建立擁有者帳號（只能在這台電腦上建立，且只有第一次）。之後再執行只會直接開啟；程式被 Agent 改過時會自動重新建置。按 Ctrl+C 或關掉視窗就停止。

依序：商家資料 → 菜單 → 桌位與營業（營業時間）→ 開放顧客點餐（下一節）。沒有預設帳密、金鑰、菜單或顧客。

**資料都在 `data/`**（SQLite）。備份或換電腦：停止 App 後複製整個專案資料夾（含 `data/` 與 `.env`）。`data/` 與 `.env` 不進 Git。忘記密碼時執行 `./start.command manage changepassword <帳號>`（Windows：`start.bat manage changepassword <帳號>`），或請 Agent 代為執行。

## 讓顧客用手機點餐

顧客要用自己的手機打開點餐頁（掃桌上的 QR code、或 Agent 傳來的確認連結），但預設只有這台電腦連得到。所以還沒公開時，後台不產生 QR code，Agent 準備訂單也會收到 `not_published`，不會發出打不開的連結。

App 內建一個只有點餐頁的**顧客點餐入口**：在 `.env` 設定 `PUBLIC_PORT` 與 `ORDER_PUBLIC_BASE_URL`，再用 Cloudflare Tunnel 等工具把一個固定的 HTTPS 網址轉到它。後台、建立擁有者、Agent API 與 MCP 都不在這個入口上，不管 tunnel 怎麼設定都連不到。要用哪個工具由店家決定；不設定就只在店內電腦上使用。步驟見 [公開顧客點餐頁](docs/publish.md)。

- 顧客點餐頁：`<公開網址>/`（外帶）、`/?table=A1`（內用）
- 商家後台：只在這台電腦上，http://127.0.0.1:8084/console/

點餐只發生在營業時間，而營業時間店裡的電腦本來就開著；請關掉營業時間的自動睡眠。

## 放到伺服器上

要隨時從外面管理後台時，改用 Docker Compose + PostgreSQL 放到伺服器上，整個網站對外，不需要顧客點餐入口的設定。同一份程式碼，以 `DATABASE_URL` 決定用哪種資料庫。

```sh
python3 scripts/setup.py
docker compose up --build -d
docker compose exec backend python manage.py create_owner --username owner
```

第三步私下設定第一位擁有者的密碼。`ORDER_PUBLIC_BASE_URL` 設成正式網址，細節見 [部署](docs/deployment.md)。

登入使用獨立 Django session，不接 Agenrena SSO，也不共用 Firebase。

## 三個入口

**QR 點餐**（`/api/web/`，不登入）

- 外帶：選餐 → 留電話 → 送出，拿到取餐號與狀態頁 `/o/<token>`。
- 內用：掃桌上的 QR code，同桌的人看到同一張帳單，可以一直加點；店員結帳關帳後才換下一組客人。
- 點餐頁只做瀏覽與下單。想問推薦、辣度或過敏原，頁面引導顧客到 Agenrena 問這間店的 Agent（在「桌位與營業」填 Agenrena 商家代碼後出現）。

**Agent**（擁有者在「Agent 連接」建立金鑰，只顯示一次）

- **Agent 在這台電腦上（預設）**：頁面直接給一段 `mcpServers` 設定（`node mcp/dist/index.js --stdio`，金鑰已填好），交給 Agent 即可。MCP 不在顧客點餐入口上，不需要對外開放。
- **App 放在伺服器上**：連到 `https://<網域>/mcp` 並帶 `Authorization: Bearer abc_…`。

| Tool | 能力 |
|---|---|
| `get_business` | 這間店的介紹、地址、電話、時區 |
| `get_customer_profile` / `update_customer_profile` | 顧客的最小身分資料 |
| `get_shop` | 營業時間、是否接單中、外帶／內用 |
| `get_menu` | 整份菜單、價格、選項（以文字說明必選幾個）、售完，以及店家給 Agent 的說明 |
| `create_order_link` | 準備外帶購物車，回傳確認連結 `/d/<token>`；**不會下單** |
| `list_orders` | 這位顧客在這間店的訂單 |
| `cancel_order` | 店家接單前取消 |

Agent 只準備購物車；顧客在確認頁檢查、留電話、按送出後才成立訂單並取號，再由店家接單。還沒公開顧客點餐頁時，`create_order_link` 回 `not_published`。新顧客第一次要提供稱呼。Agent 不能改價，也不能修改已送出的訂單。只做外帶：內用的人桌上就有 QR code。

**後台**（`/console`）

- 訂單：待確認、製作中、待結帳、已結束。接單、拒單（寫原因給顧客）、完成、結帳／關帳；有問題先聯絡顧客，談妥後「修改」（可改數量、選項、價格），可順便接單。忙不過來時暫停接單。
- 菜單：分類與餐點；選項群組；餐點與選項的售完一鍵切換。
- 總覽：今天已接單的張數與金額（不含待確認、拒單與取消，不是實收金額）。
- 桌位與營業：外帶／內用、幣別、停止接單時間、Agenrena 商家代碼、每週營業時間、桌號與 QR code（公開顧客點餐頁之後才產生）。

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

刻意不做：付款、廚房出單系統、完整庫存、外送、會員點數、簡訊。

## 程式結構

```text
scripts/start.py                在這台電腦上執行（start.command / start.bat 呼叫它），含顧客點餐入口
backend/config/public.py        顧客點餐入口放行哪些路徑
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
.venv/bin/python backend/manage.py test core.tests ordering.tests --noinput      # SQLite（預設）
DATABASE_URL=postgresql://… .venv/bin/python backend/manage.py test core.tests ordering.tests --noinput
.venv/bin/python backend/manage.py makemigrations --check --dry-run
npm run build --prefix frontend
npm test --prefix mcp
./start.command --no-browser                     # 實際在這台電腦上啟動
# 自行建立及刪除獨立 smoke database，需開發用 CREATEDB 權限
.venv/bin/python scripts/http_smoke.py
```

## 授權

[MIT](LICENSE)。可以免費使用、修改，也可以拿去幫店家建置並收費，不需要向 Agenrena 分潤或回報；只要保留 LICENSE 檔即可。「Agenrena」名稱與商標不在授權範圍內，改過的版本請不要宣稱是 Agenrena 官方版本。

[產品決策](docs/product-decisions.md) · [公開顧客點餐頁](docs/publish.md) · [客製開發](docs/development.md) · [Agent 契約](docs/agent.md) · [部署](docs/deployment.md) · [核心副本](docs/core-copy.md) · [驗證紀錄](docs/verification.md)

## 軟體名稱（2026-10-02）

登入頁、後台左上角和瀏覽器分頁使用商家的軟體名稱；直接從 GitHub 取得時預設為 `Order`。Agenrena Business 下載會寫入 `backend/app-config.json` 的 `software_name`（最多 120 字），首次建立商家資料時保存至資料庫。檔案缺少、空白或無效時使用模板預設值。後台「商家資料」可改名，之後啟動不會用下載設定覆蓋。軟體名稱與商家名稱分開，也不會同步改動 Agenrena 上的 App/Vendor 名稱。頁底的 `Powered by Agenrena` 可自行移除，不影響功能。此版本只針對全新初始化，沒有舊資料搬移流程。

## 餐點照片

在「菜單 → 新增／編輯餐點」一次選取多張照片，與餐點一起按儲存。第一張就是列表主圖，可拖曳或用上下箭頭排序，也可調整主圖的縮圖位置、移除照片。未儲存即關閉不會改動照片；沒有照片仍可正常上架。每道菜最多 12 張，每張最多 10 MB／2400 萬像素，支援 JPEG、PNG、WebP。

顧客列表顯示右側小圖，點開餐點後可左右滑動或按箭頭看完整比例照片（附張數）；售完或停止接單時仍可瀏覽，但不能加入購物車。照片屬於餐點，不綁選項、不進訂單快照。

上傳時自動校正方向、移除相機中繼資料、轉成 WebP，詳情最長邊 1600px、縮圖 480px，不保留原始檔。照片透過 `/api/web/menu-photos/` 提供，沿用顧客公開入口。

本機預設存於 `data/media/`，備份整個 `data/` 即包含照片與 SQLite。Compose 用獨立 `menu_media` volume，需與 PostgreSQL 一起備份。其他託管（含 Runtime）必須替 `MEDIA_ROOT` 配置持久儲存並備份；本模板的 Docker 預設路徑為 `/app/media`，單靠容器檔案系統無法在重建時保存照片。
