import { useEffect, useRef, useState } from "react";
import QRCode from "qrcode";
import { api, change, client, useData, type AgenrenaState } from "../api";
import { Alert, Modal, useAction } from "../ui";

const POLL_MS = 3000;

// The store is one Agenrena Business Profile. This App is its Vendor; the
// store's owner/admin on Agenrena authorizes it to speak in its conversations.
export function AgenrenaPanel({
  owner,
  storeName,
}: {
  owner: boolean;
  storeName: string;
}) {
  const state = useData<AgenrenaState>("agenrena/"),
    [connecting, setConnecting] = useState(false),
    action = useAction();
  const status = state.data?.status ?? "none";
  const connected = status === "connected";
  const configured = state.data?.configured ?? false;
  return (
    <section className="panel narrow">
      <div className="agenrena-status">
        <div>
          <strong>Agenrena</strong>
          <small>
            {state.isPending
              ? "載入中…"
              : !configured
                ? "此部署尚未設定 Agenrena 憑證"
                : connected
                  ? `已連接：${state.data?.business_name || "Agenrena 商家"}`
                  : status === "revoked"
                    ? `授權已失效：${state.data?.business_name || "請重新連接"}`
                    : "尚未連接"}
          </small>
        </div>
        {owner && configured && (
          <button
            className={connected ? "quiet" : "primary"}
            disabled={action.busy}
            onClick={() => {
              if (!connected) setConnecting(true);
              else if (
                window.confirm(
                  "中斷與 Agenrena 的連接？顧客將不再於 Agenrena 對話收到進度通知。",
                )
              )
                void action.run(() =>
                  change("agenrena/disconnect/", "POST", {}),
                );
            }}
          >
            {connected
              ? "中斷連接"
              : status === "revoked"
                ? "重新連接"
                : "連接"}
          </button>
        )}
        <Alert message={state.error?.message || action.error} />
      </div>
      <p className="muted">
        連接後，業務進度（例如訂單或預約）會送進顧客與這間店的 Agenrena 對話。
      </p>
      {connecting && (
        <ConnectDialog
          storeName={storeName}
          close={() => setConnecting(false)}
        />
      )}
    </section>
  );
}

function ConnectDialog({
  storeName,
  close,
}: {
  storeName: string;
  close: () => void;
}) {
  const [link, setLink] = useState<{
      url: string;
      qr: string;
      expires: number;
    }>(),
    [outcome, setOutcome] = useState<"waiting" | "connected" | "expired">(
      "waiting",
    ),
    [problem, setProblem] = useState(""),
    [name, setName] = useState(""),
    [now, setNow] = useState(Date.now()),
    action = useAction(),
    started = useRef(false),
    polling = useRef(false);

  const start = () =>
    action.run(async () => {
      setProblem("");
      setOutcome("waiting");
      setLink(undefined);
      const result = await api<{ authorize_url: string; expires_at: string }>(
        "agenrena/connect/",
        "POST",
        {},
      );
      setLink({
        url: result.authorize_url,
        qr: await QRCode.toDataURL(result.authorize_url, {
          margin: 1,
          width: 240,
        }),
        expires: Date.parse(result.expires_at),
      });
    });

  useEffect(() => {
    // One consent session per opening; the server keeps only the latest one.
    if (started.current) return;
    started.current = true;
    void start();
  });

  useEffect(() => {
    if (!link || outcome !== "waiting") return;
    const timer = window.setInterval(() => {
      setNow(Date.now());
      if (polling.current) return;
      polling.current = true;
      api<AgenrenaState>("agenrena/check/", "POST", {})
        .then((state) => {
          if (state.status === "connected") {
            setName(state.business_name ?? "");
            setOutcome("connected");
            void client.invalidateQueries({ queryKey: ["agenrena/"] });
          } else if (state.status === "expired" || state.status === "none") {
            setOutcome("expired");
          }
        })
        .catch((error: Error) => {
          // For example: this Agenrena business already serves another store.
          setProblem(error.message);
          setOutcome("expired");
          void client.invalidateQueries({ queryKey: ["agenrena/"] });
        })
        .finally(() => {
          polling.current = false;
        });
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [link, outcome]);

  const seconds = link
    ? Math.max(0, Math.round((link.expires - now) / 1000))
    : 0;
  return (
    <Modal title="連接 Agenrena" close={close}>
      {outcome === "connected" ? (
        <>
          <p className="success">
            已連接「{name || "Agenrena 商家"}」。顧客會在 Agenrena
            對話裡收到進度通知。
          </p>
          <button className="primary" onClick={close}>
            完成
          </button>
        </>
      ) : (
        <>
          <p>
            用 Agenrena App 掃描，並切換成<strong>「{storeName}」</strong>在
            Agenrena 上的商家身分後按同意。一間店對應一個 Agenrena 商家。
          </p>
          {link && outcome === "waiting" && (
            <div className="agenrena-qr">
              <img src={link.qr} alt="Agenrena 授權 QR code" />
              <small>
                {seconds > 0
                  ? `連結 ${seconds} 秒後失效，只能使用一次。`
                  : "連結已過期。"}
              </small>
              <a href={link.url} target="_blank" rel="noreferrer">
                在這台裝置開啟連結
              </a>
            </div>
          )}
          {outcome === "expired" && !problem && (
            <p>這個連結已過期或未完成授權。</p>
          )}
          <Alert message={action.error || problem} />
          <div className="actions">
            {(outcome === "expired" ||
              action.error ||
              (link && seconds === 0)) && (
              <button
                className="primary"
                disabled={action.busy}
                onClick={() => void start()}
              >
                重新產生連結
              </button>
            )}
            <button className="quiet" onClick={close}>
              取消
            </button>
          </div>
        </>
      )}
    </Modal>
  );
}
