import { App, Button, Checkbox, Input, Select, Spin } from "antd";
import { useEffect, useMemo, useState } from "react";

import {
  type CheckResult,
  type YandexConfig,
  useCheckYandex,
  useDiscoverYandexCounters,
  useSaveYandex,
} from "@/api/integrations";

const ENTITIES = [
  { value: "uo", label: "ЮО" },
  { value: "csv", label: "ЦСВ" },
  { value: "urpase", label: "УрПАСЭ" },
];

function uid(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

function cloneConfig(value: YandexConfig): YandexConfig {
  return JSON.parse(JSON.stringify(value)) as YandexConfig;
}

function Result({ value }: { value?: CheckResult }) {
  if (!value) return null;
  const cls = value.status === "ok" ? "ok" : value.status === "error" ? "err" : "idle";
  return (
    <div className={`intg-result ${cls}`}>
      <b>{value.message}</b>{value.detail ? <span> {value.detail}</span> : null}
    </div>
  );
}

export function YandexSettingsSection({ initial }: { initial: YandexConfig }) {
  const { message } = App.useApp();
  const save = useSaveYandex();
  const check = useCheckYandex();
  const discover = useDiscoverYandexCounters();
  const [draft, setDraft] = useState<YandexConfig>(() => cloneConfig(initial));

  useEffect(() => setDraft(cloneConfig(initial)), [initial]);

  const credentials = useMemo(
    () => draft.credentials.map((item) => ({ value: item.id, label: item.name || item.login || item.id })),
    [draft.credentials],
  );
  const authUrl = draft.client_id
    ? `https://oauth.yandex.ru/authorize?response_type=token&client_id=${encodeURIComponent(draft.client_id)}`
    : "";

  const persist = async (): Promise<YandexConfig> => {
    const saved = await save.mutateAsync(draft);
    setDraft(cloneConfig(saved));
    return saved;
  };

  const onCheck = async () => {
    try {
      const saved = await persist();
      const result = await check.mutateAsync();
      setDraft({ ...saved, last_checks: result.results });
      const errors = Object.values(result.results).filter((item) => item.status === "error").length;
      if (errors) message.warning(`Проверка завершена: ошибок ${errors}`);
      else message.success("Все включённые ресурсы Яндекса доступны");
    } catch (error) {
      message.error((error as Error).message);
    }
  };

  const onDiscover = async (credentialId: string) => {
    try {
      await persist();
      const result = await discover.mutateAsync(credentialId);
      if (!result.ok) throw new Error(result.error || "Не удалось получить счётчики");
      const existing = new Set(draft.metrika_counters.map((item) => item.counter_id));
      const added = result.counters.filter((item) => !existing.has(item.counter_id)).map((item) => ({
        id: uid("metrika"),
        name: item.name,
        credential_id: credentialId,
        counter_id: item.counter_id,
        site: item.site,
        legal_entity_key: "",
        enabled: false,
      }));
      setDraft((current) => ({
        ...current,
        metrika_counters: [...current.metrika_counters, ...added],
      }));
      message.success(
        added.length ? `Найдено новых счётчиков: ${added.length}. Выберите юрлицо и включите нужные.` :
          "Все доступные счётчики уже добавлены",
      );
    } catch (error) {
      message.error((error as Error).message);
    }
  };

  const removeCredential = (id: string) => setDraft((current) => ({
    ...current,
    credentials: current.credentials.filter((item) => item.id !== id),
    direct_accounts: current.direct_accounts.filter((item) => item.credential_id !== id),
    metrika_counters: current.metrika_counters.filter((item) => item.credential_id !== id),
  }));

  return (
    <div className="card yandex-settings" style={{ marginBottom: 16 }}>
      <div className="card-h">
        <div>
          <h3>Яндекс Директ и Метрика</h3>
          <span className="sub">одно одобренное приложение · несколько аккаунтов и счётчиков</span>
        </div>
        <div className="yandex-head-actions">
          <Button onClick={onCheck} loading={check.isPending || save.isPending}>Проверить всё</Button>
          <Button type="primary" onClick={() => persist().then(() => message.success("Настройки Яндекса сохранены")).catch((e: Error) => message.error(e.message))} loading={save.isPending}>
            Сохранить
          </Button>
        </div>
      </div>
      <div className="card-p yandex-body">
        <section>
          <h4>1. Одобренное приложение</h4>
          <div className="yandex-app-row">
            <div className="field intg-field">
              <label>Client ID приложения</label>
              <Input value={draft.client_id} placeholder="Client ID одобренного приложения" onChange={(e) => setDraft({ ...draft, client_id: e.target.value })} />
              <span className="intg-hint">Все новые токены должны быть получены через этот Client ID.</span>
            </div>
            <Button href={authUrl || undefined} target="_blank" disabled={!authUrl}>Получить OAuth-токен</Button>
          </div>
        </section>

        <section>
          <div className="yandex-section-head">
            <div><h4>2. OAuth-доступы</h4><span>Добавьте каждого пользователя Яндекса, которому доступны нужные кабинеты или счётчики.</span></div>
            <Button onClick={() => setDraft((current) => ({ ...current, credentials: [...current.credentials, { id: uid("oauth"), name: `OAuth-доступ ${current.credentials.length + 1}`, login: "", token: "", enabled: true }] }))}>Добавить доступ</Button>
          </div>
          <div className="yandex-list">
            {draft.credentials.map((item, index) => (
              <div className="yandex-row credential" key={item.id}>
                <Checkbox checked={item.enabled} onChange={(e) => setDraft((current) => ({ ...current, credentials: current.credentials.map((row) => row.id === item.id ? { ...row, enabled: e.target.checked } : row) }))} />
                <Input value={item.name} placeholder="Название подключения" onChange={(e) => setDraft((current) => ({ ...current, credentials: current.credentials.map((row) => row.id === item.id ? { ...row, name: e.target.value } : row) }))} />
                <Input value={item.login} placeholder="Логин Яндекса (для подписи)" onChange={(e) => setDraft((current) => ({ ...current, credentials: current.credentials.map((row) => row.id === item.id ? { ...row, login: e.target.value } : row) }))} />
                <Input.Password value={item.token} placeholder="OAuth-токен" autoComplete="new-password" onChange={(e) => setDraft((current) => ({ ...current, credentials: current.credentials.map((row) => row.id === item.id ? { ...row, token: e.target.value } : row) }))} />
                <Button onClick={() => onDiscover(item.id)} loading={discover.isPending}>Загрузить счётчики</Button>
                <Button danger onClick={() => removeCredential(item.id)} aria-label={`Удалить OAuth-доступ ${index + 1}`}>Удалить</Button>
              </div>
            ))}
            {!draft.credentials.length ? <div className="yandex-empty">OAuth-доступы ещё не добавлены.</div> : null}
          </div>
        </section>

        <section>
          <div className="yandex-section-head">
            <div><h4>3. Аккаунты Директа</h4><span>Один токен можно использовать для нескольких Client-Login, если у пользователя есть к ним доступ.</span></div>
            <Button disabled={!credentials.length} onClick={() => setDraft((current) => ({ ...current, direct_accounts: [...current.direct_accounts, { id: uid("direct"), name: "Новый кабинет", credential_id: current.credentials[0]?.id || "", client_login: "", legal_entity_key: "", enabled: true }] }))}>Добавить кабинет</Button>
          </div>
          <div className="yandex-list">
            {draft.direct_accounts.map((item) => (
              <div className="yandex-resource" key={item.id}>
                <div className="yandex-row resource">
                  <Checkbox checked={item.enabled} onChange={(e) => setDraft((current) => ({ ...current, direct_accounts: current.direct_accounts.map((row) => row.id === item.id ? { ...row, enabled: e.target.checked } : row) }))} />
                  <Input value={item.name} placeholder="Название" onChange={(e) => setDraft((current) => ({ ...current, direct_accounts: current.direct_accounts.map((row) => row.id === item.id ? { ...row, name: e.target.value } : row) }))} />
                  <Select value={item.credential_id || undefined} placeholder="OAuth-доступ" options={credentials} onChange={(value) => setDraft((current) => ({ ...current, direct_accounts: current.direct_accounts.map((row) => row.id === item.id ? { ...row, credential_id: value } : row) }))} />
                  <Input value={item.client_login} placeholder="Client-Login" onChange={(e) => setDraft((current) => ({ ...current, direct_accounts: current.direct_accounts.map((row) => row.id === item.id ? { ...row, client_login: e.target.value } : row) }))} />
                  <Select value={item.legal_entity_key || undefined} placeholder="Юрлицо" options={ENTITIES} onChange={(value) => setDraft((current) => ({ ...current, direct_accounts: current.direct_accounts.map((row) => row.id === item.id ? { ...row, legal_entity_key: value } : row) }))} />
                  <Button danger onClick={() => setDraft((current) => ({ ...current, direct_accounts: current.direct_accounts.filter((row) => row.id !== item.id) }))}>Удалить</Button>
                </div>
                <Result value={draft.last_checks?.[`direct:${item.id}`]} />
              </div>
            ))}
          </div>
        </section>

        <section>
          <div className="yandex-section-head">
            <div><h4>4. Счётчики Метрики</h4><span>После загрузки доступных счётчиков включите нужные и сопоставьте их с юрлицами.</span></div>
          </div>
          <div className="yandex-list">
            {draft.metrika_counters.map((item) => (
              <div className="yandex-resource" key={item.id}>
                <div className="yandex-row resource">
                  <Checkbox checked={item.enabled} onChange={(e) => setDraft((current) => ({ ...current, metrika_counters: current.metrika_counters.map((row) => row.id === item.id ? { ...row, enabled: e.target.checked } : row) }))} />
                  <Input value={item.name} placeholder="Название счётчика" onChange={(e) => setDraft((current) => ({ ...current, metrika_counters: current.metrika_counters.map((row) => row.id === item.id ? { ...row, name: e.target.value } : row) }))} />
                  <Select value={item.credential_id || undefined} placeholder="OAuth-доступ" options={credentials} onChange={(value) => setDraft((current) => ({ ...current, metrika_counters: current.metrika_counters.map((row) => row.id === item.id ? { ...row, credential_id: value } : row) }))} />
                  <Input value={item.counter_id} placeholder="ID счётчика" onChange={(e) => setDraft((current) => ({ ...current, metrika_counters: current.metrika_counters.map((row) => row.id === item.id ? { ...row, counter_id: e.target.value } : row) }))} />
                  <Select value={item.legal_entity_key || undefined} placeholder="Юрлицо" options={ENTITIES} onChange={(value) => setDraft((current) => ({ ...current, metrika_counters: current.metrika_counters.map((row) => row.id === item.id ? { ...row, legal_entity_key: value } : row) }))} />
                  <Button danger onClick={() => setDraft((current) => ({ ...current, metrika_counters: current.metrika_counters.filter((row) => row.id !== item.id) }))}>Удалить</Button>
                </div>
                {item.site ? <div className="yandex-site">{item.site}</div> : null}
                <Result value={draft.last_checks?.[`metrika:${item.id}`]} />
              </div>
            ))}
            {!draft.metrika_counters.length ? <div className="yandex-empty">Нажмите «Загрузить счётчики» у OAuth-доступа.</div> : null}
          </div>
        </section>
        {(save.isPending || check.isPending || discover.isPending) ? <div className="yandex-working"><Spin size="small" /> Выполняется запрос к Яндексу…</div> : null}
      </div>
    </div>
  );
}
