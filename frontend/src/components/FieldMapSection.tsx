import { App, Button, Checkbox, Select } from "antd";
import { useState } from "react";

import {
  type BitrixSchema,
  type FieldMap,
  type FieldTarget,
  useBitrixSchema,
  useSaveFieldMap,
} from "@/api/integrations";

// Раздел сопоставления пользовательских полей Битрикс24 с полями регламента.
// Пользователь загружает реальные поля/стадии из своего портала и выбирает,
// какое поле Битрикс соответствует «причине отказа», «типу клиента» и т.д.
export function FieldMapSection({
  targets,
  initialMaps,
}: {
  targets: FieldTarget[];
  initialMaps: Record<"box" | "cloud", FieldMap>;
}) {
  const [source, setSource] = useState<"box" | "cloud">("box");
  const schema = useBitrixSchema(source);
  const save = useSaveFieldMap();
  const { message } = App.useApp();

  const [drafts, setDrafts] = useState(initialMaps);
  const fields = drafts[source].fields ?? {};
  const required = new Set(drafts[source].required ?? []);
  const [loaded, setLoaded] = useState<BitrixSchema | null>(null);

  const onLoad = async () => {
    try {
      const res = await schema.mutateAsync();
      if (!res.ok) {
        message.error(`Не удалось загрузить поля из Битрикс24: ${res.error ?? "ошибка"}`);
        return;
      }
      setLoaded(res);
      if (!res.fields.length) message.warning("Битрикс вернул пустой список полей");
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const onSave = async () => {
    try {
      // Отправляем только заполненные сопоставления; required — из заполненных.
      const cleanFields: Record<string, string> = {};
      for (const [k, v] of Object.entries(fields)) if (v) cleanFields[k] = v;
      const cleanReq = [...required].filter((k) => cleanFields[k]);
      await save.mutateAsync({ source, fields: cleanFields, required: cleanReq });
      setDrafts((prev) => ({ ...prev, [source]: { fields: cleanFields, required: cleanReq } }));
      message.success("Сопоставление полей сохранено");
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const options = [
    { value: "", label: "— не сопоставлено —" },
    ...(loaded?.fields ?? []).map((f) => ({ value: f.code, label: `${f.title} · ${f.code}` })),
  ];
  const toggleReq = (key: string, on: boolean) => {
      const next = new Set(required);
      if (on) next.add(key);
      else next.delete(key);
      setDrafts((prev) => ({ ...prev, [source]: { ...prev[source], required: [...next] } }));
  };

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="card-h">
        <div>
          <h3>Поля и этапы Битрикс24</h3>
          <span className="sub">отдельное сопоставление для каждого портала</span>
        </div>
        <div style={{ display: "flex", gap: 8 }}><Select value={source} options={[{ value: "box", label: "Коробочный Bitrix24" }, { value: "cloud", label: "Облачный Bitrix24" }]} onChange={(value) => { setSource(value); setLoaded(null); }} /><Button size="small" onClick={onLoad} loading={schema.isPending}>Загрузить поля</Button></div>
      </div>
      <div className="card-p">
        {loaded && loaded.stages.length ? (
          <div className="fmap-stages">
            <span className="fmap-stages-label">Этапы вашей воронки:</span>
            {loaded.stages.map((s) => (
              <span key={s.id} className="intg-src-chip">{s.name}</span>
            ))}
          </div>
        ) : null}

        {!loaded ? (
          <p className="intg-source-note">
            Нажмите «Загрузить из Битрикс24», чтобы увидеть поля и стадии вашего портала.
            Стандартные поля (телефон, источник, сумма, UTM, этап, менеджер) сопоставляются
            автоматически — здесь настраиваются только пользовательские поля.
          </p>
        ) : (
          <>
            <div className="fmap-grid">
              {targets.map((t) => (
                <div key={t.key} className="fmap-row">
                  <div className="fmap-target">
                    <b>{t.label}</b>
                    <span>{t.hint}</span>
                  </div>
                  <Select
                    className="fmap-select"
                    value={fields[t.key] ?? ""}
                    options={options}
                    showSearch
                    optionFilterProp="label"
                    onChange={(v) => setDrafts((prev) => ({ ...prev, [source]: { ...prev[source], fields: { ...prev[source].fields, [t.key]: v } } }))}
                  />
                  <Checkbox
                    checked={required.has(t.key)}
                    disabled={!fields[t.key]}
                    onChange={(e) => toggleReq(t.key, e.target.checked)}
                  >
                    обязательное
                  </Checkbox>
                </div>
              ))}
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 14 }}>
              <Button type="primary" onClick={onSave} loading={save.isPending}>
                Сохранить сопоставление
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
