// Gateway 桌面壳 — Tauri 只管「窗口 + 进程」,所有内容走 HTTP 到 sidecar(localhost:4321)。
// 铁律:不碰 Tauri JS 桥,前端零改,壳可热插拔。
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tauri_plugin_updater::UpdaterExt;

/// 启动时后台 check 是否有新版本。失败 silent — 不阻塞主流程。
/// 走 yanpai feedback-sink /updates/latest.json,minisign 验签,有新版本下载到临时位置后
/// 触发应用重启(用户确认 dialog 在前端做,这里只做检测+下载机制)
async fn check_for_updates(app: AppHandle, sidecar_port: u16) {
    let updater = match app.updater() {
        Ok(u) => u,
        Err(e) => {
            log::warn!("[updater] init failed: {e}");
            return;
        }
    };
    match updater.check().await {
        Ok(Some(update)) => {
            let new_ver = update.version.clone();
            log::info!("[updater] new version available: {}", new_ver);
            // 下载 + 安装 — 用户重启时生效;失败 silent
            match update
                .download_and_install(|_chunk, _total| {}, || {})
                .await
            {
                Ok(()) => {
                    log::info!("[updater] download+install done, notifying sidecar");
                    // POST sidecar 让它推 banner 给前端 "重启生效"
                    notify_sidecar_updater_installed(sidecar_port, &new_ver).await;
                }
                Err(e) => log::warn!("[updater] download/install failed: {e}"),
            }
        }
        Ok(None) => log::info!("[updater] no new version"),
        Err(e) => log::warn!("[updater] check failed: {e}"),
    }
}

/// 把"新版本已下载,重启生效"事件推给 sidecar /api/updater/installed。
/// sidecar 内存队列存,前端 30s poll /api/notifications 拿出来挂 banner。
///
/// 兜底:retry 10 次 × 间隔 3s(防 sidecar 冷启 / 临时抖动);全失败也落 pending 文件
/// 让 sidecar 下次启动时自补 notification(review #18)。
async fn notify_sidecar_updater_installed(port: u16, version: &str) {
    let url = format!("http://127.0.0.1:{port}/api/updater/installed");
    let body = serde_json::json!({ "version": version });
    let client = match reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(5))
        .build()
    {
        Ok(c) => c,
        Err(e) => {
            log::warn!("[updater] reqwest build fail: {e}");
            write_updater_pending(version);
            return;
        }
    };
    for attempt in 0..10u32 {
        match client.post(&url).json(&body).send().await {
            Ok(resp) if resp.status().is_success() => {
                log::info!("[updater] sidecar notified (try {attempt})");
                return;
            }
            Ok(resp) => log::warn!("[updater] sidecar notify HTTP {} (try {attempt})", resp.status()),
            Err(e) => log::warn!("[updater] sidecar notify fail (try {attempt}): {e}"),
        }
        tokio::time::sleep(Duration::from_secs(3)).await;
    }
    log::warn!("[updater] sidecar 10 次 retry 全失败,落 pending 文件等 sidecar 下次启动自补");
    write_updater_pending(version);
}

/// 失败时落 ~/.human-ai/.updater-pending.json,sidecar startup hook 读它后自动 push notification。
/// 不引入 dirs crate;走 std::env 算 home。
///
/// workflow #11 闭合:Win 优先 USERPROFILE(Python sidecar 用 Path.home() 也走 USERPROFILE),
/// 否则 Git for Windows 用户的 HOME=/c/Users/x(POSIX 风)跟 sidecar 的 C:\Users\x 算到两份
/// 不同路径,sidecar 永远读不到 pending file → updater banner 永远不出。
fn write_updater_pending(version: &str) {
    #[cfg(windows)]
    let home = std::env::var_os("USERPROFILE").or_else(|| std::env::var_os("HOME"));
    #[cfg(not(windows))]
    let home = std::env::var_os("HOME").or_else(|| std::env::var_os("USERPROFILE"));
    let Some(home) = home else { return };
    let dir = std::path::PathBuf::from(home).join(".human-ai");
    let path = dir.join(".updater-pending.json");
    let _ = std::fs::create_dir_all(&dir);
    let payload = serde_json::json!({ "version": version });
    // A-H4: atomic tmp + rename。直接 fs::write 中途崩 / 半写 = sidecar 读损坏 JSON
    // 进入 unlink 失败路径 → pending banner 永久卡。tmp+rename POSIX/Win 都 atomic。
    let tmp = path.with_extension("json.tmp");
    let write_res = std::fs::write(&tmp, payload.to_string())
        .and_then(|_| std::fs::rename(&tmp, &path));
    match write_res {
        Ok(_) => log::info!("[updater] pending 文件已写(atomic): {path:?}"),
        Err(e) => {
            let _ = std::fs::remove_file(&tmp); // 残留 tmp 清掉
            log::warn!("[updater] write pending file 失败: {e}");
        }
    }
}

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
        // workflow #7 闭合:pkill -f 是 substring 匹配 → 会误杀任意 argv 含 "gateway-server"
        // 的进程(包括用户在 IDE/shell 里编辑的同名文件 / 编译命令)。改 -x 精确进程名匹配。
        let _ = std::process::Command::new("pkill")
            .args(["-9", "-x", "gateway-server"])
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
        // T9 自动更新:启动后台 check yanpai /updates/latest.json,minisign 验签
        // 后下载新 binary;走 feedback-sink 同 host(国内直连稳)
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .setup(|app| {
            // T4 自启 sidecar:动态空闲端口 + headless(GATEWAY_NO_OPEN=1)。
            // 用动态端口后,上次崩溃的孤儿占着旧口也不影响 —— 不在启动时杀(那会跟新 spawn 抢资源),
            // 退出时才清(见下 ExitRequested)。
            let port = pick_free_port();
            // 启动 5s 后后台 check 更新(不阻塞窗口建,失败 silent)
            // 传 port 进去,download 完了好 POST sidecar /api/updater/installed
            let handle = app.handle().clone();
            let updater_port = port;
            tauri::async_runtime::spawn(async move {
                tokio::time::sleep(Duration::from_secs(5)).await;
                check_for_updates(handle, updater_port).await;
            });
            let sidecar = app
                .shell()
                .sidecar("gateway-server")
                .expect("sidecar 'gateway-server' 没找到(跑 build-sidecar.sh)")
                .env("GATEWAY_NO_OPEN", "1")
                .env("GATEWAY_PORT", port.to_string());
            let (mut rx, child) = sidecar.spawn().expect("spawn sidecar 失败");
            // ① 排空 sidecar stdout/stderr — PyInstaller Win bootstrap 写一坨 debug 到
            //    stderr,如果没人 read rx 这个 channel,pipe buffer (Win 64KB) 满了
            //    sidecar 会 block 在 write syscall → uvicorn 永远起不来。
            //    0.1.7/0.1.8 Win Tauri 5 轮 smoke 卡这条的真因。
            // ② sidecar 死了 (auto-update / 用户 /api/quit / crash) → Tauri 主进程
            //    跟着退出,防"banner 立即重启 → /api/quit → sidecar 死 → Tauri 还在,
            //    用户看到 ERR_CONNECTION_REFUSED 卡屏"那条断链(self-review R3)。
            let app_handle_for_sidecar = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    if let CommandEvent::Terminated(_) = event {
                        log::info!("[sidecar] terminated → exit Tauri");
                        app_handle_for_sidecar.exit(0);
                        break;
                    }
                    // 其他事件(Stdout/Stderr)只为排空 buffer,不处理
                }
            });
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
            // Tauri 默认在 webview 层注册原生拖放处理器,吞掉 OS 文件 drop → 前端 HTML5
            // dragover/drop 收不到(thread.js 的拖图上传失灵)。禁掉它,让 WKWebView 的
            // HTML5 拖放像浏览器一样直达网页。守铁律:壳侧配置,前端零改、不碰 JS 桥。
            .disable_drag_drop_handler()
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
