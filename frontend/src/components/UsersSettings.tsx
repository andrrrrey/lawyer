import { Alert, App, Button, Input, Modal, Popconfirm, Select, Switch, Table, Tag } from "antd";
import { useState } from "react";

import type { BusinessSettings } from "@/api/businessSettings";
import { type AppUserPayload, type AppUserRow, type UserRole, useDeleteUser, useSaveUser, useUsers } from "@/api/users";

const ROLE_LABEL: Record<UserRole, string> = {
  owner: "Собственник", head: "Руководитель", manager: "Менеджер",
};

const emptyUser = (): AppUserPayload => ({
  login: "", password: "", role: "manager", employee_key: "", department_key: "", enabled: true,
});

export function UsersSettings({ settings }: { settings: BusinessSettings }) {
  const query = useUsers();
  const save = useSaveUser();
  const remove = useDeleteUser();
  const { message } = App.useApp();
  const [open, setOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | undefined>();
  const [draft, setDraft] = useState<AppUserPayload>(emptyUser());

  const edit = (row?: AppUserRow) => {
    setEditingId(row?.id);
    setDraft(row ? { ...row, password: "" } : emptyUser());
    setOpen(true);
  };
  const submit = async () => {
    try {
      await save.mutateAsync({ id: editingId, payload: draft });
      message.success(editingId ? "Пользователь обновлён" : "Пользователь создан");
      setOpen(false);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "Не удалось сохранить пользователя");
    }
  };

  return (
    <div className="card">
      <div className="card-h">
        <div><h3>Пользователи и роли</h3><span className="sub">доступ к данным и разделам Lawyer</span></div>
        <Button type="primary" onClick={() => edit()}>Добавить пользователя</Button>
      </div>
      <div className="card-p">
        <Alert type="info" showIcon style={{ marginBottom: 14 }} message="Основная учётная запись администратора всегда имеет роль собственника" description="Менеджер видит только свои сделки и не видит суммы, расходы и ROMI. Руководителю доступны рабочие и финансовые отчёты, но недоступны настройки и интеграции." />
        <Table<AppUserRow> rowKey="id" loading={query.isLoading} dataSource={query.data ?? []} pagination={false} columns={[
          { title: "Логин", dataIndex: "login" },
          { title: "Роль", dataIndex: "role", render: (value: UserRole) => <Tag>{ROLE_LABEL[value]}</Tag> },
          { title: "Сотрудник", dataIndex: "employee_key", render: (value: string) => settings.employees.find((x) => x.key === value)?.name ?? "—" },
          { title: "Отдел", dataIndex: "department_key", render: (value: string) => settings.departments.find((x) => x.key === value)?.name ?? "—" },
          { title: "Статус", dataIndex: "enabled", render: (value: boolean) => <Tag color={value ? "green" : "default"}>{value ? "Активен" : "Отключён"}</Tag> },
          { title: "", render: (_, row) => <div style={{ display: "flex", gap: 8 }}><Button size="small" onClick={() => edit(row)}>Изменить</Button><Popconfirm title="Удалить пользователя?" onConfirm={() => remove.mutateAsync(row.id)} okText="Удалить" cancelText="Отмена"><Button size="small" danger>Удалить</Button></Popconfirm></div> },
        ]} />
      </div>
      <Modal title={editingId ? "Изменить пользователя" : "Новый пользователь"} open={open} confirmLoading={save.isPending} okText="Сохранить" cancelText="Отмена" onCancel={() => setOpen(false)} onOk={submit} okButtonProps={{ disabled: !draft.login.trim() || (!editingId && draft.password.length < 8) || (draft.role === "manager" && !draft.employee_key) || (draft.role === "head" && !draft.department_key) }}>
        <div className="field"><label>Логин</label><Input value={draft.login} onChange={(e) => setDraft((x) => ({ ...x, login: e.target.value }))} /></div>
        <div className="field"><label>{editingId ? "Новый пароль (необязательно)" : "Пароль — минимум 8 символов"}</label><Input.Password value={draft.password} onChange={(e) => setDraft((x) => ({ ...x, password: e.target.value }))} /></div>
        <div className="field"><label>Роль</label><Select style={{ width: "100%" }} value={draft.role} options={Object.entries(ROLE_LABEL).map(([value, label]) => ({ value, label }))} onChange={(role: UserRole) => setDraft((x) => ({ ...x, role }))} /></div>
        {draft.role === "manager" ? <div className="field"><label>Сотрудник</label><Select allowClear style={{ width: "100%" }} value={draft.employee_key || undefined} options={settings.employees.filter((x) => x.enabled).map((x) => ({ value: x.key, label: x.name }))} onChange={(value) => setDraft((x) => ({ ...x, employee_key: value ?? "" }))} /></div> : null}
        {draft.role === "head" ? <div className="field"><label>Отдел</label><Select allowClear style={{ width: "100%" }} value={draft.department_key || undefined} options={settings.departments.filter((x) => x.enabled).map((x) => ({ value: x.key, label: x.name }))} onChange={(value) => setDraft((x) => ({ ...x, department_key: value ?? "" }))} /></div> : null}
        <div className="field"><label>Доступ разрешён</label><Switch checked={draft.enabled} onChange={(enabled) => setDraft((x) => ({ ...x, enabled }))} /></div>
      </Modal>
    </div>
  );
}
