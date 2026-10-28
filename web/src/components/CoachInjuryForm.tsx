import type { ReactNode } from "react";
import { WarningOctagon } from "@phosphor-icons/react";
import { injuryReady, choiceLabel, injurySummary } from "../lib/coachChatUi.ts";
import { useCoachChat } from "../state/CoachChatContext.tsx";

const BODY_PARTS = [
  "膝蓋 (Knee)",
  "阿基里斯腱 (Achilles)",
  "足底筋膜 (Plantar)",
  "小腿脛骨 (Shin Splints)",
  "大腿後側 (Hamstring)",
  "髖關節 (Hip)",
];

const SEVERITIES = ["輕微 (Mild)", "中度 (Moderate)", "嚴重 (Severe)"];

/** 身體回報 inside the coach: unlike the 身體回報 page it hands what you pick
 *  to this conversation, and the answer comes back here. */
export function CoachInjuryForm({ en }: { en: boolean }) {
  const { injury, setInjury, submitTriage } = useCoachChat();
  const ready = injuryReady(injury);
  return (
    <div className="cc-injury">
      <fieldset className="cc-fieldset">
        <legend className="cc-legend">{en ? "Where does it feel off?" : "哪裡覺得不舒服？"}</legend>
        <div className="cc-choices">
          {BODY_PARTS.map((part) => (
            <Choice
              key={part}
              selected={injury.bodyPart === part}
              onClick={() => setInjury((current) => ({ ...current, bodyPart: part }))}
            >
              {choiceLabel(part, en)}
            </Choice>
          ))}
        </div>
      </fieldset>

      <fieldset className="cc-fieldset">
        <legend className="cc-legend">{en ? "How bad is it?" : "大概多嚴重？"}</legend>
        <div className="cc-choices cc-choices--even">
          {SEVERITIES.map((level) => (
            <Choice
              key={level}
              selected={injury.severity === level}
              onClick={() => setInjury((current) => ({ ...current, severity: level }))}
            >
              {choiceLabel(level, en)}
            </Choice>
          ))}
        </div>
      </fieldset>

      <fieldset className="cc-fieldset">
        <legend className="cc-legend cc-legend--critical">
          <WarningOctagon size={16} weight="bold" aria-hidden="true" />
          {en ? "Warning signs" : "需要特別留意的徵兆"}
        </legend>
        <label className="cc-check">
          <input
            type="checkbox"
            checked={injury.bonePain}
            onChange={(event) =>
              setInjury((current) => ({ ...current, bonePain: event.target.checked }))
            }
          />
          <span>{en ? "Pinpoint bone tenderness that gets clearly worse when you land or bear weight" : "局部骨頭壓痛，踩踏或負重時明顯加劇"}</span>
        </label>
        <label className="cc-check">
          <input
            type="checkbox"
            checked={injury.chestPain}
            onChange={(event) =>
              setInjury((current) => ({ ...current, chestPain: event.target.checked }))
            }
          />
          <span>{en ? "Chest tightness, unusual difficulty breathing or confusion while exercising" : "運動中胸悶、呼吸異常困難或意識混亂"}</span>
        </label>
      </fieldset>

      <label className="cc-fieldset">
        <span className="cc-legend">{en ? "Anything else?" : "還想補充什麼？"}</span>
        <textarea
          className="input cc-note"
          value={injury.note}
          onChange={(event) => setInjury((current) => ({ ...current, note: event.target.value }))}
          placeholder={en ? "e.g. the lower edge of my knee felt stiff after a long run, a little sore on stairs…" : "例如：跑完長距離後膝蓋下緣卡卡的，上下樓梯有點不適…"}
        />
      </label>

      <div className="cc-triage-foot">
        <p className="cc-injury-summary" aria-live="polite">
          {injurySummary(injury, en)}
        </p>
        <p className="cc-injury-next">
          {en
            ? "Sending takes you back to Ask, where your coach replies. Nothing goes to your own coach unless you choose to send it."
            : "送出後會回到「問教練」，由健康教練回覆；除非你自己按「傳給教練」，否則不會傳給你的教練。"}
        </p>
        <button
          type="button"
          className={`btn btn-block cc-triage ${ready ? "btn-primary" : "btn-secondary"}`}
          disabled={!ready}
          onClick={submitTriage}
        >
          {en ? "Ask the coach about this" : "請教練看看"}
        </button>
      </div>
    </div>
  );
}

function Choice({
  selected,
  onClick,
  children,
}: {
  selected: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button type="button" className="cc-choice" aria-pressed={selected} onClick={onClick}>
      {children}
    </button>
  );
}

