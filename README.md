# runsense

> **Athlete-First Endurance Training & Physiological Load Intelligence Platform**  
> 專為跑者打造的自主訓練數據中心與運動生理負荷智慧平台。

---

## 快速開始 (Quick Start)

### 前端啟動 (Web App)
```bash
cd web
npm install
npm run dev
```
瀏覽器開啟 `http://localhost:5173`。

### 後端啟動 (Backend API)
```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate | macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python scripts/seed_demo_personas.py
uvicorn app.main:app --reload --port 8000
```

### 客戶端離線測試
```bash
cd client
npm test
```

---

## 系統交接與開發手冊 (Hand-off Guide)
詳細的資料庫建置、Demo 帳號密碼、UI 各介面導覽與未完成待辦清單，請參閱：
👉 **[HANDOFF.md](./HANDOFF.md)**
