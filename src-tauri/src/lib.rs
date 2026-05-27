// Gateway 桌面壳 — Tauri 只管「窗口 + 进程」,所有内容走 HTTP 到 sidecar(localhost:4321)。
// 铁律:不碰 Tauri JS 桥,前端零改,壳可热插拔。
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

/// 选一个空闲端口(bind :0 让内核分配,拿到号再释放)。动态端口根治"重绑 4321 撞 TIME_WAIT/孤儿"
/// 那整类 bug:孤儿占着旧端口也无所谓,新实例直接用另一个空闲口。
fn pick_free_port() -> u16 {
    std::net::TcpListener::bind("127.0.0.1:0")
        .ok()
        .and_then(|l| l.local_addr().ok())
        .map(|a| a.port())
        .unwrap_or(4321)
}

/// 按名杀掉所有 gateway-server sidecar(含 PyInstaller bootloader→worker 整棵树)。
/// single-instance 保证只有一个 app,所以任何残留的 sidecar 都是上次崩溃/被强杀留下的孤儿。
/// 用于:① 启动前清残留(防上次没退干净) ② 干净退出时兜底(child.kill 杀不到 worker)。
fn kill_stale_sidecars() {
    #[cfg(unix)]
    {
        // -9 SIGKILL:孤儿不需要优雅 shutdown(那会拖着端口不放,新 sidecar 抢不到),瞬死立刻释放端口
        let _ = std::process::Command::new("pkill")
            .args(["-9", "-f", "gateway-server"])
            .status();
    }
    #[cfg(windows)]
    {
        let _ = std::process::Command::new("taskkill")
            .args(["/F", "/IM", "gateway-server.exe", "/T"])
            .status();
    }
}

/// 轮询本地端口直到可连(server 就绪),或超时返 false。
fn wait_for_port(port: u16, timeout_secs: u64) -> bool {
    let deadline = Instant::now() + Duration::from_secs(timeout_secs);
    let addr = format!("127.0.0.1:{port}");
    while Instant::now() < deadline {
        if std::net::TcpStream::connect(&addr).is_ok() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    false
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        // T5 单实例:第二次启动 → 不开新窗,focus 已有窗口。插件必须最先注册。
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.unminimize();
                let _ = w.set_focus();
            }
        }))
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            // T4 自启 sidecar:动态空闲端口 + headless(GATEWAY_NO_OPEN=1)。
            // 用动态端口后,上次崩溃的孤儿占着旧口也不影响 —— 不在启动时杀(那会跟新 spawn 抢资源),
            // 退出时才清(见下 ExitRequested)。
            let port = pick_free_port();
            let sidecar = app
                .shell()
                .sidecar("gateway-server")
                .expect("sidecar 'gateway-server' 没找到(跑 build-sidecar.sh)")
                .env("GATEWAY_NO_OPEN", "1")
                .env("GATEWAY_PORT", port.to_string());
            let (mut _rx, child) = sidecar.spawn().expect("spawn sidecar 失败");
            // T6 存 child handle,退出时 kill
            app.manage(Mutex::new(Some(child)));

            // 等 server 就绪再建窗(避免白屏)。setup 在 main thread,阻塞 ~几秒可接受。
            if !wait_for_port(port, 30) {
                eprintln!("[gateway] sidecar 30s 内没在 :{port} 就绪");
            }
            WebviewWindowBuilder::new(
                app,
                "main",
                WebviewUrl::External(format!("http://127.0.0.1:{port}/").parse().unwrap()),
            )
            .title("Gateway · 半小时复盘")
            .inner_size(1200.0, 850.0)
            .resizable(true)
            .build()?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Tauri app 构建失败")
        .run(|app_handle, event| {
            // T6 app 退出 → kill sidecar,防僵尸 uvicorn 占端口。
            // child.kill() 只杀 onefile 的 bootloader,worker 会漏 → 再 pkill 整树兜底。
            if let RunEvent::ExitRequested { .. } = event {
                if let Some(state) = app_handle.try_state::<Mutex<Option<CommandChild>>>() {
                    if let Some(child) = state.lock().unwrap().take() {
                        let _ = child.kill();
                    }
                }
                kill_stale_sidecars();
            }
        });
}
