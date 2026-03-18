# GitHub + Azure App Service 部署指南

這份文件對應目前專案的部署方式：

- 程式碼推到 GitHub `main`
- GitHub Actions 自動部署到 Azure App Service

## 1. 先把本機變更提交到 GitHub

在專案根目錄執行：

```bash
git add .
git commit -m "Polish UI and booking availability"
git push origin main
```

如果 `git commit` 顯示沒有設定作者資訊，先執行：

```bash
git config user.name "Hans Chung"
git config user.email "你的 GitHub Email"
```

## 2. Azure App Service 要先建立好的資源

至少需要：

- Azure App Service（Linux）
- Python 3.11 Runtime
- Azure Database for PostgreSQL（正式環境建議）

## 3. Azure App Service 需要設定的 Startup Command

在 Azure Portal > App Service > Configuration > General settings：

```bash
bash startup.sh
```

`startup.sh` 會在使用 SQLite 時自動執行初始化：

- `flask --app run.py init-db`
- `flask --app run.py seed-defaults`

如果之後改用 PostgreSQL，腳本會直接跳過 SQLite 初始化，只啟動 Gunicorn。

## 4. Azure App Service 需要設定的 Application Settings

在 Azure Portal > App Service > Environment variables，加上：

```text
SCM_DO_BUILD_DURING_DEPLOYMENT=true
ENABLE_ORYX_BUILD=true
SECRET_KEY=<strong-random-secret>
DATABASE_URL=<your-postgres-connection-string>
OIDC_TENANT_ID=<tenant-id>
OIDC_CLIENT_ID=<client-id>
OIDC_CLIENT_SECRET=<client-secret>
OIDC_REDIRECT_URI=https://<app-name>.azurewebsites.net/auth/callback
OIDC_ALLOWED_TENANT_IDS=<tenant-id>
ADMIN_UPNS=<admin1@o365.tku.edu.tw>
STAFF_UPNS=<staff1@o365.tku.edu.tw>
WORKSTUDY_UPNS=<student1@o365.tku.edu.tw>
SESSION_COOKIE_SECURE=true
```

說明：

- `SCM_DO_BUILD_DURING_DEPLOYMENT=true`：讓 App Service 在部署時執行 Python build/install
- `ENABLE_ORYX_BUILD=true`：確保使用 Oryx 建置 Python app
- `DATABASE_URL` 正式環境不要再用 sqlite

## 5. 讓 GitHub Actions 可以部署 Azure

目前 repo 已有 workflow：

- `.github/workflows/deploy-appservice.yml`

你要在 GitHub repo > Settings > Secrets and variables > Actions > Repository secrets 新增：

- `AZURE_WEBAPP_NAME`
- `AZURE_WEBAPP_PUBLISH_PROFILE`

### `AZURE_WEBAPP_NAME`

填你的 App Service 名稱，例如：

```text
tku-etd-classroom-booking
```

### `AZURE_WEBAPP_PUBLISH_PROFILE`

取得方式：

1. 到 Azure Portal 打開你的 App Service
2. 點 `Get publish profile` / `下載發佈設定檔`
3. 打開下載的 `.PublishSettings` 檔
4. 把整份 XML 內容貼到 GitHub secret `AZURE_WEBAPP_PUBLISH_PROFILE`

## 6. Microsoft Entra ID Redirect URI

在 Azure Portal > App registrations > 你的應用程式 > Authentication：

新增：

```text
https://<app-name>.azurewebsites.net/auth/callback
```

本機測試用：

```text
http://localhost:5000/auth/callback
```

## 7. 推版流程

之後每次部署：

```bash
git add .
git commit -m "your message"
git push origin main
```

只要 push 到 `main`，GitHub Actions 就會自動部署到 Azure。

## 8. 第一次部署後要確認

部署完成後，先確認：

- GitHub Actions workflow 成功
- Azure App Service > Log stream 沒有啟動錯誤
- `https://<app-name>.azurewebsites.net/`
- `https://<app-name>.azurewebsites.net/auth/login`

## 9. 常見失敗點

- 沒設 `SCM_DO_BUILD_DURING_DEPLOYMENT=true`
- `OIDC_REDIRECT_URI` 和 Entra ID Authentication 設定不一致
- `AZURE_WEBAPP_PUBLISH_PROFILE` 貼錯
- App Service Startup Command 沒填
- `DATABASE_URL` 還在用本機 sqlite
