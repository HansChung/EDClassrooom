# 淡江教科系教室借用系統（Flask）

本專案依需求建置以下能力：
- Office 365（Microsoft Entra ID）單一登入，無本地註冊。
- 教室借用申請、衝堂檢查、低風險自動核准、高風險人工核准。
- 管理後台（教室管理、規則管理、人工借用登記、角色管理）。
- 借用日曆檢視與行事曆匯出（ICS/CSV/XLSX/ODS）。
- Azure App Service 部署設定與 CI/CD workflow。

## 1. 本機啟動

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

設定 `.env` 後執行：

```bash
flask --app run.py init-db
flask --app run.py seed-defaults
python run.py
```

## 2. Office 365 單一登入設定

1. 到 Azure Portal > Microsoft Entra ID > App registrations 建立應用程式。
2. 新增 Redirect URI：
   - 本機：`http://localhost:5000/auth/callback`
   - 雲端：`https://<app-name>.azurewebsites.net/auth/callback`
3. 建立 Client secret，填入 `.env` 的 `OIDC_CLIENT_SECRET`。
4. 建議限制租戶：`OIDC_ALLOWED_TENANT_IDS=<學校租戶ID>`。

## 3. 角色與權限

- `user`：一般借用者。
- `workstudy_manager`：可查看全域借用與人工登記。
- `staff_manager`：可查看全域借用、審核高風險案件、管理規則。
- `super_admin`：完整權限含角色管理。

可先透過 `.env` 的 `ADMIN_UPNS` / `STAFF_UPNS` / `WORKSTUDY_UPNS` 自動授權。

## 4. PDF 規範對應

已內建初始教室資料與限制：
- 可線上借用：`L105`、`L108`、`L109`、`L111`、`ED202`、`ED204`、`ED205`
- 不可線上借用：`L102`、`L110`、`L103`（請改由管理後台人工登記）
- 初始時數規則：
  - 單次上限 2 小時
  - 每日總時數上限 3 小時
  - 低風險自動核准時數上限 2 小時

## 5. Azure App Service 部署

### 5.1 建立資源
- Azure App Service (Linux, Python 3.11)
- Azure Database for PostgreSQL（建議正式環境）
- Application Insights（監控）

### 5.2 App Settings（至少）
- `SECRET_KEY`
- `DATABASE_URL`
- `OIDC_TENANT_ID`
- `OIDC_CLIENT_ID`
- `OIDC_CLIENT_SECRET`
- `OIDC_REDIRECT_URI=https://<app-name>.azurewebsites.net/auth/callback`
- `OIDC_ALLOWED_TENANT_IDS`
- `ADMIN_UPNS` / `STAFF_UPNS` / `WORKSTUDY_UPNS`
- `SESSION_COOKIE_SECURE=true`

### 5.3 啟動命令
在 App Service 設定 Startup Command：

```bash
gunicorn --bind=0.0.0.0 --timeout 600 run:app
```

（對應 `startup.txt`）

## 6. 核心路由

- `/auth/login`：Office 365 登入
- `/bookings/new`：新增借用
- `/approvals/`：審核佇列（承辦/最高管理者）
- `/admin/`：管理後台
- `/calendar/`：行事曆
- `/calendar/export/ics`：ICS 匯出
- `/calendar/export/csv`：CSV 匯出
- `/calendar/export/xlsx`：XLSX 匯出
- `/calendar/export/ods`：ODS（OpenDocument）匯出

## 7. 建議後續加值（下一階段）

- Microsoft Graph 寄送通知信（申請成功/駁回/提醒）。
- 違規點數與暫停借用機制。
- 假日與學期課表模板批次匯入。
- 細緻化審核條件（特殊設備、夜間時段、跨館別規則）。
- 導入 migration 版本控管（`flask db migrate/upgrade`）與自動化測試。
