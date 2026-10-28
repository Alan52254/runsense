/** The four things worth asking when the thread is empty, each built from the
 *  signed-in Athlete's own figures, and the record each one draws on. Without
 *  a figure the card asks the question without it; nothing is invented. */

export interface PromptInputs {
  en: boolean;
  /** formatted ACWR, or "—" when there is not enough observation */
  loadRatio: string;
  temperatureC: number | null;
  humidityPct: number | null;
  report: { bodyPart: string; severityBand: string } | null;
}

export interface OpeningCardText {
  prompt: string;
  source: string;
}

export function openingPrompts(input: PromptInputs): OpeningCardText[] {
  const { en, loadRatio, temperatureC, humidityPct, report } = input;
  const hasRatio = loadRatio !== "—";
  const hasWeather = temperatureC !== null && humidityPct !== null;
  if (en) {
    return [
      {
        prompt: hasRatio
          ? `My current load ratio is ${loadRatio}. What should I pay attention to today?`
          : "What should I run today given my recent records?",
        source: "From your training records",
      },
      {
        prompt: hasWeather
          ? `It is ${Math.round(temperatureC)}°C and ${humidityPct}% humidity — how should I adjust my pace?`
          : "How should I adjust my pace for the current weather?",
        source: "From today's conditions",
      },
      { prompt: "I only have 30 minutes today.", source: "Against today's plan" },
      {
        prompt: report
          ? `My latest report is ${report.bodyPart} (${report.severityBand}). What should I do next?`
          : "Does my latest body report mean I should adjust today's training?",
        source: "From your latest body report",
      },
    ];
  }
  return [
    {
      prompt: hasRatio
        ? `我目前 ACWR 負荷比是 ${loadRatio}，今天訓練要注意什麼？`
        : "依我近期紀錄，今天訓練要注意什麼？",
      source: "來自你的訓練紀錄",
    },
    {
      prompt: hasWeather
        ? `今天 ${Math.round(temperatureC)}°C、濕度 ${humidityPct}%，配速要怎麼調整？`
        : "依當前天候，配速要怎麼調整？",
      source: "來自目前天候",
    },
    { prompt: "我今天只有 30 分鐘。", source: "對照你今天的課表" },
    {
      prompt: report
        ? `我最近回報 ${report.bodyPart}（${report.severityBand}），下一步該怎麼做？`
        : "依最近一次身體回報，今天需要調整訓練嗎？",
      source: "來自最近一次身體回報",
    },
  ];
}
