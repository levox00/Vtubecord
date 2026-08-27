# Vtubecord desktop app

The desktop target wraps the existing React/Vite interface in a native
Tauri/WebView2 window. It does not open Chrome or Edge as the application UI,
and the bundled Rust launcher starts the FastAPI server without a console
window.

## Development

From this directory:

```powershell
npm install
npm run dev
```

`npm run dev` expects the normal backend to already be running on
`http://127.0.0.1:8000` (for example through `START.bat`).

## Windows release installer

`npm run build:release` builds the frontend, packages the backend into
`VtubecordServer.exe` when it is not already present, and produces:

```text
src-tauri/target/release/bundle/nsis/Vtubecord_0.1.0_x64-setup.exe
src-tauri/target/release/bundle/msi/Vtubecord_0.1.0_x64_en-US.msi
```

The first build downloads the Rust crates, Tauri bundler tools, and the
WebView2 bootstrapper. The generated installer is x64 and keeps model weights
out of the application package; users download those through Vtubecord.

## Runtime data

The installed app stores writable data in `%LOCALAPPDATA%\\Vtubecord` and
passes that location to the backend. Source assets are read from the packaged
resources, so the app does not need a checkout, Python, or Node.js to run.
