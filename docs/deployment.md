# 部署

## 這台電腦（預設）

見 README：`start.command`／`start.bat` 執行 `scripts/start.py`，只需要 uv 與 Node.js 22.12+。Django 以 waitress 直接提供 API 與建置好的畫面（沒有 nginx），資料是 `data/db.sqlite3`（WAL；寫入交易一開始就取得鎖，同一時間只有一個寫入）。預設只聽 127.0.0.1:8084；`LOCAL_APP=true` 由啟動程式設定，打開本機建立第一位擁有者與 stdio 的 MCP 設定說明。顧客服務 Agent 在同一台電腦以 stdio 啟動 MCP。

顧客的手機要能打開點餐頁：設定 `PUBLIC_PORT` 後，同一個程式另外在 127.0.0.1:`PUBLIC_PORT` 提供只有點餐頁的顧客點餐入口，由店家選的 tunnel 公開；`ORDER_PUBLIC_BASE_URL` 是顧客打開的網址。步驟見 [公開顧客點餐頁](publish.md)。

這台電腦要開著、App 要在執行，顧客才能點餐、Agent 才能回答；開機自動啟動目前沒有內建，由商家或 Agent 依作業系統設定。備份是停止後複製整個資料夾。

## 伺服器：Docker Compose

需要隨時從外面管理後台時使用。見 README 的 setup / compose / create_owner。所有資料庫與 backend/MCP 埠都在 Compose 私有網路，只有 web 對外；預設綁定 127.0.0.1:8084，避免與 Booking 8080、Business Core 8082、Runtime 5188 混淆。整個網站對外，不使用 `PUBLIC_PORT`。

正式環境設定專用網域、HTTPS、ALLOWED_HOSTS、CSRF_TRUSTED_ORIGINS、COOKIE_SECURE=true。使用能覆寫 X-Forwarded-Proto 的可信反向代理；不要將私有 backend 直接公開。持久化 PostgreSQL 並安排備份；此模板不自行實作 Runtime 的備份／復原管理。伺服器路線不設定 `LOCAL_APP`，網頁上的首次建立帳號不會開放。

## Agenrena Runtime

runtime.json 宣告 Django + static frontend + optional MCP，以及 django_admin bootstrap。Runtime 注入 DATABASE_URL、SECRET_KEY、Host/CSRF/SSL 設定。後端 8000、前端 8080、MCP 8765，GET /health/ 驗證 DB。

先 migrate，再 runtime_bootstrap，再啟動服務。Bootstrap 使用 BOOTSTRAP_ADMIN_USERNAME / BOOTSTRAP_ADMIN_PASSWORD，只建立第一位有效 owner，不重設既有帳號。

MCP API URL 使用 ORDER_API_URL；為兼容現有 Runtime provider，亦接受 CORE_API_URL 與 BOOKING_API_URL。這是相容環境變數名稱，不表示依賴 Booking 業務。

`ORDER_PUBLIC_BASE_URL` 必須設成顧客開啟的正式網址（例如 `https://order.example.com`）：Agent 的確認連結由它組成。MCP 直接呼叫 backend，無法從請求推得公開網址；未設定時連結會指向內部位址。`ORDER_DRAFT_TTL_MINUTES` 預設 30。`AGENRENA_SHARE_BASE_URL` 預設 `https://agenrena.com`，用於顧客頁的「到 Agenrena 問這間店」連結。

## Agenrena Vendor 憑證

每個部署出去的 App 是一個 Agenrena Vendor，需要自己的 `AGENRENA_VENDOR_ID` 與 `AGENRENA_VENDOR_SECRET`（`bvs_…`）。目前由 Agenrena admin 為這個 App 建立 Vendor 並發出 secret，部署者把兩個值放進部署環境（Compose 的 `.env` 或 Runtime 的秘密設定）；`AGENRENA_BASE_URL` 預設 `https://api.agenrena.com`。沒有設定時 Agenrena 功能關閉，其他功能照常。

secret 只放在部署環境：不進原始碼、Git、打包 ZIP、log、API 回應或前端。商家的 Coding Agent 讀得到部署環境；這把 secret 只能代表這個 App，拿到也只能對已授權這個 App 的店發訊息，不會越權到其他商家。

輪替（手動）：Agenrena 為同一個 Vendor 發一把新 secret（新舊可同時有效）→ 更新部署環境並重啟 backend → 確認通知正常 → 在 Agenrena 停用舊的。App 以 secret 區分 token 快取，換新 secret 後會自動換新 token。懷疑外洩時立即停用舊 secret；目前平台上已換出的 token 最長仍可用 1 小時。

App 只連出到 `AGENRENA_BASE_URL`；Agenrena 不回呼 App，不需要對外開放額外端點。

## 發布到模板目錄

在 GitHub 發正式 release（例如 `v0.1.0`；草稿與 prerelease 不發布）。`.github/workflows/release.yml` 先跑完 `check.yml` 的全部檢查，再以 `scripts/publish_template.py` 從該 commit 打包並上傳到 S3 的模板目錄（`catalog.json` 依模板 id 合併，不會蓋掉其他模板）。ZIP root 為此專案根目錄，不含 .env、node_modules、建置結果、.venv、Git、.github、`data/`、資料庫或密鑰檔；檔案權限照 Git 記錄，所以 `start.command` 保持可執行。需要 repo 的 `template-publish` environment 設定 `LAUNCH_TEMPLATE_BUCKET`、`AWS_TEMPLATE_PUBLISH_ROLE_ARN`（可選 `TEMPLATE_REGION`，預設 `us-east-1`，須與 bucket 所在 region 相同），且 AWS 角色信任這個 repo。發布前 bucket 需已有 `catalog.json`（新 bucket 先放入 `[]`）。

## 照片持久儲存與備份

本機預設 `data/media/`。Docker image 預設 `MEDIA_ROOT=/app/media`；Compose 已掛載 `menu_media` volume，該路徑由 app 使用者擁有。使用外部 bind mount 時需授予容器 app 使用者讀寫權限。備份與還原需同時包含資料庫和圖片目錄，建議停止寫入後一起備份。

Runtime 或其他託管必須另外配置可跨重建保留的儲存並設定 `MEDIA_ROOT`；本次未修改 Runtime 的部署契約，也未驗證其 volume 配置。反向代理須允許餐點編輯批次上傳最多 125 MiB；模板 Nginx 已設定。圖片由 Django `/api/web/menu-photos/<uuid>/image/` 與 `thumbnail/` 提供，不需要公開整個 MEDIA_ROOT。
