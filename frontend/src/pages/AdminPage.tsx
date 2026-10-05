import { App, Button, Modal, Select, Spin } from "antd";
import { type ReactNode, useEffect, useState } from "react";

import {
  type RegulationConfig,
  useHistory,
  useRegulation,
  useRollback,
  useSaveRegulation,
} from "@/api/admin";
import { EmptyState } from "@/components/EmptyState";
import { CheckIcon } from "@/components/icons";

/* --- Мелкие контролы в стиле прототипа --- */
function Stepper({ value, unit, onStep }: { value: number; unit: string; onStep: (d: number) => void }) {
  return (
    <div className="stepper">
      <button onClick={() => onStep(-1)}>−</button>
      <input value={value} readOnly />
      <button onClick={() => onStep(1)}>+</button>
      <span className="unit">{unit}</span>
    </div>
  );
}

function Toggle({ checked, onChange }: { checked: boolean; onChange: () => void }) {
  return (
    <label className="sw">
      <input type="checkbox" checked={checked} onChange={onChange} />
      <span className="tr" />
    </label>
  );
}

function SetRow({ title, sub, children }: { title: string; sub: string; children: ReactNode }) {
  return (
    <div className="setrow">
      <div className="st">
        <b>{title}</b>
        <span>{sub}</span>
      </div>
      {children}
    </div>
  );
}

export default function AdminPage() {
  const reg = useRegulation();
  const history = useHistory();
  const save = useSaveRegulation();
  const rollback = useRollback();
  const { message } = App.useApp();

  const [cfg, setCfg] = useState<RegulationConfig | null>(null);
  useEffect(() => {
    if (reg.data) setCfg(structuredClone(reg.data));
  }, [reg.data]);

  if (!cfg) {
    return (
      <div style={{ minHeight: "40vh", display: "grid", placeItems: "center" }}>
        <Spin size="large" />
      </div>
    );
  }

  const update = (mut: (c: RegulationConfig) => void) => {
    setCfg((prev) => {
      const next = structuredClone(prev!);
      mut(next);
      return next;
    });
  };

  const changedCount = reg.data ? diffCount(reg.data, cfg) : 0;

  const onSave = () => {
    Modal.confirm({
      title: "Подтвердите изменение регламента",
      content:
        "Часть правок влияет на расчёт нарушений. После сохранения показатели за период " +
        "будут пересчитаны, изменение зафиксируется в истории.",
      okText: "Сохранить и пересчитать",
      cancelText: "Отмена",
      onOk: () =>
        save.mutateAsync(cfg).then((res) => {
          message.success(`Регламент сохранён · изменений: ${res.changes}`);
        }),
    });
  };

  const onReset = () => reg.data && setCfg(structuredClone(reg.data));

  return (
    <>
      <div className="grid admin-grid">
        {/* Пороги по этапам */}
        <div className="card">
          <div className="card-h">
            <h3>Пороги по этапам воронки</h3>
            <span className="sub">норматив реакции</span>
          </div>
          <div className="card-p">
            {cfg.thresholds.map((t, i) => (
              <SetRow key={i} title={t.n} sub={t.s}>
                <Stepper
                  value={t.v}
                  unit={t.u}
                  onStep={(d) => update((c) => { c.thresholds[i].v = Math.max(0, c.thresholds[i].v + d); })}
                />
              </SetRow>
            ))}
          </div>
        </div>

        {/* Правила по задачам */}
        <div className="card">
          <div className="card-h">
            <h3>Правила по задачам</h3>
            <span className="sub">когда отсутствие задачи — нарушение</span>
          </div>
          <div className="card-p">
            {cfg.task_rules.map((r, i) => (
              <SetRow key={i} title={r.n} sub={r.s}>
                <Toggle checked={r.on} onChange={() => update((c) => { c.task_rules[i].on = !c.task_rules[i].on; })} />
              </SetRow>
            ))}
          </div>
        </div>

        {/* Обязательные поля */}
        <div className="card">
          <div className="card-h">
            <h3>Обязательные поля карточки</h3>
            <span className="sub">контроль заполнения</span>
          </div>
          <div className="card-p">
            <div className="chkline">
              {cfg.req_fields.map(([name, on], i) => (
                <div
                  key={i}
                  className={`chk ${on ? "on" : ""}`}
                  onClick={() => update((c) => { c.req_fields[i][1] = c.req_fields[i][1] ? 0 : 1; })}
                >
                  <span className="bx"><CheckIcon /></span>
                  {name}
                </div>
              ))}
            </div>
            <div style={{ borderTop: "1px solid var(--line2)", marginTop: 16, paddingTop: 16 }}>
              <div className="field">
                <label>Правило определения дублей</label>
                <Select
                  className="sel2"
                  style={{ width: "100%" }}
                  value={cfg.dup_rule.value}
                  options={cfg.dup_rule.options.map((o) => ({ value: o, label: o }))}
                  onChange={(v) => update((c) => { c.dup_rule.value = v; })}
                />
              </div>
            </div>
          </div>
        </div>

        {/* Рабочий график */}
        <div className="card">
          <div className="card-h">
            <h3>Рабочий график и календарь</h3>
            <span className="sub">для нормативов в рабочем времени</span>
          </div>
          <div className="card-p">
            <div className="field">
              <label>Рабочие дни</label>
              <div className="days">
                {cfg.schedule.days.map((d, i) => (
                  <div
                    key={i}
                    className={`day ${cfg.schedule.days_on[i] ? "on" : ""}`}
                    onClick={() => update((c) => { c.schedule.days_on[i] = !c.schedule.days_on[i]; })}
                  >
                    {d}
                  </div>
                ))}
              </div>
            </div>
            <SetRow title="Рабочее время" sub="московское время">
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <input
                  className="txt"
                  style={{ width: 76, textAlign: "center" }}
                  value={cfg.schedule.work_from}
                  onChange={(e) => update((c) => { c.schedule.work_from = e.target.value; })}
                />
                <span style={{ color: "var(--faint)" }}>—</span>
                <input
                  className="txt"
                  style={{ width: 76, textAlign: "center" }}
                  value={cfg.schedule.work_to}
                  onChange={(e) => update((c) => { c.schedule.work_to = e.target.value; })}
                />
              </div>
            </SetRow>
            <SetRow title="Производственный календарь РФ" sub="учитывать праздники и переносы">
              <Toggle
                checked={cfg.schedule.production_calendar}
                onChange={() => update((c) => { c.schedule.production_calendar = !c.schedule.production_calendar; })}
              />
            </SetRow>
            <div className="field" style={{ marginTop: 14 }}>
              <label>Дополнительные нерабочие дни и переносы (ГГГГ-ММ-ДД, по одному в строке)</label>
              <textarea className="txt" rows={3} style={{ width: "100%" }} value={(cfg.schedule.holidays ?? []).join("\n")} onChange={(e) => update((c) => { c.schedule.holidays = e.target.value.split("\n").map((v) => v.trim()).filter(Boolean); })} />
            </div>
          </div>
        </div>

        {/* Логика создания задач */}
        <div className="card">
          <div className="card-h">
            <h3>Логика создания задач</h3>
            <span className="sub">триггер · адресат · текст · срок</span>
          </div>
          <div className="card-p">
            <div className="field" style={{ marginBottom: 14 }}>
              <label>Адресат задачи</label>
              <Select
                className="sel2"
                style={{ width: "100%" }}
                value={cfg.task_logic.assignee}
                options={cfg.task_logic.assignee_options.map((o) => ({ value: o, label: o }))}
                onChange={(v) => update((c) => { c.task_logic.assignee = v; })}
              />
            </div>
            <div className="field">
              <label>Шаблон текста задачи</label>
              <textarea
                value={cfg.task_logic.template}
                onChange={(e) => update((c) => { c.task_logic.template = e.target.value; })}
              />
            </div>
          </div>
        </div>

        {/* Оценочные нарушения */}
        <div className="card">
          <div className="card-h">
            <h3>Оценочные нарушения</h3>
            <span className="sub">подсветка без автоклассификации</span>
          </div>
          <div className="card-p">
            <SetRow title="Подсвечивать перевод живой сделки в «Спам»" sub="решение принимает руководитель">
              <Toggle
                checked={cfg.evaluative.highlight_spam}
                onChange={() => update((c) => { c.evaluative.highlight_spam = !c.evaluative.highlight_spam; })}
              />
            </SetRow>
            <SetRow title="Подсвечивать отказ «для чистоты воронки»" sub="подозрительные отказы">
              <Toggle
                checked={cfg.evaluative.highlight_refusal}
                onChange={() => update((c) => { c.evaluative.highlight_refusal = !c.evaluative.highlight_refusal; })}
              />
            </SetRow>
            <SetRow title="Порог «зависшей» сделки" sub="без движения по статусу">
              <Stepper
                value={cfg.evaluative.stuck_days}
                unit="дн."
                onStep={(d) => update((c) => { c.evaluative.stuck_days = Math.max(1, c.evaluative.stuck_days + d); })}
              />
            </SetRow>
          </div>
        </div>
      </div>

      {/* История изменений */}
      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-h">
          <h3>История изменений регламента</h3>
          <span className="sub">кто, когда и что изменил · защита от случайных правок</span>
        </div>
        {history.data && history.data.length === 0 ? (
          <EmptyState
            title="История изменений пуста"
            hint="Записи появятся после первых изменений параметров регламента."
          />
        ) : (
        <div className="tbl-wrap">
          <table className="htable">
            <thead>
              <tr>
                <th>Дата и время</th>
                <th>Пользователь</th>
                <th>Параметр</th>
                <th>Было</th>
                <th>Стало</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {history.data?.map((h) => (
                <tr key={h.id}>
                  <td className="num" style={{ color: "var(--muted)" }}>{h.dt}</td>
                  <td><b>{h.user}</b></td>
                  <td>
                    {h.param}
                    {h.crit ? <span className="crit-dot" title="влияет на расчёт нарушений" /> : null}
                  </td>
                  <td><span className="hist-from">{h.from}</span></td>
                  <td><span className="hist-to">{h.to}</span></td>
                  <td style={{ textAlign: "right" }}>
                    <Button
                      size="small"
                      disabled={!h.can_rollback}
                      loading={rollback.isPending}
                      onClick={() =>
                        rollback.mutate(h.id, {
                          onSuccess: () => message.success(`Значение «${h.param}» восстановлено`),
                          onError: (e) => message.error((e as Error).message),
                        })
                      }
                    >
                      Откатить
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        )}
      </div>

      <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 20 }}>
        <Button onClick={onReset} disabled={changedCount === 0}>Сбросить</Button>
        <Button type="primary" onClick={onSave} loading={save.isPending} disabled={changedCount === 0}>
          Сохранить регламент{changedCount ? ` · ${changedCount}` : ""}
        </Button>
      </div>
    </>
  );
}

// Грубая оценка числа изменений (для активации кнопок).
function diffCount(a: RegulationConfig, b: RegulationConfig): number {
  return JSON.stringify(a) === JSON.stringify(b) ? 0 : 1;
}
