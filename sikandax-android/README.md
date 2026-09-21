# SikandX Android app — install the bot on your phone

Black / gold / white theme (`#0a0a0b` / `#d4af37` / `#f8f7f4`), same as the
SikandX website. XAUUSD only, M1/M5/M15.

## How it works

- The **bot brain stays in Python** (`sikandx/`). Your phone app is a thin
  client that talks to it over HTTP/JSON.
- **Private server (full trading):** run `python -m sikandx.app` on your PC
  (it listens on `0.0.0.0:5001`). The app uses `/api/status`, `/api/signal`,
  `/api/backtest`, `/api/command`.
- **Shared demo feed (signals only):** the public Vercel demo exposes
  `/api/demo-signal` and `/api/demo-backtest`. No broker, no orders.

> MT5 can only run on Windows — the phone cannot fetch MT5 candles itself.
> It must point at a server (your PC or Vercel) that runs the strategy.

## Option A — download the APK (recommended, no Android Studio needed)

1. Push this repo to GitHub (or open it there).
2. Go to **Actions → SikandX APK → Run workflow** (or push a change under
   `sikandax-android/` — it builds automatically).
3. When the run finishes, download the **SikandX-app-debug** artifact —
   it contains `app-debug.apk`.
4. On your phone: allow **Install unknown apps** for your browser/Files,
   open the APK, install **SikandX**.
5. Open SikandX → **Settings**:
   - Private: enter `http://<YOUR-PC-LAN-IP>:5001` (e.g.
     `http://192.168.1.50:5001`), mode = *Private bot server*.
   - Demo: enter `https://<your-site>.vercel.app/sikandx`, mode =
     *Shared demo feed*.
6. Tap **SAVE & CONNECT**, then **Status → REFRESH STATUS**.

## Option B — build on your own PC (needs Android Studio)

```bat
cd sikandax-android
npm install
npx cap add android
npx cap sync android
npx cap open android
```

Then in Android Studio: **Build → Build APK(s)**. The APK lands in
`android/app/build/outputs/apk/debug/`. Copy it to your phone and install.

`build-apk-local.bat` in this folder does the npm/Capacitor steps for you.

## Run the private server so the phone can reach it

```bat
pip install flask pandas numpy
python -m sikandx.app --host 0.0.0.0 --port 5001
```

- Phone and PC must be on the **same Wi-Fi**.
- Find your PC LAN IP with `ipconfig` (e.g. `192.168.1.50`).
- Windows Firewall must allow inbound TCP 5001 (first run usually prompts).
- Keep the MT5 terminal open/logged in on the PC for a live feed;
  otherwise the server uses the sample feed (validation mode).

## Safety

- Demo/paper first. Live orders on the private server need one-time
  **CONFIRM LIVE** and are never implicit.
- Broker credentials live only in server memory, never in the app.
- Trading XAUUSD on leverage is high risk. Not financial advice.
