// Shared, always-visible safety copy for the backend Injury Guidance flow.
// No React Native import so this remains testable with node --test.

export const HEALTH_COACH_DISCLAIMER: Record<'zh-TW' | 'en', string> = {
  'zh-TW':
    '健康教練內容僅供一般資訊與自我照護參考，不能取代醫師或其他合格醫療專業人員的診斷與治療。若有持續、嚴重或緊急症狀，請立即尋求專業協助。',
  en:
    'Health-coach content is general educational and self-care information, not a substitute for diagnosis or treatment by a qualified clinician. Seek professional help for persistent, severe, or emergency symptoms.',
};
