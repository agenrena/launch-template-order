import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { client } from "./api";
import { App } from "./App";
import { DraftPage, MenuPage, StatusPage } from "./customer/Customer";
import "./style.css";
import "./customer/customer.css";

/**
 * The URLs a customer arrives at, and the staff console:
 *
 *   /?table=A1   the code on a table: everyone there shares one bill
 *   /            the code by the counter: takeout
 *   /d/<token>   a cart an Agent prepared, for the customer to confirm
 *   /o/<token>   one order's progress
 *   /console     staff
 */
function Route() {
  const path = window.location.pathname;
  const token = (prefix: string) =>
    decodeURIComponent(path.slice(prefix.length).replace(/\/$/, ""));
  if (path === "/console" || path.startsWith("/console/")) return <App />;
  if (path.startsWith("/d/")) return <DraftPage token={token("/d/")} />;
  if (path.startsWith("/o/")) return <StatusPage token={token("/o/")} />;
  if (path === "/") return <MenuPage />;
  return (
    <main className="customer c-main c-message">
      <h1>找不到這個頁面</h1>
      <a className="c-link" href="/">
        回到菜單
      </a>
    </main>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={client}>
      <Route />
    </QueryClientProvider>
  </React.StrictMode>,
);
