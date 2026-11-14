use std::process::{Child, Command};
use std::sync::Mutex;
use std::net::TcpStream;
use std::time::Duration;
use std::path::PathBuf;
use tauri::Manager;

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

struct BackendProcessState {
    child: Mutex<Option<Child>>,
}

fn is_backend_alive() -> bool {
    let addr = "127.0.0.1:8000";
    if let Ok(socket_addr) = addr.parse() {
        TcpStream::connect_timeout(&socket_addr, Duration::from_millis(500)).is_ok()
    } else {
        false
    }
}

fn launch_backend() -> Option<Child> {
    if is_backend_alive() {
        println!("[Sealed Tauri] Backend is already running on 127.0.0.1:8000");
        return None;
    }

    println!("[Sealed Tauri] Backend not detected on 127.0.0.1:8000. Auto-starting local runtime...");

    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|d| d.to_path_buf()))
        .unwrap_or_else(|| PathBuf::from("."));

    // -------------------------------------------------------------------------
    // Strategy 1: Standalone compiled native Windows backend binary (Zero Python/Docker required)
    // -------------------------------------------------------------------------
    let mut backend_candidates = vec![
        exe_dir.join("sealed-backend.exe"),
        exe_dir.join("sealed-backend").join("sealed-backend.exe"),
        exe_dir.join("bin").join("sealed-backend.exe"),
        exe_dir.join("bin").join("sealed-backend").join("sealed-backend.exe"),
    ];

    // For local dev builds running out of target/debug or target/release, inspect parent paths
    let mut cur = exe_dir.clone();
    for _ in 0..4 {
        if let Some(parent) = cur.parent() {
            backend_candidates.push(parent.join("dist_setup").join("app").join("sealed-backend").join("sealed-backend.exe"));
            backend_candidates.push(parent.join("test_dist").join("sealed-backend").join("sealed-backend.exe"));
            cur = parent.to_path_buf();
        }
    }

    for b_path in &backend_candidates {
        if b_path.exists() {
            println!("[Sealed Tauri] Found standalone backend binary: {:?}", b_path);
            let mut cmd = Command::new(b_path);
            cmd.arg("--headless").arg("--exact-port");

            // Resolve proper application root directory
            let parent_dir = b_path.parent().unwrap_or(&exe_dir);
            let base_dir = if parent_dir.file_name().map_or(false, |n| n == "sealed-backend" || n == "bin") {
                parent_dir.parent().unwrap_or(parent_dir)
            } else {
                parent_dir
            };

            let local_data = base_dir.join("data");
            let is_writable = {
                let _ = std::fs::create_dir_all(&local_data);
                let probe = local_data.join(".write_probe");
                if std::fs::write(&probe, b"1").is_ok() {
                    let _ = std::fs::remove_file(&probe);
                    true
                } else {
                    false
                }
            };

            let sealed_data_dir = if is_writable {
                local_data
            } else {
                let local_app_data = std::env::var("LOCALAPPDATA").unwrap_or_else(|_| ".".to_string());
                let fallback = PathBuf::from(local_app_data).join("Sealed Sovereign Enclave").join("data");
                let _ = std::fs::create_dir_all(&fallback);
                fallback
            };

            cmd.current_dir(base_dir);
            cmd.env("BASE_DIR", base_dir);
            cmd.env("SEALED_DATA_DIR", &sealed_data_dir);
            cmd.env("AIRGAP_MODE", "1")
               .env("HF_HUB_OFFLINE", "1")
               .env("TRANSFORMERS_OFFLINE", "1")
               .env("HF_DATASETS_OFFLINE", "1")
               .env("SEALED_AIRGAP_ENFORCED", "1");

            #[cfg(target_os = "windows")]
            {
                cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
            }

            match cmd.spawn() {
                Ok(mut child) => {
                    println!("[Sealed Tauri] Spawned standalone backend (PID: {}). Awaiting health...", child.id());
                    // Allow up to 35 seconds (140 * 250ms) for cold boot / Defender verification on virgin machines
                    for _ in 0..140 {
                        if is_backend_alive() {
                            println!("[Sealed Tauri] Standalone backend is alive and verified on 127.0.0.1:8000");
                            return Some(child);
                        }
                        if let Ok(Some(status)) = child.try_wait() {
                            eprintln!("[Sealed Tauri] Standalone backend exited prematurely with status: {:?}", status);
                            break;
                        }
                        std::thread::sleep(Duration::from_millis(250));
                    }
                    return Some(child);
                }
                Err(e) => {
                    eprintln!("[Sealed Tauri] Could not spawn standalone backend {:?}: {}", b_path, e);
                }
            }
        }
    }

    // -------------------------------------------------------------------------
    // Strategy 2: Native host Python launcher fallback
    // -------------------------------------------------------------------------
    println!("[Sealed Tauri] Searching for host Python environment...");
    let mut python_candidates = vec![
        exe_dir.join("python").join("python.exe"),
    ];

    if let Ok(conda_prefix) = std::env::var("CONDA_PREFIX") {
        python_candidates.push(PathBuf::from(conda_prefix).join("python.exe"));
    }

    if let Ok(user_profile) = std::env::var("USERPROFILE") {
        let p = PathBuf::from(user_profile);
        python_candidates.push(p.join("miniconda3\\envs\\ragapp\\python.exe"));
        python_candidates.push(p.join("miniconda3\\python.exe"));
        python_candidates.push(p.join("anaconda3\\envs\\ragapp\\python.exe"));
        python_candidates.push(p.join("anaconda3\\python.exe"));
    }

    python_candidates.push(PathBuf::from("python.exe"));

    let mut found_py: Option<PathBuf> = None;
    for py in &python_candidates {
        if py.exists() {
            found_py = Some(py.clone());
            break;
        }
    }

    // Search for desktop_launcher.py walking up directory hierarchy
    let mut script_candidates = vec![
        exe_dir.join("desktop_launcher.py"),
        exe_dir.join("backend").join("desktop_launcher.py"),
    ];
    let mut search_cur = exe_dir.clone();
    for _ in 0..4 {
        if let Some(parent) = search_cur.parent() {
            script_candidates.push(parent.join("desktop_launcher.py"));
            script_candidates.push(parent.join("backend").join("desktop_launcher.py"));
            search_cur = parent.to_path_buf();
        }
    }

    let mut found_script: Option<PathBuf> = None;
    for sc in &script_candidates {
        if sc.exists() {
            found_script = Some(sc.clone());
            break;
        }
    }

    if let (Some(py), Some(script)) = (found_py, found_script) {
        println!("[Sealed Tauri] Launching backend script: {:?} via {:?}", script, py);
        let mut cmd = Command::new(&py);
        cmd.arg(&script).arg("--headless").arg("--exact-port");
        if let Some(script_dir) = script.parent() {
            if let Some(root_dir) = script_dir.parent() {
                cmd.current_dir(root_dir);
            }
        }

        cmd.env("AIRGAP_MODE", "1")
           .env("HF_HUB_OFFLINE", "1")
           .env("TRANSFORMERS_OFFLINE", "1")
           .env("HF_DATASETS_OFFLINE", "1")
           .env("SEALED_AIRGAP_ENFORCED", "1");

        #[cfg(target_os = "windows")]
        {
            cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
        }

        match cmd.spawn() {
            Ok(mut child) => {
                println!("[Sealed Tauri] Spawned host Python sidecar (PID: {}). Awaiting health...", child.id());
                for _ in 0..80 {
                    if is_backend_alive() {
                        println!("[Sealed Tauri] Host backend is alive and verified on 127.0.0.1:8000");
                        return Some(child);
                    }
                    if let Ok(Some(status)) = child.try_wait() {
                        eprintln!("[Sealed Tauri] Host Python backend exited prematurely with status: {:?}", status);
                        break;
                    }
                    std::thread::sleep(Duration::from_millis(250));
                }
                return Some(child);
            }
            Err(e) => {
                eprintln!("[Sealed Tauri] Failed to spawn host Python backend: {}", e);
            }
        }
    }

    // -------------------------------------------------------------------------
    // Strategy 3: Sovereign enclave container (optional acceleration if Docker is available)
    // -------------------------------------------------------------------------
    #[cfg(target_os = "windows")]
    {
        println!("[Sealed Tauri] Checking optional Docker container...");
        let mut docker_cmd = Command::new("docker");
        docker_cmd.args(&["start", "sealed-sovereign-enclave"]);
        docker_cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
        if let Ok(mut child) = docker_cmd.spawn() {
            let _ = child.wait();
            for _ in 0..10 {
                if is_backend_alive() {
                    println!("[Sealed Tauri] Sovereign container backend is active on 127.0.0.1:8000");
                    return None;
                }
                std::thread::sleep(Duration::from_millis(300));
            }
        }
    }

    None
}

#[tauri::command]
fn get_backend_url() -> String {
    "http://127.0.0.1:8000".to_string()
}

#[tauri::command]
fn is_airgap_active() -> bool {
    true
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let backend_child = launch_backend();
    let state = BackendProcessState {
        child: Mutex::new(backend_child),
    };

    tauri::Builder::default()
        .manage(state)
        .invoke_handler(tauri::generate_handler![get_backend_url, is_airgap_active])
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            match event {
                tauri::WindowEvent::CloseRequested { .. } | tauri::WindowEvent::Destroyed => {
                    let state = window.state::<BackendProcessState>();
                    if let Ok(mut guard) = state.child.lock() {
                        if let Some(mut child) = guard.take() {
                            println!("[Sealed Tauri] Terminating backend sidecar (PID: {})...", child.id());
                            let _ = child.kill();
                        }
                    }
                }
                _ => {}
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Sealed sovereign desktop application");
}
