#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    net::TcpStream,
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::Mutex,
    thread,
    time::Duration,
};

use tauri::{AppHandle, Manager, RunEvent};

const BACKEND_PORT: u16 = 8000;
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

struct ManagedProcesses(Mutex<Vec<Child>>);

fn data_dir(app: &AppHandle) -> PathBuf {
    app.path()
        .app_local_data_dir()
        .unwrap_or_else(|_| std::env::temp_dir().join("Vtubecord"))
}

fn backend_candidates(app: &AppHandle) -> Vec<PathBuf> {
    let resource_dir = app.path().resource_dir().unwrap_or_default();
    let data = data_dir(app);
    vec![
        resource_dir.join("VtubecordServer.exe"),
        // Tauri preserves the configured `resources/*` directory in some
        // Windows bundle targets, while other targets flatten the glob.
        resource_dir.join("resources").join("VtubecordServer.exe"),
        resource_dir.join("server").join("VtubecordServer.exe"),
        resource_dir.join("resources").join("server").join("VtubecordServer.exe"),
        data.join("server").join("VtubecordServer.exe"),
    ]
}

fn existing_backend(app: &AppHandle) -> Option<PathBuf> {
    backend_candidates(app)
        .into_iter()
        .find(|path| path.is_file())
}

fn port_is_open(port: u16) -> bool {
    TcpStream::connect(("127.0.0.1", port)).is_ok()
}

#[cfg(windows)]
fn hide_console(command: &mut std::process::Command) {
    use std::os::windows::process::CommandExt;
    command.creation_flags(CREATE_NO_WINDOW);
}

#[cfg(not(windows))]
fn hide_console(_command: &mut std::process::Command) {}

fn spawn_backend(app: &AppHandle) -> Option<Child> {
    let data = data_dir(app);
    if let Err(error) = std::fs::create_dir_all(&data) {
        eprintln!(
            "Could not create Vtubecord data directory {}: {error}",
            data.display()
        );
    }

    if port_is_open(BACKEND_PORT) {
        // A developer may already have the portable backend running. Reuse it
        // instead of creating a second server or showing an error window.
        return None;
    }

    let resource_dir = app.path().resource_dir().unwrap_or_default();
    let (program, args, working_dir) = if let Some(executable) = existing_backend(app) {
        (
            executable,
            vec![
                "--host".to_string(),
                "127.0.0.1".to_string(),
                "--port".to_string(),
                BACKEND_PORT.to_string(),
            ],
            data.clone(),
        )
    } else if cfg!(debug_assertions) {
        // `tauri dev` can be used directly from a checkout without requiring
        // START.bat first. The release app never relies on Python.
        let project_root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
        let python = project_root.join("backend/.venv/Scripts/python.exe");
        if !python.is_file() {
            eprintln!(
                "VtubecordServer.exe was not found and the development backend venv is unavailable"
            );
            return None;
        }
        (
            python,
            vec![
                "-m".to_string(),
                "app.desktop_server".to_string(),
                "--host".to_string(),
                "127.0.0.1".to_string(),
                "--port".to_string(),
                BACKEND_PORT.to_string(),
            ],
            project_root,
        )
    } else {
        eprintln!("VtubecordServer.exe was not found in the application resources");
        return None;
    };

    let mut command = Command::new(program);
    command
        .args(args)
        .current_dir(working_dir)
        .env("VTUBECORD_DESKTOP", "1")
        .env("VTUBECORD_DATA_DIR", &data)
        .env("VTUBECORD_RESOURCE_DIR", &resource_dir)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    hide_console(&mut command);

    match command.spawn() {
        Ok(child) => Some(child),
        Err(error) => {
            eprintln!("Could not start VtubecordServer.exe: {error}");
            None
        }
    }
}

fn spawn_optional_sidecars(app: &AppHandle) -> Vec<Child> {
    let data = data_dir(app);
    let mut children = Vec::new();

    // Keep the single-model llama.cpp router behavior used by START_ALL.bat,
    // but make it invisible when a packaged/local runtime is available.
    let model_dir = data.join("assets/models/gguf");
    let llama = [
        data.join("tools/llama.cpp/llama-server.exe"),
        app.path()
            .resource_dir()
            .unwrap_or_default()
            .join("tools/llama.cpp/llama-server.exe"),
    ]
    .into_iter()
    .find(|path| path.is_file());
    if let Some(executable) = llama {
        if model_dir.is_dir() && !port_is_open(8081) {
            let mut command = Command::new(executable);
            command
                .args([
                    "--models-dir",
                    model_dir.to_string_lossy().as_ref(),
                    "--models-max",
                    "1",
                    "--models-autoload",
                    "--jinja",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8081",
                    "-c",
                    "16384",
                    "-ngl",
                    "99",
                ])
                .current_dir(&data)
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null());
            hide_console(&mut command);
            if let Ok(child) = command.spawn() {
                children.push(child);
            }
        }
    }

    // NeMo-Speech.cpp is optional and only starts when both the executable and
    // the configured default model are present. Faster-Whisper remains the
    // backend fallback when this sidecar is not installed.
    let nemo_model = data.join("assets/whisper/nemotron/nemotron-3.5-asr-streaming-0.6b.q8_0.gguf");
    let nemo = [
        data.join("tools/nemo-speech/nemo-speech.exe"),
        app.path()
            .resource_dir()
            .unwrap_or_default()
            .join("tools/nemo-speech/nemo-speech.exe"),
    ]
    .into_iter()
    .find(|path| path.is_file());
    if let (Some(executable), true) = (nemo, nemo_model.is_file()) {
        if !port_is_open(8092) {
            let mut command = Command::new(executable);
            command
                .args([
                    "serve",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8092",
                    "--asr-model",
                    nemo_model.to_string_lossy().as_ref(),
                    "--asr.backend.gpu",
                    "0",
                    "--asr.streaming.rnnt_right_context",
                    "3",
                ])
                .current_dir(&data)
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null());
            hide_console(&mut command);
            if let Ok(child) = command.spawn() {
                children.push(child);
            }
        }
    }

    children
}

fn wait_for_backend() {
    for _ in 0..80 {
        if TcpStream::connect(("127.0.0.1", BACKEND_PORT)).is_ok() {
            return;
        }
        thread::sleep(Duration::from_millis(250));
    }
    eprintln!("Vtubecord backend did not become ready on port {BACKEND_PORT}");
}

fn stop_processes(app: &AppHandle) {
    let Some(state) = app.try_state::<ManagedProcesses>() else {
        return;
    };
    let Ok(mut process) = state.0.lock() else {
        return;
    };
    for child in process.iter_mut() {
        let _ = child.kill();
        let _ = child.wait();
    }
    process.clear();
}

#[tauri::command]
fn desktop_runtime() -> serde_json::Value {
    serde_json::json!({
        "name": "Vtubecord",
        "desktop": true,
        "backend": format!("http://127.0.0.1:{BACKEND_PORT}"),
    })
}

pub fn run() {
    let app = tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![desktop_runtime])
        .setup(|app| {
            let mut children = Vec::new();
            if let Some(backend) = spawn_backend(app.handle()) {
                children.push(backend);
            }
            children.extend(spawn_optional_sidecars(app.handle()));
            app.manage(ManagedProcesses(Mutex::new(children)));
            if port_is_open(BACKEND_PORT) {
                thread::spawn(wait_for_backend);
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Vtubecord application");

    app.run(|app_handle, event| {
        if matches!(event, RunEvent::Exit | RunEvent::ExitRequested { .. }) {
            stop_processes(app_handle);
        }
    });
}
