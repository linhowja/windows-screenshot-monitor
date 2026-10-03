TorCap -> Windows Screenshot Monitor
File-by-file modification map
Source repository:
https://github.com/ciscoAnass/torcap
Reviewed branch:
`main`
Existing files
```text
.gitignore
LICENSE
README.md
app.py
config.json
install.bat
requirements.txt
server_config.json
tor_server.py
```
Summary
File	Decision	Action
`.gitignore`	KEEP	保留，補充 build/dist/log/cache 等排除項
`LICENSE`	KEEP	保留原授權資訊
`README.md`	REWRITE	完全改寫成 Windows Client/Server MVP 說明
`app.py`	MAJOR MODIFY	改造成 Screenshot Client
`config.json`	REWRITE	改成 Server IP/Port + Last Known Good Config
`install.bat`	REWRITE	不再安裝 Tor，改成正式 Windows installer 流程
`requirements.txt`	REWRITE	移除 Tor 相關套件，依最終實作決定 Flask/Waitress/Pillow 等依賴
`server_config.json`	REWRITE	改成 Windows Server 設定
`tor_server.py`	MAJOR REWRITE	砍掉 Web/Tor 功能，只保留/重寫 upload server 核心
1. .gitignore
KEEP
保留 Git ignore 概念。
MODIFY
建議加入：
```text
build/
dist/
*.log
Cache/
*.local.json
```
實際項目由 Grok 依 build 結構調整。
2. LICENSE
KEEP
保留原專案授權資訊，不任意刪除。
3. README.md
REWRITE
移除所有與下列內容相關的舊文件：
Tor
.onion
Tor Browser
Debian server
Web Gallery
Web Login
Gunicorn deployment
新版 README 應說明：
Windows Client
Windows Server
HTTP POST /api/upload
TCP 55550
Client install
Server install
Task Scheduler
Firewall
Cache / Recovery
Retention
Uninstall
4. app.py
MAJOR MODIFY
可保留概念
`mss` screen capture
`getpass.getuser()` / Windows username 概念
Primary monitor capture
`requests` HTTP upload
timer loop
local filesystem queue
retry concept
必須刪除
Tor SOCKS proxy
.onion
upload password
upload batch size
max folder size rotation
PNG-only design
Tor-specific logging/messages
必須加入
hostname detection
Windows session lock/unlock handling
power sleep/wake handling
resize 25% x 25%
8-bit grayscale
JPEG encode
configurable JPEG quality
server-controlled interval
5 sec upload timeout
direct upload without persistent local file on success
cache only on failed upload
5 minute recovery scan
unlock/wake immediate recovery
full cache recovery
duplicate-safe upload behavior
last-known-good config
server response config update
client cache retention
建議
第一版可以先維持單一 `app.py`，不要過早拆成大量 modules。
5. config.json
REWRITE
舊項目例如：
`interval_seconds`
`screenshot_folder`
`server_url`
`upload_password`
`upload_batch_size`
`max_folder_size_mb`
`tor_socks_proxy`
依 MVP 移除或重新定義。
建議概念：
```json
{
  "server_ip": "192.168.1.100",
  "server_port": 55550,
  "last_known_interval_seconds": 20,
  "last_known_jpeg_quality": 40,
  "last_known_client_cache_days": 3
}
```
實際 schema 由 Grok 依程式設計決定，但不要新增未經 ChatGPT 裁決的功能。
6. install.bat
REWRITE / MAY BE REPLACED
原版是 Tor Browser / VBS / Edge 自動啟動用途，不符合新專案。
新的安裝方式可以不再使用 `install.bat`，而改用正式 Windows installer，例如 Inno Setup / WiX 等。
如果 Grok 提議保留 `.bat` 作為 build/deploy helper，可以，但它不能代替正式 uninstall information、Task Scheduler、Firewall 等安裝功能。
7. requirements.txt
REWRITE
移除：
`pysocks`
Tor-specific dependencies
不必要的 `python-dotenv`（除非實作另有明確用途）
可能需要：
`mss`
`Pillow`
`requests`
`flask`
`waitress`
`pyinstaller`
最終套件以實際 implementation 為準。
8. server_config.json
REWRITE
移除：
web username/password
web password hash
upload password
site name
Flask session secret
建議 schema：
```json
{
  "storage_root": "D:\\ScreenshotServer\\",
  "listen_port": 55550,
  "screenshot_interval_seconds": 20,
  "jpeg_quality": 40,
  "client_cache_days": 3,
  "server_retention_days": 14
}
```
9. tor_server.py
MAJOR REWRITE
目前此檔案包含大量：
Web login
HTML templates
image gallery
preview
delete route
ZIP download
Tor assumptions
web authentication
這些全部不是 MVP 必要功能。
保留/重用概念
Flask / HTTP server concept
`/api/upload`
filesystem storage
identifier validation
`secure_filename` / safe path handling concept
file save
刪除
Web UI
Web login
session
HTML templates
image gallery
preview
ZIP download
delete web routes
web password
upload password
Tor
Debian-specific startup
新增/重做
Windows 55550 listener
Hostname + Username handling
filename date parsing
storage root setting
duplicate upload handling
HTTP 200 ACK after successful write
return latest client config in success response
server retention cleanup
Windows-friendly server startup
Server 不需要 Client registration database。
10. Important architectural conclusion
不要為了「保留 TorCap」而硬保留 TorCap 的所有檔案與結構。
TorCap 主要作為：
```text
Capture + HTTP upload + Retry/Cache concepts
```
的參考 code base。
新的 Server 應該優先追求「小而乾淨」，而不是把原本 38KB 左右的 `tor_server.py` 硬改成更大的泥球。
