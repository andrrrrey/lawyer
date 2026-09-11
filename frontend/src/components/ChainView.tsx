import type { ChainStep } from "@/api/analytics";

const ARROW =
  '<path d="M9 6l6 6-6 6" stroke-linecap="round" stroke-linejoin="round"/>';

// Цепочка «реклама → визит → сделка → оплата → выручка».
export function ChainView({ steps }: { steps: ChainStep[] }) {
  return (
    <div className="chain">
      {steps.map((s, i) => (
        <div key={i} className="chain-step">
          <div
            className="chain-bar"
            style={{
              background: `linear-gradient(135deg, ${s.color}, ${s.color}dd)`,
              height: `${60 + s.width * 0.9}px`,
              boxShadow: s.glow ? "0 10px 26px -8px rgba(18,183,106,.6)" : undefined,
            }}
          >
            <div className="cn num">{s.display}</div>
            <div className="cl">{s.label}</div>
            <div className="csub">{s.sub}</div>
          </div>
          {i < steps.length - 1 ? (
            <div className="chain-arrow">
              <svg
                fill="none"
                stroke="currentColor"
                strokeWidth={2.5}
                viewBox="0 0 24 24"
                dangerouslySetInnerHTML={{ __html: ARROW }}
              />
            </div>
          ) : null}
          <div className="chain-conv">
            {i === 0 ? "старт" : <>конверсия <b>{s.conversion}%</b></>}
          </div>
        </div>
      ))}
    </div>
  );
}
