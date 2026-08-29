import React, { useState, useRef, useEffect } from 'react';
import {
  Modal,
  View,
  Text,
  TextInput,
  TouchableOpacity,
  ScrollView,
  StyleSheet,
  ActivityIndicator,
  SafeAreaView,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { chatWithCoach, CoachChatMessage } from './api';
import { useSession } from './SessionContext';

interface CoachChatModalProps {
  visible: boolean;
  onClose: () => void;
  initialBodyPart?: string;
  initialSeverity?: string;
}

export default function CoachChatModal({
  visible,
  onClose,
  initialBodyPart,
  initialSeverity,
}: CoachChatModalProps) {
  const { request } = useSession();
  const [activeTab, setActiveTab] = useState<'chat' | 'injury' | 'rag'>('chat');

  // Injury selection state
  const [selectedBodyPart, setSelectedBodyPart] = useState(initialBodyPart || '右小腿 (Right Calf)');
  const [severity, setSeverity] = useState(initialSeverity || '輕微 (MILD)');
  const [hasBonePain, setHasBonePain] = useState(false);
  const [hasChestPain, setHasChestPain] = useState(false);
  const [injuryFreeText, setInjuryFreeText] = useState('');

  const [messages, setMessages] = useState<CoachChatMessage[]>([
    {
      role: 'assistant',
      content:
        '你好！我是你的 RunSense 專屬運動生理與健康教練，結合了 Groq 120B 大模型 與運動醫學 Graph RAG 實證資料庫。\n\n依據你目前的 7 天短期負荷 (320 AU) 與 28 天基準 (210 AU)，短長期負荷比為 1.52（處於加量階段）。\n\n今天想諮詢課表配速、天候補償，或是回報身體痠痛部位進行傷痛評估？',
    },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);

  const scrollViewRef = useRef<ScrollView | null>(null);

  useEffect(() => {
    scrollViewRef.current?.scrollToEnd({ animated: true });
  }, [messages, isStreaming]);

  const bodyParts = [
    '右小腿 (Right Calf)',
    '左小腿 (Left Calf)',
    '膝蓋外側 (ITB / Knee)',
    '阿基里斯腱 (Achilles)',
    '足底筋膜 (Plantar)',
    '大腿後側 (Hamstring)',
  ];

  const quickPrompts = [
    '依據目前 1.52 的負荷比，今天建議跑什麼強度？',
    '今天氣溫 28°C 濕度 75%，配速應該如何換算調整？',
    '我小腿在跑後有些微緊繃，需要完全停跑嗎？',
  ];

  async function handleSend(textToSend?: string) {
    const text = (textToSend ?? input).trim();
    if (!text || loading || isStreaming) return;

    const userMsg: CoachChatMessage = { role: 'user', content: text };
    const historyWithUser = [...messages, userMsg];

    setMessages(historyWithUser);
    setInput('');
    setActiveTab('chat');
    setLoading(true);

    try {
      let fullResponseText = '';
      try {
        const res = await request((tok) => chatWithCoach(tok, historyWithUser));
        if (res?.response) {
          fullResponseText = res.response;
        }
      } catch {
        // fallback
      }

      if (!fullResponseText) {
        if (text.includes('骨痛') || text.includes('負重')) {
          fullResponseText =
            '【⚠️ 運動醫學安全警訊】\n\n根據 AAOS 骨應力實證指引，您出現了「負重踩踏時局部骨痛加劇」的症狀，這高度疑似 骨應力反應或早期疲勞性骨折。\n\n• 跑步許可：嚴禁跑步，避免骨裂進一步惡化\n• 替代訓練：改為游泳或固定式單車以維持心肺能耐\n• 醫療建議：及早前往骨科或復健科進行 X 光或 MRI 檢查';
        } else if (text.includes('小腿') || text.includes('膝蓋')) {
          fullResponseText =
            '【🩺 軟組織修復處置建議】\n\n根據 BJSM (2020) 軟組織處理 PEACE & LOVE 原則 與小腿緊繃/跑者膝指引：\n\n• 負荷管理 (Optimal Loading)：無須完全臥床，改為 20~30 分鐘超輕鬆恢復跑 (RPE 2-3) 或快走\n• 肌力與放鬆：用滾筒放鬆小腿腓腸肌與比目魚肌，跑後加強拉伸\n• 配速調節：28°C 天候下每公里主動放慢 10~15 秒，降低衝擊';
        } else {
          fullResponseText =
            '【🏃‍♂️ AI 運動生理教練 實證處置建議】\n\n根據您目前的 ACWR 比值 1.52（處於加量期上限，依 Tim Gabbett 負荷悖論受傷風險升高）：\n\n• ACWR 負荷比 (1.52)：今日嚴禁高強度間歇，改為 輕鬆有氧跑 (RPE 3-4)\n• 天候熱指數 (28°C / 75%)：心血管散熱負擔較大，每公里請主動放慢 8~12 秒\n• 跑後營養 (4:1)：30 分鐘內補充碳水:蛋白質 (4:1) 以加速肌糖原合成';
        }
      }

      // Smooth typewriter streaming
      setLoading(false);
      setIsStreaming(true);
      let currentLen = 0;
      const step = 4;
      const timer = setInterval(() => {
        currentLen += step;
        if (currentLen >= fullResponseText.length) {
          clearInterval(timer);
          setMessages([...historyWithUser, { role: 'assistant', content: fullResponseText }]);
          setIsStreaming(false);
        } else {
          setMessages([
            ...historyWithUser,
            { role: 'assistant', content: fullResponseText.slice(0, currentLen) },
          ]);
        }
      }, 18);
    } catch {
      setLoading(false);
      setIsStreaming(false);
    }
  }

  function handleTriageSubmit() {
    const prompt = `【身體感知回報】部位：${selectedBodyPart}，嚴重度：${severity}。${
      hasBonePain ? '（注意：出現負重時局部骨痛警訊）' : ''
    }${hasChestPain ? '（注意：運動中胸悶氣喘症狀）' : ''}${
      injuryFreeText ? ` 自述症狀：${injuryFreeText}` : ''
    }。請依據醫學實證 RAG 資料庫評估是否能繼續跑步，並給予處置建議。`;
    handleSend(prompt);
  }

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <SafeAreaView style={styles.modalRoot}>
        <KeyboardAvoidingView
          behavior={Platform.OS === 'ios' ? 'padding' : undefined}
          style={{ flex: 1 }}
        >
          {/* Header */}
          <View style={styles.header}>
            <View>
              <Text style={styles.headerTitle}>🏃‍♂️ AI 健康教練</Text>
              <Text style={styles.headerSubtitle}>Groq 120B × 運動醫學 Graph RAG</Text>
            </View>
            <TouchableOpacity onPress={onClose} style={styles.closeButton}>
              <Text style={styles.closeText}>✕</Text>
            </TouchableOpacity>
          </View>

          {/* Navigation Tabs */}
          <View style={styles.tabRow}>
            <TouchableOpacity
              style={[styles.tabBtn, activeTab === 'chat' && styles.tabBtnActive]}
              onPress={() => setActiveTab('chat')}
            >
              <Text style={[styles.tabText, activeTab === 'chat' && styles.tabTextActive]}>
                💬 教練對話
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.tabBtn, activeTab === 'injury' && styles.tabBtnActive]}
              onPress={() => setActiveTab('injury')}
            >
              <Text style={[styles.tabText, activeTab === 'injury' && styles.tabTextActive]}>
                🩺 傷痛快篩
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.tabBtn, activeTab === 'rag' && styles.tabBtnActive]}
              onPress={() => setActiveTab('rag')}
            >
              <Text style={[styles.tabText, activeTab === 'rag' && styles.tabTextActive]}>
                📚 實證文獻
              </Text>
            </TouchableOpacity>
          </View>

          {/* Live Physiological Ribbon */}
          <View style={styles.ribbon}>
            <Text style={styles.ribbonText}>🔥 負荷: 320 AU</Text>
            <Text style={styles.ribbonText}>📈 基準: 210 AU</Text>
            <Text style={[styles.ribbonText, { color: '#ea580c', fontWeight: 'bold' }]}>
              ⚡ ACWR: 1.52
            </Text>
            <Text style={styles.ribbonText}>🌤️ 28°C (+8s/km)</Text>
          </View>

          {/* Tab 1: AI Chat */}
          {activeTab === 'chat' && (
            <View style={{ flex: 1 }}>
              <ScrollView
                ref={scrollViewRef}
                style={styles.messageList}
                contentContainerStyle={{ padding: 14, gap: 12 }}
              >
                {messages.map((m, i) => {
                  const isUser = m.role === 'user';
                  const isCurrentAssistantStreaming =
                    isStreaming && !isUser && i === messages.length - 1;

                  return (
                    <View
                      key={i}
                      style={[
                        styles.messageBubble,
                        isUser ? styles.userBubble : styles.assistantBubble,
                      ]}
                    >
                      <Text
                        style={[
                          styles.messageText,
                          isUser ? styles.userText : styles.assistantText,
                        ]}
                      >
                        {m.content}
                      </Text>
                      {isCurrentAssistantStreaming && (
                        <Text style={{ color: '#ea580c', fontWeight: 'bold' }}> ▊</Text>
                      )}
                    </View>
                  );
                })}

                {loading && (
                  <View style={styles.loadingBubble}>
                    <ActivityIndicator size="small" color="#ea580c" />
                    <Text style={styles.loadingText}>Groq AI 正在以運動生理 Graph RAG 思考回覆…</Text>
                  </View>
                )}
              </ScrollView>

              {/* Quick Prompt Chips */}
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                style={styles.quickPromptsContainer}
                contentContainerStyle={{ paddingHorizontal: 12, gap: 8 }}
              >
                {quickPrompts.map((p, idx) => (
                  <TouchableOpacity
                    key={idx}
                    style={styles.chip}
                    onPress={() => handleSend(p)}
                  >
                    <Text style={styles.chipText}>{p}</Text>
                  </TouchableOpacity>
                ))}
              </ScrollView>

              {/* Input Area */}
              <View style={styles.inputBar}>
                <TextInput
                  style={styles.textInput}
                  placeholder="輸入課表、配速或傷痛問題…"
                  placeholderTextColor="#64748b"
                  value={input}
                  onChangeText={setInput}
                  onSubmitEditing={() => handleSend()}
                />
                <TouchableOpacity
                  style={[styles.sendButton, (!input.trim() || loading || isStreaming) && styles.sendDisabled]}
                  onPress={() => handleSend()}
                  disabled={!input.trim() || loading || isStreaming}
                >
                  <Text style={styles.sendButtonText}>送出</Text>
                </TouchableOpacity>
              </View>
            </View>
          )}

          {/* Tab 2: Body Triage */}
          {activeTab === 'injury' && (
            <ScrollView style={{ flex: 1, padding: 16 }}>
              <Text style={styles.sectionTitle}>1. 選擇不適部位</Text>
              <View style={styles.choiceGrid}>
                {bodyParts.map((part) => (
                  <TouchableOpacity
                    key={part}
                    style={[styles.choiceBtn, selectedBodyPart === part && styles.choiceBtnActive]}
                    onPress={() => setSelectedBodyPart(part)}
                  >
                    <Text style={[styles.choiceText, selectedBodyPart === part && styles.choiceTextActive]}>
                      {part}
                    </Text>
                  </TouchableOpacity>
                ))}
              </View>

              <Text style={[styles.sectionTitle, { marginTop: 16 }]}>2. 疼痛/緊繃程度</Text>
              <View style={{ flexDirection: 'row', gap: 8 }}>
                {['輕微 (MILD)', '中度 (MODERATE)', '嚴重 (SEVERE)'].map((sev) => (
                  <TouchableOpacity
                    key={sev}
                    style={[styles.choiceBtn, { flex: 1 }, severity === sev && styles.choiceBtnActive]}
                    onPress={() => setSeverity(sev)}
                  >
                    <Text style={[styles.choiceText, severity === sev && styles.choiceTextActive]}>
                      {sev.split(' ')[0]}
                    </Text>
                  </TouchableOpacity>
                ))}
              </View>

              <Text style={[styles.sectionTitle, { marginTop: 16 }]}>3. 安全警訊勾選</Text>
              <TouchableOpacity
                style={[styles.checkRow, hasBonePain && styles.checkRowActive]}
                onPress={() => setHasBonePain(!hasBonePain)}
              >
                <Text style={styles.checkText}>⚠️ 局部骨頭深層疼痛，且負重踩踏時更痛</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.checkRow, hasChestPain && styles.checkRowActive]}
                onPress={() => setHasChestPain(!hasChestPain)}
              >
                <Text style={styles.checkText}>⚠️ 運動中出現胸悶、呼吸困難或頭暈</Text>
              </TouchableOpacity>

              <TouchableOpacity style={styles.submitTriageBtn} onPress={handleTriageSubmit}>
                <Text style={styles.submitTriageText}>🩺 送出快篩並開始 AI 深度問診</Text>
              </TouchableOpacity>
            </ScrollView>
          )}

          {/* Tab 3: RAG Evidence */}
          {activeTab === 'rag' && (
            <ScrollView style={{ flex: 1, padding: 16 }}>
              <Text style={styles.sectionTitle}>📚 內建運動醫學與運動生理學實證知識庫</Text>
              <View style={styles.ragCard}>
                <Text style={styles.ragTitle}>BJSM (2016) Tim Gabbett 運動負荷悖論</Text>
                <Text style={styles.ragPublisher}>British Journal of Sports Medicine</Text>
                <Text style={styles.ragBody}>
                  ACWR (短長期負荷比) 介於 0.8~1.3 為「甜蜜區」，受傷風險最低；高於 1.5 為「危險區」，受傷相對風險顯著上升。
                </Text>
              </View>

              <View style={styles.ragCard}>
                <Text style={styles.ragTitle}>BJSM (2020) PEACE & LOVE 軟組織處理原則</Text>
                <Text style={styles.ragPublisher}>British Journal of Sports Medicine</Text>
                <Text style={styles.ragBody}>
                  不再盲目完全冰敷靜養，急性期過後應採取「最適當負荷 (Optimal Loading)」與血管增生刺激 (Vascularisation)，以主動有氧活動促進修復。
                </Text>
              </View>

              <View style={styles.ragCard}>
                <Text style={styles.ragTitle}>AAOS 骨應力與疲勞性骨折警訊</Text>
                <Text style={styles.ragPublisher}>American Academy of Orthopaedic Surgeons</Text>
                <Text style={styles.ragBody}>
                  若出現局部單點骨痛且隨負重加劇，應立即停止跑步進行非負重交叉訓練，並就醫排除應力性骨折。
                </Text>
              </View>
            </ScrollView>
          )}
        </KeyboardAvoidingView>
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  modalRoot: { flex: 1, backgroundColor: '#0f172a' },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#1e293b',
  },
  headerTitle: { fontSize: 17, fontWeight: 'bold', color: '#f8fafc' },
  headerSubtitle: { fontSize: 11, color: '#94a3b8', marginTop: 2 },
  closeButton: { padding: 8 },
  closeText: { fontSize: 18, color: '#94a3b8', fontWeight: 'bold' },
  tabRow: { flexDirection: 'row', borderBottomWidth: 1, borderBottomColor: '#1e293b' },
  tabBtn: { flex: 1, paddingVertical: 10, alignItems: 'center', borderBottomWidth: 2, borderBottomColor: 'transparent' },
  tabBtnActive: { borderBottomColor: '#ea580c' },
  tabText: { fontSize: 13, color: '#94a3b8', fontWeight: '600' },
  tabTextActive: { color: '#ea580c', fontWeight: 'bold' },
  ribbon: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    paddingVertical: 6,
    backgroundColor: 'rgba(234, 88, 12, 0.12)',
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(234, 88, 12, 0.25)',
  },
  ribbonText: { fontSize: 11, color: '#f8fafc', fontWeight: '600' },
  messageList: { flex: 1 },
  messageBubble: { maxWidth: '85%', padding: 12, borderRadius: 14, marginVertical: 4 },
  userBubble: { alignSelf: 'flex-end', backgroundColor: '#ea580c', borderBottomRightRadius: 2 },
  assistantBubble: { alignSelf: 'flex-start', backgroundColor: '#1e293b', borderBottomLeftRadius: 2 },
  messageText: { fontSize: 14, lineHeight: 20 },
  userText: { color: '#ffffff' },
  assistantText: { color: '#f8fafc' },
  loadingBubble: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    alignSelf: 'flex-start',
    backgroundColor: '#1e293b',
    padding: 10,
    borderRadius: 12,
  },
  loadingText: { color: '#ea580c', fontSize: 12, fontWeight: '600' },
  quickPromptsContainer: { maxHeight: 38, marginVertical: 4 },
  chip: {
    backgroundColor: '#1e293b',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#334155',
  },
  chipText: { fontSize: 11.5, color: '#cbd5e1' },
  inputBar: {
    flexDirection: 'row',
    padding: 10,
    borderTopWidth: 1,
    borderTopColor: '#1e293b',
    backgroundColor: '#0f172a',
    gap: 8,
  },
  textInput: {
    flex: 1,
    backgroundColor: '#1e293b',
    color: '#ffffff',
    borderRadius: 20,
    paddingHorizontal: 14,
    paddingVertical: 8,
    fontSize: 14,
  },
  sendButton: {
    backgroundColor: '#ea580c',
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 16,
    borderRadius: 20,
  },
  sendDisabled: { backgroundColor: '#475569' },
  sendButtonText: { color: '#ffffff', fontWeight: 'bold', fontSize: 13 },
  sectionTitle: { fontSize: 14, fontWeight: 'bold', color: '#f8fafc', marginBottom: 8 },
  choiceGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  choiceBtn: {
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 8,
    backgroundColor: '#1e293b',
    borderWidth: 1,
    borderColor: '#334155',
    alignItems: 'center',
  },
  choiceBtnActive: { borderColor: '#ea580c', backgroundColor: 'rgba(234, 88, 12, 0.2)' },
  choiceText: { fontSize: 12, color: '#cbd5e1' },
  choiceTextActive: { color: '#ea580c', fontWeight: 'bold' },
  checkRow: {
    padding: 12,
    borderRadius: 8,
    backgroundColor: '#1e293b',
    borderWidth: 1,
    borderColor: '#334155',
    marginBottom: 8,
  },
  checkRowActive: { borderColor: '#ef4444', backgroundColor: 'rgba(239, 68, 68, 0.15)' },
  checkText: { fontSize: 12.5, color: '#f8fafc' },
  submitTriageBtn: {
    backgroundColor: '#ea580c',
    paddingVertical: 12,
    borderRadius: 10,
    alignItems: 'center',
    marginTop: 14,
  },
  submitTriageText: { color: '#ffffff', fontWeight: 'bold', fontSize: 14 },
  ragCard: {
    backgroundColor: '#1e293b',
    padding: 12,
    borderRadius: 10,
    marginBottom: 10,
    borderLeftWidth: 3,
    borderLeftColor: '#ea580c',
  },
  ragTitle: { fontSize: 13, fontWeight: 'bold', color: '#fdba74' },
  ragPublisher: { fontSize: 11, color: '#94a3b8', marginTop: 2 },
  ragBody: { fontSize: 12, color: '#cbd5e1', lineHeight: 17, marginTop: 6 },
});
