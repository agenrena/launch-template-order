# 公開顧客點餐頁

給店家的 Agent 或幫忙架設的人照著做。App 在店裡的電腦上執行時，預設只有這台電腦連得到，顧客的手機打不開點餐頁。所以在公開之前：

- 後台「桌位與營業」不產生 QR code（只有在這台電腦上試用的連結）；
- Agent 準備訂單（`create_order_link`）會收到 `not_published`，不會發出顧客打不開的連結。

要讓顧客掃桌上的 QR code、或打開 Agent 傳來的確認連結，就需要一個**固定的 HTTPS 網址**，由它把請求轉到這台電腦。QR code 會印出來貼在桌上，所以網址不能每次重開就變。

## App 提供什麼

設定 `PUBLIC_PORT` 後，App 除了原本的後台（`PORT`，預設 8084）之外，還會在同一台電腦開一個**顧客點餐入口**：

| 入口 | 位址 | 內容 |
|---|---|---|
| 後台 | `http://127.0.0.1:8084` | 全部：後台、建立擁有者、Agent API、MCP、點餐頁 |
| 顧客點餐入口 | `http://127.0.0.1:<PUBLIC_PORT>` | 只有點餐頁：`/`、`/?table=A1`、`/d/…`、`/o/…`，以及它們用的 `/assets/`、`/api/web/` |

在顧客點餐入口上，其他路徑一律回 404，不管 tunnel 怎麼設定，後台和 MCP 都連不到。**tunnel 只能指向顧客點餐入口，絕對不要指向 8084。**

兩個入口預設都只聽 127.0.0.1，所以區域網路上的其他裝置也連不到；對外只能經過你設定的 tunnel。

## 步驟

### 1. 打開顧客點餐入口

在專案的 `.env` 填入：

```sh
PUBLIC_PORT=8085
ORDER_PUBLIC_BASE_URL=https://order.example.com   # 顧客實際打開的網址，換成你的
```

重新執行 `start.command`／`start.bat`，畫面上會多一行：

```text
顧客點餐入口：http://127.0.0.1:8085 → https://order.example.com
```

### 2. 用一個工具把網址轉到這個入口

任何能把「固定的 HTTPS 網址」轉到這台電腦 `http://127.0.0.1:8085` 的工具都可以，由店家決定。以下以 Cloudflare Tunnel 為例。

**Cloudflare Tunnel**（免費；需要 Cloudflare 帳號，以及一個 DNS 放在 Cloudflare 的網域，一年約數百元）

```sh
# 安裝：macOS 用 brew install cloudflared；Windows 用 winget install --id Cloudflare.cloudflared
cloudflared tunnel login                              # 瀏覽器登入 Cloudflare，選這個網域
cloudflared tunnel create my-store                    # 建立 tunnel，記下產生的 ID 與憑證檔路徑
cloudflared tunnel route dns my-store order.example.com
```

建立 `~/.cloudflared/config.yml`（Windows：`%USERPROFILE%\.cloudflared\config.yml`）：

```yaml
tunnel: <tunnel ID>
credentials-file: <上一步產生的 .json 路徑>
ingress:
  - hostname: order.example.com
    service: http://127.0.0.1:8085 # 顧客點餐入口，不是 8084
  - service: http_status:404
```

```sh
cloudflared tunnel run my-store
```

測試沒問題後，依 Cloudflare 的說明用 `cloudflared service install` 讓它開機自動執行。

`cloudflared tunnel --url …` 的快速模式會給一個 `trycloudflare.com` 網址，但每次重開都會變，只適合試用，不要拿來印 QR code。

**其他做法**：Tailscale Funnel（網址是固定的 `*.ts.net`）、店家自己的網域加反向代理（Caddy、nginx）都可以，一樣只轉到 `127.0.0.1:8085`。App 會採用工具帶來的 `X-Forwarded-For` 當作顧客位址，讓「每分鐘最多 30 次點餐操作」按顧客分開計算；如果你的工具不帶這個標頭，全部顧客會共用同一個上限。

### 3. 確認

用手機的**行動網路**（不要連店裡的 Wi-Fi）檢查：

- [ ] `https://order.example.com/` 出現菜單，`/?table=A1` 是內用點餐
- [ ] `https://order.example.com/console/` 與 `/mcp` 都是 404
- [ ] 後台「桌位與營業」出現 QR code，下方寫著的網址是 `https://order.example.com/`
- [ ] 請 Agent 準備一筆訂單：確認連結是 `https://order.example.com/d/…`，在手機上打得開

都沒問題再印 QR code。

## 之後要注意

- 營業時間內，這台電腦、App 和 tunnel 都要開著；電腦睡眠時顧客就點不了餐，請關掉營業時間的自動睡眠。
- QR code 綁著這個網址：網域要記得續約；網址改了就要重印。
- 後台只在這台電腦上用。讓店員的手機或平板也能用屬於客製，見 [客製開發](development.md)。
- App 放在伺服器上（Docker Compose）時整個網站本來就對外，不需要這份設定，只要把 `ORDER_PUBLIC_BASE_URL` 設成正式網址。
