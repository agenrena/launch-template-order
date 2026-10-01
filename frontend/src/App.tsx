import { useEffect, useState } from "react";
import { api, client, useData, type User, type Business } from "./api";
import { Alert, Field, Form, text, useAction } from "./ui";
import { roleName } from "./labels";
import { Overview } from "./pages/Overview";
import { BusinessPage } from "./pages/Business";
import { Members } from "./pages/Members";
import { Agents } from "./pages/Agents";
import { AuditPage } from "./pages/Audit";
import { Account } from "./pages/Account";
import { Icon } from "./icons";
import { Orders } from "./ordering/Orders";
import { MenuAdmin } from "./ordering/MenuAdmin";
import { Setup } from "./ordering/Setup";

export function App() {
  const session = useData<{
    user: User | null;
    setup: boolean;
    software_name: string;
  }>("session/");
  const softwareName = session.data?.software_name?.trim() || "Order";
  useEffect(() => {
    document.title = softwareName;
  }, [softwareName]);
  if (session.isPending)
    return <main className="loading">正在載入工作空間…</main>;
  if (session.error)
    return (
      <main className="login">
        <h1>暫時無法連線</h1>
        <Alert message={session.error.message} />
        <button onClick={() => void session.refetch()}>重新連線</button>
      </main>
    );
  if (!session.data.user)
    return (
      <Entry
        setup={session.data.setup}
        done={() => session.refetch()}
        softwareName={softwareName}
      />
    );
  return <Console user={session.data.user} softwareName={softwareName} />;
}
function Entry({
  setup,
  done,
  softwareName,
}: {
  setup: boolean;
  softwareName: string;
  done: () => Promise<unknown>;
}) {
  const action = useAction();
  const submit = (path: string, d: FormData) =>
    action.run(async () => {
      const password = String(d.get("password"));
      if (setup && password !== String(d.get("confirm")))
        throw new Error("兩次輸入的密碼不同。");
      await api(path, "POST", { username: text(d, "username"), password });
      client.clear();
      await done();
    });
  return (
    <div className="login-shell">
      <aside className="login-story">
        <div className="wordmark">{softwareName}</div>
        <div>
          <p className="eyebrow">YOUR BUSINESS, YOUR WAY</p>
          <h1>
            從你的生意，
            <br />
            開始。
          </h1>
          <p>
            一個屬於你的工作空間。
            <br />
            管理商家資料與團隊，讓服務從這裡展開。
          </p>
        </div>
        <small>Powered by Agenrena</small>
      </aside>
      <main className="login">
        {setup ? (
          <>
            <p className="eyebrow">FIRST TIME</p>
            <h1>建立擁有者帳號</h1>
            <p className="muted">
              這是這間店的第一個帳號，之後用它登入、管理團隊與 Agent。
            </p>
            <Form busy={action.busy} onSubmit={(d) => submit("setup/", d)}>
              <Field label="帳號">
                <input
                  name="username"
                  autoComplete="username"
                  required
                  autoFocus
                />
              </Field>
              <Field label="密碼">
                <input
                  name="password"
                  type="password"
                  autoComplete="new-password"
                  required
                />
              </Field>
              <Field label="再輸入一次密碼">
                <input
                  name="confirm"
                  type="password"
                  autoComplete="new-password"
                  required
                />
              </Field>
              <Alert message={action.error} />
              <button className="primary wide">
                {action.busy ? "建立中…" : "建立並進入工作空間 →"}
              </button>
            </Form>
          </>
        ) : (
          <>
            <p className="eyebrow">WELCOME BACK</p>
            <h1>登入商家後台</h1>
            <p className="muted">使用這個商家的帳號與密碼。</p>
            <Form busy={action.busy} onSubmit={(d) => submit("login/", d)}>
              <Field label="帳號">
                <input
                  name="username"
                  autoComplete="username"
                  required
                  autoFocus
                />
              </Field>
              <Field label="密碼">
                <input
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  required
                />
              </Field>
              <Alert message={action.error} />
              <button className="primary wide">
                {action.busy ? "登入中…" : "登入工作空間 →"}
              </button>
            </Form>
            <p className="login-help">
              需要帳號或重設密碼？請聯絡這個商家的擁有者。
            </p>
          </>
        )}
      </main>
    </div>
  );
}
function Console({ user, softwareName }: { user: User; softwareName: string }) {
  const [tab, setTab] = useState("orders"),
    business = useData<Business>("business/"),
    action = useAction();
  const owner = user.role === "owner";
  useEffect(() => {
    if (!owner && ["members", "agents"].includes(tab)) setTab("overview");
  }, [owner, tab]);
  const nav = [
    ["orders", "訂單"],
    ["menu", "菜單"],
    ["setup", "桌位與營業"],
    ["overview", "總覽"],
    ["business", "商家資料"],
    ...(owner
      ? [
          ["members", "團隊成員"],
          ["agents", "Agent 連接"],
        ]
      : []),
    ["audit", "操作紀錄"],
    ["account", "我的帳號"],
  ];
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="wordmark">{softwareName}</div>
        <div className="workspace">
          <span className="tile">{(business.data?.name || "商")[0]}</span>
          <div>
            <strong>{business.data?.name ?? "商家工作空間"}</strong>
            <small>獨立商家 App</small>
          </div>
        </div>
        <p className="nav-label">工作空間</p>
        <nav>
          {nav.map(([key, label]) => (
            <button
              key={key}
              aria-current={tab === key ? "page" : undefined}
              onClick={() => setTab(key)}
            >
              <Icon name={key} />
              {label}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span className="avatar">{(user.name || user.username)[0]}</span>
          <div>
            <strong>{user.name || user.username}</strong>
            <small>{roleName(user.role)}</small>
          </div>
          <button
            className="quiet"
            disabled={action.busy}
            onClick={() =>
              void action.run(async () => {
                await api("logout/", "POST", {});
                client.clear();
                window.location.reload();
              })
            }
          >
            登出
          </button>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <span>
            工作空間 / <strong>{nav.find((n) => n[0] === tab)?.[1]}</strong>
          </span>
          <span className="badge brand">{roleName(user.role)}</span>
        </header>
        <main className="content">
          <Alert message={action.error || business.error?.message} />
          {tab === "overview" ? (
            <Overview business={business.data} go={setTab} owner={owner} />
          ) : tab === "business" ? (
            business.data && (
              <BusinessPage business={business.data} owner={owner} />
            )
          ) : tab === "members" && owner ? (
            <Members />
          ) : tab === "agents" && owner ? (
            <Agents />
          ) : tab === "audit" ? (
            <AuditPage timezone={business.data?.timezone ?? "Asia/Taipei"} />
          ) : tab === "account" ? (
            <Account user={user} />
          ) : tab === "orders" ? (
            <Orders timezone={business.data?.timezone ?? "Asia/Taipei"} />
          ) : tab === "menu" ? (
            <MenuAdmin />
          ) : tab === "setup" ? (
            <Setup />
          ) : null}
        </main>
        <footer>Powered by Agenrena</footer>
      </div>
    </div>
  );
}
