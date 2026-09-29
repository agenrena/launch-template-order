# 驗證紀錄

## 2026-09-30：樣式集中於 theme.css、發布流程

同步 business_core 的樣式重構（theme.css、check:style、側欄圖示）與發布流程；刻意不同步本機執行，order 只在伺服器上執行。Agenrena 未設定。

| 檢查 | 結果 |
|---|---|
| Django / PostgreSQL | 71 項測試通過（後端未修改） |
| Frontend | 正式建置通過；check:style：後台 style.css 與顧客頁 customer.css 都沒有 theme.css 以外的色碼（原本約 100 處，含顧客頁自己定義的綠色 `--brand`） |
| MCP | 10 項測試通過 |
| 發布 | 發布腳本 14 項測試通過；workflow YAML 可解析；在臨時 repo 實際 `pack`：ZIP 約 190 KB、105 個檔案，不含 node_modules、建置結果、.github 或 .env（只有 .env.example） |
| Docker Compose 與畫面 | 乾淨副本 `docker compose up --build`，加入菜單、選項、全天營業時間與桌位 A1。Chrome 截圖：手機 QR 內用點餐（選項、購物車、送出、訂單進度）亮色與暗色；後台訂單（待確認用品牌淺底）亮色與暗色 |
| 換品牌 | 測試副本只改 `theme.css` 的 `--brand` 成藍色並重建前端 image：顧客頁的連結與按鈕、後台側欄、按鈕與待確認標籤全部變藍 |
| 程式整理 | Prettier（修改過的檔案） |

尚未執行：Agent 確認連結頁（/d/）的畫面、與真實 Agenrena 的授權與通知。

## 2026-09-29：第二階段（單層選項、暫停接單、今日營收）

同樣在 scratchpad 的獨立 venv 與臨時 PostgreSQL 14 叢集執行，Agenrena 以模擬的 HTTP 回應代替。

| 檢查 | 結果 |
|---|---|
| PostgreSQL 後端 | 71 項 core.tests + ordering.tests 通過（第一階段 61 項加上 10 項） |
| 選項 | 加價計入明細與金額、群組名／選項名／加價快照（改選項不影響舊訂單）；必選未選附可選項目、超過上限、不屬於這道菜、格式錯誤都拒絕；售完選項擋顧客但店員代改可選，店員仍須滿足必選；顧客與 Agent 菜單描述選項（Agent 以文字說明「必選 1 個」）；Agent 確認連結帶選項、查單回傳可重送的選項 id 與可讀文字；通知卡片列出選項 |
| 後台選項管理 | 群組與選項一起新增、排序、改名、刪除、新增；最少／最多、重名、別的群組的選項 id、空清單都拒絕；餐點掛群組；單一選項切換售完且不能順便改其他欄位；Agent 不能進入 |
| 暫停接單 | 暫停後顧客頁、QR 外帶、Agent 都收到含原因與恢復時間的拒絕；恢復後可下單；定時暫停到期自動解除、手動暫停不會；不合法的分鐘數／動作／過長原因拒絕；操作紀錄 |
| 今日營收 | 只算已接單與完成（含選項加價），不算待確認與拒單；Agent 不能讀 |
| Migration | 全新 database migrate（含 0003_options_and_pause）與 makemigrations --check --dry-run 通過 |
| Frontend | TypeScript 與 Vite 正式編譯通過；編譯抓到並修正一處把 option_groups 誤加到分類表單的錯誤 |
| MCP | 10 項測試通過，購物車可帶 options，拒絕非 id 的選項 |
| 真實 HTTP | 在第一階段流程上加入：後台建立選項群組並掛到餐點、QR 外帶帶選項（金額含加價）、暫停與恢復、Agent 必選未選被拒後帶選項建立連結、今日營收 |
| 畫面 | CDP 截圖：手機選項選擇（必選未選時按鈕停用並提示、售完選項停用、加價標示）、後台接單列出選項與暫停列、菜單頁選項群組、總覽今日營收；依截圖把選項售完勾選改為「勾選表示售完」 |

尚未驗證：瀏覽器互動測試（實際點選送出）、真實 Agenrena、Docker image build 與 Compose 啟動、Runtime 部署。

## 2026-09-29：第一階段（點餐主流程）

在 scratchpad 的獨立 venv 與臨時 PostgreSQL 14 叢集執行，不讀寫 `Documents/order`、Booking、Runtime 或 Agenrena 的既有資料庫；Agenrena 以模擬的 HTTP 回應代替。

| 檢查 | 結果 |
|---|---|
| PostgreSQL 後端 | 61 項 core.tests + ordering.tests 通過：核心 32 項（含 Agenrena 12 項）與點餐 29 項 |
| 點餐規則 | 菜單顯示售完、隱藏下架；外帶必留電話、每日取餐號、價格快照、待確認不計帳；售完拒單並提示同類餐點；不合法明細（空、非 id、數量 0、顧客帶價格）拒絕；內用同桌共用帳單、關帳後拒絕加點並開新帳單；外帶不能加點；外帶／內用開關與營業時間擋住三個入口；開始時間、午休與停止接單分鐘數；取餐號每日重新計算 |
| 後台 | 接單、完成、錯誤狀態轉換、未知操作；代改不受售完限制、保留狀態、可改價、可同時接單、結束後不能改；拒單原因；關帳；服務畫面列出今天與未完成帳單、指定日期查詢；只有成員能進後台；菜單、桌位 CRUD 與操作紀錄；接單設定與每週營業時間的驗證（七天、不可跨日、不可重疊） |
| Agent | 讀店家與菜單（含售完原因與店家說明）；新顧客必填稱呼、之後記住；拒絕自編 reference；確認連結在顧客送出前不成立訂單、頁面不洩漏 reference、必填電話、重送冪等、顧客可調整購物車、過期拒絕；只看得到與取消自己的訂單、接單後不能取消、重送安全；不能帶價格、不能進後台 |
| 通知 | 送出、修改、接單、完成的卡片依序送出且 message id 各不相同、不含電話；拒單附原因；QR 匿名訂單不發送；送達失敗不影響訂單 |
| 並行 | 8 筆同時外帶取得 1–8 不重複的取餐號 |
| Migration | 全新 database migrate 與 makemigrations --check --dry-run 通過 |
| Frontend | TypeScript 與 Vite 正式編譯通過（Node 22.23.2） |
| MCP | 10 項測試通過：8 個工具、參數原樣轉交、本地拒絕價格／自編 reference／名稱代替 id／空購物車、店家拒絕原樣回傳、查單與取消帶顧客 reference |
| 真實 HTTP | `scripts/http_smoke.py`：後台登入與建立菜單、桌位、營業時間；QR 外帶與內用加點；Streamable HTTP 讀店家與菜單、新顧客稱呼、確認連結、顧客在網頁確認與重送、依顧客查單、他人取消被拒、取消；後台服務畫面看到三個入口的訂單並接單、完成、關帳；撤銷金鑰被拒絕 |
| 畫面 | 以 Chrome DevTools Protocol 模擬 390px 手機截圖：外帶菜單、內用菜單、Agent 確認頁（購物車與電話欄）、訂單狀態頁，頁面寬度皆為 390px 無橫向捲動；1280px 截圖後台訂單、菜單、桌位與營業。依截圖修正：後台卡片顯示已點金額、隱藏還沒點餐的空帳單、聯絡資訊格式、單一文字按鈕置中、設定頁區塊間距與 QR 說明對齊 |
| Compose | 以假值執行 docker compose config --quiet 通過 |
| 靜態整理 | Ruff check / format，前端與 MCP 以 Prettier 整理 |

尚未驗證：實際點擊操作（加入購物車、送出、後台按鈕）的瀏覽器互動測試、與真實 Agenrena 的授權與發訊息、完整 Docker image build 與 Compose 啟動、Runtime 部署。

交付不含 .env、密碼、Agent key、顧客資料、node_modules、virtualenv 或建置產物；`Documents/order` 的 .env、Firebase 服務帳戶、照片均未複製。
