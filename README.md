# AnyDesk Clone - Native Desktop Remote Control Tool

A lightweight, high-performance remote desktop application built for Windows with **AnyDesk-style 9-digit IDs**, **real-time Online/Offline presence detection**, **PIN authentication**, and **ultra-low latency screen & input control**.

---

## 🚀 Key Features

* **AnyDesk-style 9-Digit ID**: Every PC is assigned a unique, permanent 9-digit ID (e.g. `492 813 092`).
* **Real-time Online / Offline Detection**: Entering a remote ID immediately shows a live badge:
  * 🟢 **Online** (Device is connected and ready)
  * 🔴 **Offline** (Device is not currently reachable)
* **Security PIN Authentication**: Protects the host machine from unauthorized access. The controller must provide the correct PIN before any video or control commands are permitted.
* **Lightweight & High-Performance Screen Capture**:
  * Powered by `mss` (direct Windows desktop bitblt) and OpenCV fast JPEG compression.
  * Real-time hardware-friendly streaming with low CPU and network bandwidth.
* **Full Remote Control**:
  * Native Win32 API mouse movements (`SetCursorPos`), clicks (Left, Right, Middle), and wheel scrolling.
  * Full keyboard keystroke forwarding.
* **Interactive Viewer Window**:
  * Live video canvas with dynamic resolution scaling.
  * Fullscreen toggle mode.
  * Real-time FPS and latency counter.

---

## 📁 Project Structure

```
├── client/
│   ├── config.py             # Generates & manages persistent ID, PIN, and settings
│   ├── input_handler.py      # Win32 ctypes API mouse & keyboard input simulator
│   ├── screen_streamer.py    # High-speed mss capture + OpenCV compression thread
│   ├── viewer.py             # Remote viewer window with mouse/keyboard bindings
│   └── gui.py                # Main AnyDesk-style CustomTkinter desktop interface
├── server/
│   └── server.py             # WebSocket signaling, presence & stream relay hub
├── start_server.bat          # 1-click server launcher
├── start_client.bat          # 1-click client launcher
└── README.md
```

---

## ⚡ Quick Start (Local Testing on this PC)

1. **Start the Relay Server**:
   - Double-click `start_server.bat` (or run `python server\server.py`).
   - You will see: `Starting AnyDesk-style Relay & Presence Server on 0.0.0.0:8765...`

2. **Start Client 1 (Host)**:
   - Double-click `start_client.bat`.
   - Your permanent 9-digit ID will appear on the left under **"THIS DESK"** (e.g. `123 456 789`).
   - The status badge will display **🟢 Server Ready**.
   - Your default PIN is `1234` (you can change it anytime in the UI).

3. **Start Client 2 (Controller / Viewer)**:
   - Run `start_client.bat` again (or on another PC).
   - Enter Client 1's 9-digit ID into **"Remote ID"**.
   - Notice the status badge immediately switches to **🟢 Online**!
   - Enter the PIN `1234` and click **🔗 Connect**.
   - The remote control window will open with real-time video streaming and full mouse/keyboard control.

---

## 🌐 How to Connect from Anywhere in the World

Because home and office PCs sit behind routers/firewalls (NAT), both PCs must communicate through the central relay server. You have three simple options:

### Option 1: Free Cloudflare Tunnel (Zero port-forwarding, 100% free)
1. Download [Cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/).
2. Start your local server: `python server\server.py`.
3. In a terminal, run:
   ```bash
   cloudflared tunnel --url ws://localhost:8765
   ```
4. Cloudflare gives you a public secure URL (e.g., `wss://random-name.trycloudflare.com`).
5. On any PC in the world, enter that URL in the client's **Relay Server** box at the bottom and click **Update / Reconnect**.

## 🌐 Deploying to Railway or Render (Connect Anywhere in the World)

Deploying `server/` to **Railway** or **Render** gives you a free, permanently hosted WebSocket server with SSL (`wss://`) so PCs anywhere on Earth can connect.

### Option A: Railway (Recommended - Fastest Setup)
1. Push this folder to a GitHub repository (or just push the `server/` folder).
2. Go to [railway.app](https://railway.app) and click **"New Project"** -> **"Deploy from GitHub repo"**.
3. Select your repository.
4. Railway will automatically detect the `Procfile` / `Dockerfile` and start the server.
5. In Railway, go to **Settings** -> **Networking** -> **Generate Domain**.
6. You will get a domain like:
   `anydesk-relay-production.up.railway.app`
7. Your client connection string is:
   `wss://anydesk-relay-production.up.railway.app`

---

### Option B: Render
1. Push the project to GitHub.
2. Go to [render.com](https://render.com) and click **"New"** -> **"Web Service"**.
3. Connect your GitHub repository.
4. Set the following settings:
   - **Root Directory**: `server`
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python server.py`
5. Click **"Deploy Web Service"**.
6. Render will assign you a public URL like:
   `https://my-relay-desk.onrender.com`
7. Your client connection string is:
   `wss://my-relay-desk.onrender.com`

---

### How to Apply Your Cloud URL to the App
1. Open `AnyDeskClone.exe` on any PC.
2. In the bottom bar, change the **Relay Server** from `ws://localhost:8765` to:
   ```
   wss://your-app.up.railway.app
   ```
3. Click **Update / Reconnect**.
4. Both computers will now see each other online and can connect from anywhere across different cities or countries!

---

## ⚙️ Configuration & Customization

The client automatically creates `client/config.json`:
- `id`: Your persistent 9-digit device number.
- `pin`: Your security access PIN.
- `server_url`: The address of the relay server (`ws://...` or `wss://...`).
- `quality`: JPEG compression quality (default `60` for fast responsive control).
- `fps_limit`: Target capture rate (default `30` FPS).
