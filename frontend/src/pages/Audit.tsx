import { useState } from "react";
import { useData, type Audit, type Page } from "../api";
import { Alert, Pages } from "../ui";
import { Heading } from "../Heading";

const actionNames: Record<string, string> = {
  "business.updated": "更新商家資料",
  "member.created": "新增成員",
  "member.updated": "更新成員",
  "agent.key_created": "建立 Agent 金鑰",
  "agent.key_revoked": "撤銷 Agent 金鑰",
  "account.login": "登入",
  "account.logout": "登出",
  "account.password_changed": "更改密碼",
  "owner.initialized": "建立首位擁有者",
  "customer.profile_read": "查詢顧客身分",
  "customer.profile_updated": "更新顧客名稱",
  "business.read": "查詢商家資料",
  "order.confirmed": "接單",
  "order.rejected": "拒單",
  "order.completed": "完成餐點",
  "order.cancelled": "取消訂單",
  "order.amended": "修改訂單",
  "order.tab_closed": "結帳／關帳",
  "order.draft_created": "建立確認連結",
  "order.listed": "查詢自己的訂單",
  "shop.read": "查詢店家資訊",
  "menu.read": "查詢菜單",
  "category.created": "新增分類",
  "category.updated": "更新分類",
  "menuitem.created": "新增餐點",
  "menuitem.updated": "更新餐點",
  "table.created": "新增桌位",
  "table.updated": "更新桌位",
  "ordering.settings_updated": "更新接單設定",
  "ordering.hours_updated": "更新營業時間",
  "ordering.paused": "暫停接單",
  "ordering.resumed": "恢復接單",
  "optiongroup.created": "新增選項群組",
  "optiongroup.updated": "更新選項群組",
  "option.updated": "切換選項供應",
  "agenrena.connect_started": "開始連接 Agenrena",
  "agenrena.connected": "連接 Agenrena",
  "agenrena.disconnected": "中斷 Agenrena 連接",
  "agenrena.message_sent": "送出 Agenrena 通知",
  "agenrena.message_failed": "Agenrena 通知未送達",
};
const actorNames: Record<string, string> = {
  agent: "Agent",
  human: "成員",
  system: "系統",
};
export function AuditPage({ timezone }: { timezone: string }) {
  const [page, setPage] = useState(1),
    rows = useData<Page<Audit>>(`audit/?page=${page}`);
  return (
    <>
      <Heading
        title="操作紀錄"
        description={`查看成員的變更，以及 Agent 代表顧客執行的操作。時間以 ${timezone} 顯示。`}
      />
      <Alert message={rows.error?.message} />
      {rows.isPending && <p>載入中…</p>}
      <section className="panel table-wrap">
        <table>
          <thead>
            <tr>
              <th>時間</th>
              <th>操作者</th>
              <th>操作</th>
              <th>紀錄</th>
            </tr>
          </thead>
          <tbody>
            {rows.data?.results.map((e) => (
              <tr key={e.id}>
                <td className="nowrap">
                  {new Date(e.created_at).toLocaleString("zh-TW", {
                    timeZone: timezone,
                    dateStyle: "medium",
                    timeStyle: "short",
                  })}
                </td>
                <td>
                  <strong>{e.actor_label}</strong>
                  <small>{actorNames[e.actor_type] ?? e.actor_type}</small>
                </td>
                <td>{actionNames[e.action] ?? e.action}</td>
                <td>
                  <details>
                    <summary>查看</summary>
                    <small>
                      對象：{e.target_type || "—"} {e.target_id}
                    </small>
                    {e.customer_id && <small>顧客：{e.customer_id}</small>}
                    {e.detail.fields && (
                      <small>變更欄位：{e.detail.fields.join("、")}</small>
                    )}
                    {e.detail.error && <small>原因：{e.detail.error}</small>}
                  </details>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.data?.count === 0 && <p className="empty">尚無操作紀錄。</p>}
        {rows.data && (
          <Pages page={page} pages={rows.data.pages} set={setPage} />
        )}
      </section>
    </>
  );
}
