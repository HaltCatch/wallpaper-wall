#![cfg_attr(target_os = "windows", windows_subsystem = "windows")]

use std::collections::hash_map::DefaultHasher;
use std::env;
use std::fs;
use std::hash::{Hash, Hasher};
use std::path::{Path, PathBuf};
use std::process::Command;
#[cfg(target_os = "windows")]
use std::process::Stdio;

type Result<T> = std::result::Result<T, String>;
const MAX_REMOTE_IMAGE_BYTES: u64 = 100 * 1024 * 1024;

fn main() {
    if let Err(error) = run() {
        error_notice(&error);
        eprintln!("Wallpaper Wall: {error}");
        std::process::exit(1);
    }
}

#[cfg(target_os = "windows")]
fn install_notice() {
    use std::ptr::null;
    #[link(name = "user32")]
    extern "system" { fn MessageBoxW(window: *const std::ffi::c_void, text: *const u16, caption: *const u16, kind: u32) -> i32; }
    let text: Vec<u16> = "壁纸助手已安装。\n\n现在回到 Wallpaper Wall，打开任意壁纸并点击 ⌘ 即可设为桌面壁纸。".encode_utf16().chain(Some(0)).collect();
    let caption: Vec<u16> = "Wallpaper Wall".encode_utf16().chain(Some(0)).collect();
    unsafe { MessageBoxW(null(), text.as_ptr(), caption.as_ptr(), 0x0000_0040); }
}

#[cfg(target_os = "windows")]
fn uninstall_notice() {
    use std::ptr::null;
    #[link(name = "user32")]
    extern "system" { fn MessageBoxW(window: *const std::ffi::c_void, text: *const u16, caption: *const u16, kind: u32) -> i32; }
    let text: Vec<u16> = "壁纸助手已卸载。\n\n网页将不再能唤起 wallpaperwall://。".encode_utf16().chain(Some(0)).collect();
    let caption: Vec<u16> = "Wallpaper Wall".encode_utf16().chain(Some(0)).collect();
    unsafe { MessageBoxW(null(), text.as_ptr(), caption.as_ptr(), 0x0000_0040); }
}

#[cfg(target_os = "windows")]
fn error_notice(error: &str) {
    use std::ptr::null;
    #[link(name = "user32")]
    extern "system" { fn MessageBoxW(window: *const std::ffi::c_void, text: *const u16, caption: *const u16, kind: u32) -> i32; }
    let text: Vec<u16> = format!("壁纸未设置。\n\n{error}").encode_utf16().chain(Some(0)).collect();
    let caption: Vec<u16> = "Wallpaper Wall".encode_utf16().chain(Some(0)).collect();
    unsafe { MessageBoxW(null(), text.as_ptr(), caption.as_ptr(), 0x0000_0010); }
}

#[cfg(target_os = "macos")]
fn macos_dialog(message: &str, title: &str) {
    let script = "on run argv\ndisplay dialog (item 1 of argv) with title (item 2 of argv) buttons {\"好\"} default button 1\nend run";
    let _ = Command::new("osascript")
        .args(["-e", script, "--", message, title])
        .status();
}

#[cfg(target_os = "macos")]
fn install_notice() {
    macos_dialog(
        "壁纸助手已安装。\n\n现在回到 Wallpaper Wall，打开任意壁纸并点击 ⌘ 即可设为桌面壁纸。",
        "Wallpaper Wall",
    );
}

#[cfg(target_os = "macos")]
fn uninstall_notice() {
    macos_dialog("壁纸助手已卸载。", "Wallpaper Wall");
}

#[cfg(target_os = "macos")]
fn error_notice(error: &str) {
    macos_dialog(&format!("壁纸未设置。\n\n{error}"), "Wallpaper Wall");
}

#[cfg(not(any(target_os = "windows", target_os = "macos")))]
fn install_notice() {}

#[cfg(not(any(target_os = "windows", target_os = "macos")))]
fn uninstall_notice() {}

#[cfg(not(any(target_os = "windows", target_os = "macos")))]
fn error_notice(_: &str) {}

fn run() -> Result<()> {
    let mut args = env::args().skip(1);
    // A downloaded agent is intentionally a one-double-click installer on
    // Windows. Explicit help remains available from a terminal.
    let command = args.next().unwrap_or_else(|| "install".into());
    match command.as_str() {
        "install" => install_protocol(),
        "uninstall" => uninstall_protocol(),
        "set" => set_from_source(&args.next().ok_or("缺少图片链接或文件路径")?),
        value if value.starts_with("wallpaperwall://") => set_from_protocol(value),
        "help" | "--help" | "-h" => {
            println!("Wallpaper Wall Agent\n\n  install                 注册 wallpaperwall:// 协议\n  uninstall               注销协议\n  set <url-or-path>       下载或使用本地图片并设置壁纸\n");
            Ok(())
        }
        _ => Err("未知命令；使用 --help 查看帮助".into()),
    }
}

fn set_from_protocol(uri: &str) -> Result<()> {
    let query = uri.split_once('?').map(|(_, value)| value).unwrap_or_default();
    let source = query_value(query, "source").ok_or("协议链接中没有图片 source")?;
    set_from_source(&source)
}

fn query_value(query: &str, name: &str) -> Option<String> {
    query.split('&').find_map(|entry| {
        let (key, value) = entry.split_once('=')?;
        (key == name).then(|| percent_decode(value))
    })
}

fn percent_decode(value: &str) -> String {
    let mut result = Vec::with_capacity(value.len());
    let bytes = value.as_bytes();
    let mut index = 0;
    while index < bytes.len() {
        if bytes[index] == b'%' && index + 2 < bytes.len() {
            if let (Some(high), Some(low)) = (hex(bytes[index + 1]), hex(bytes[index + 2])) {
                result.push(high * 16 + low);
                index += 3;
                continue;
            }
        }
        result.push(if bytes[index] == b'+' { b' ' } else { bytes[index] });
        index += 1;
    }
    String::from_utf8_lossy(&result).into_owned()
}

fn hex(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        b'A'..=b'F' => Some(value - b'A' + 10),
        _ => None,
    }
}

fn set_from_source(source: &str) -> Result<()> {
    let image = resolve_image(source)?;
    set_wallpaper(&image)?;
    // Desktop environments may keep using the selected file after the API call,
    // so retain exactly that one cached original and remove every previous one.
    prune_cache_except(&image)?;
    println!("已设为壁纸：{}", image.display());
    Ok(())
}

fn prune_cache_except(current: &Path) -> Result<()> {
    let cache = cache_dir();
    if !cache.exists() {
        return Ok(());
    }
    for entry in fs::read_dir(&cache).map_err(|error| format!("无法读取缓存目录：{error}"))? {
        let path = entry.map_err(|error| error.to_string())?.path();
        if path != current && path.is_file() {
            fs::remove_file(path).map_err(|error| format!("无法清理旧壁纸缓存：{error}"))?;
        }
    }
    Ok(())
}

fn resolve_image(source: &str) -> Result<PathBuf> {
    if let Some(path) = source.strip_prefix("file://") {
        let file = PathBuf::from(percent_decode(path));
        return file.exists().then_some(file).ok_or("本地图片不存在".into());
    }
    let local = PathBuf::from(source);
    if local.exists() {
        return Ok(local);
    }
    let host = validate_remote_source(source)?;

    let cache = cache_dir();
    fs::create_dir_all(&cache).map_err(|error| format!("无法创建缓存目录：{error}"))?;
    let mut hasher = DefaultHasher::new();
    source.hash(&mut hasher);
    let extension = source
        .split('?').next().and_then(|path| Path::new(path).extension())
        .and_then(|value| value.to_str())
        .filter(|value| matches!(value.to_ascii_lowercase().as_str(), "jpg" | "jpeg" | "png" | "webp" | "bmp" | "avif"))
        .ok_or("图片链接必须以 jpg、png、webp、bmp 或 avif 文件扩展名结尾")?;
    let target = cache.join(format!("{:016x}.{extension}", hasher.finish()));
    if target.exists() && !is_supported_image_file(&target) {
        let _ = fs::remove_file(&target);
    }
    if !target.exists() || target.metadata().map(|meta| meta.len()).unwrap_or(0) == 0 {
        let status = background_command("curl")
            .args(["--fail", "--location", "--silent", "--show-error", "--connect-timeout", "10", "--max-time", "120", "--max-filesize", "104857600", "--proto", "=http,https", "--proto-redir", "=http,https", "--output"])
            .arg(&target)
            .arg(source)
            .status()
            .map_err(|error| format!("无法启动 curl 下载图片：{error}"))?;
        if !status.success() {
            let _ = fs::remove_file(&target);
            return Err("下载图片失败".into());
        }
        let size = target.metadata().map_err(|error| format!("无法读取下载图片：{error}"))?.len();
        if size == 0 || size > MAX_REMOTE_IMAGE_BYTES {
            let _ = fs::remove_file(&target);
            return Err("下载图片为空或超过 100 MB 限制".into());
        }
    }
    if !is_supported_image_file(&target) {
        let _ = fs::remove_file(&target);
        return Err("下载结果不是有效图片（可能被登录页、鉴权页或错误页替换）".into());
    }
    let _ = host; // Parsed before downloading so a malformed URL is never passed to curl.
    Ok(target)
}

fn is_supported_image_file(path: &Path) -> bool {
    let Ok(bytes) = fs::read(path) else { return false; };
    let png = bytes.starts_with(b"\x89PNG\r\n\x1a\n");
    let jpeg = bytes.starts_with(&[0xff, 0xd8, 0xff]);
    let webp = bytes.len() >= 12 && &bytes[..4] == b"RIFF" && &bytes[8..12] == b"WEBP";
    let bmp = bytes.starts_with(b"BM");
    let avif = bytes.len() >= 12 && &bytes[4..8] == b"ftyp"
        && bytes[8..].windows(4).any(|brand| matches!(brand, b"avif" | b"avis" | b"mif1"));
    png || jpeg || webp || bmp || avif
}

fn validate_remote_source(source: &str) -> Result<String> {
    let (scheme, rest) = source.split_once("://").ok_or("只接受 http(s) 图片链接或本地文件路径")?;
    if scheme != "https" && scheme != "http" {
        return Err("只接受 http(s) 图片链接或本地文件路径".into());
    }
    let authority = rest.split(['/', '?', '#']).next().unwrap_or_default().rsplit('@').next().unwrap_or_default();
    let host = authority
        .strip_prefix('[')
        .and_then(|value| value.split(']').next())
        .unwrap_or_else(|| authority.split(':').next().unwrap_or_default())
        .to_ascii_lowercase();
    if host.is_empty() {
        return Err("图片链接缺少主机名".into());
    }
    if scheme == "http" && !is_local_host(&host) {
        return Err("非本地图片必须使用 HTTPS".into());
    }
    if let Some(allowed) = env::var("WALLPAPERWALL_ALLOWED_HOSTS").ok().filter(|value| !value.trim().is_empty()) {
        let permitted = allowed.split(',').map(str::trim).any(|rule| {
            let rule = rule.to_ascii_lowercase();
            host == rule || rule.strip_prefix("*.").is_some_and(|suffix| host.ends_with(&format!(".{suffix}")))
        });
        if !permitted {
            return Err("图片主机不在 WALLPAPERWALL_ALLOWED_HOSTS 白名单中".into());
        }
    }
    Ok(host)
}

fn is_local_host(host: &str) -> bool {
    if host == "localhost" || host == "::1" {
        return true;
    }
    // Prefix string checks are spoofable: "10.evil.com" or "192.168.evil.com"
    // are perfectly registrable public DNS names. Only a full literal IPv4
    // address may qualify for the private/loopback exemption.
    let mut parts = host.split('.');
    let mut octets = [0u8; 4];
    for slot in &mut octets {
        match parts.next().and_then(|part| part.parse::<u8>().ok()) {
            Some(value) => *slot = value,
            None => return false,
        }
    }
    if parts.next().is_some() {
        return false;
    }
    octets[0] == 127
        || octets[0] == 10
        || (octets[0] == 192 && octets[1] == 168)
        || (octets[0] == 172 && (16..=31).contains(&octets[1]))
}

fn background_command(program: &str) -> Command {
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        let mut command = Command::new(program);
        command.creation_flags(0x08000000); // CREATE_NO_WINDOW
        return command;
    }
    #[cfg(not(target_os = "windows"))]
    Command::new(program)
}

fn cache_dir() -> PathBuf {
    #[cfg(target_os = "windows")]
    {
        return env::var_os("LOCALAPPDATA").map(PathBuf::from).unwrap_or_else(env::temp_dir).join("WallpaperWall").join("cache");
    }
    #[cfg(target_os = "macos")]
    {
        return env::var_os("HOME").map(PathBuf::from).unwrap_or_else(env::temp_dir).join("Library").join("Caches").join("WallpaperWall");
    }
    #[cfg(target_os = "linux")]
    {
        return env::var_os("XDG_CACHE_HOME").map(PathBuf::from).or_else(|| env::var_os("HOME").map(|home| PathBuf::from(home).join(".cache"))).unwrap_or_else(env::temp_dir).join("wallpaper-wall");
    }
    #[allow(unreachable_code)]
    env::temp_dir().join("wallpaper-wall")
}

#[cfg(target_os = "windows")]
fn set_wallpaper(path: &Path) -> Result<()> {
    use std::ffi::c_void;
    use std::os::windows::ffi::OsStrExt;
    #[link(name = "user32")]
    extern "system" {
        fn SystemParametersInfoW(action: u32, parameter: u32, value: *mut c_void, flags: u32) -> i32;
    }
    let _ = background_command("reg").args(["add", "HKCU\\Control Panel\\Desktop", "/v", "WallpaperStyle", "/t", "REG_SZ", "/d", "10", "/f"]).stdout(Stdio::null()).status();
    let _ = background_command("reg").args(["add", "HKCU\\Control Panel\\Desktop", "/v", "TileWallpaper", "/t", "REG_SZ", "/d", "0", "/f"]).stdout(Stdio::null()).status();
    let mut wide: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
    let changed = unsafe { SystemParametersInfoW(0x0014, 0, wide.as_mut_ptr().cast(), 0x0001 | 0x0002) };
    (changed != 0).then_some(()).ok_or("Windows 拒绝设置此图片；请确认图片格式与路径可用".into())
}

#[cfg(target_os = "macos")]
fn set_wallpaper(path: &Path) -> Result<()> {
    let script = "on run argv\n tell application \"System Events\" to tell every desktop to set picture to POSIX file (item 1 of argv)\nend run";
    let status = Command::new("osascript").args(["-e", script, "--"]).arg(path).status().map_err(|error| format!("无法启动 osascript：{error}"))?;
    status.success().then_some(()).ok_or("macOS 拒绝设置壁纸；请在系统提示中允许自动化权限".into())
}

#[cfg(target_os = "linux")]
fn set_wallpaper(path: &Path) -> Result<()> {
    let uri = format!("file://{}", path.display());
    let desktop = env::var("XDG_CURRENT_DESKTOP").unwrap_or_default().to_ascii_lowercase();
    if desktop.contains("gnome") || desktop.contains("cinnamon") || desktop.contains("mate") {
        let schema = if desktop.contains("cinnamon") { "org.cinnamon.desktop.background" } else if desktop.contains("mate") { "org.mate.desktop.background" } else { "org.gnome.desktop.background" };
        command_success("gsettings", &["set", schema, "picture-uri", &uri])?;
        if schema == "org.gnome.desktop.background" { let _ = command_success("gsettings", &["set", schema, "picture-uri-dark", &uri]); }
        return Ok(());
    }
    if desktop.contains("kde") || desktop.contains("plasma") {
        let quoted = format!("{:?}", uri);
        let script = format!("var ds=desktops();for(var i=0;i<ds.length;i++){{var d=ds[i];d.wallpaperPlugin='org.kde.image';d.currentConfigGroup=['Wallpaper','org.kde.image','General'];d.writeConfig('Image',{quoted});}}");
        return command_success("qdbus", &["org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript", &script]);
    }
    if desktop.contains("xfce") {
        let output = Command::new("xfconf-query").args(["-c", "xfce4-desktop", "-l"]).output().map_err(|error| format!("无法启动 xfconf-query：{error}"))?;
        for property in String::from_utf8_lossy(&output.stdout).lines().filter(|item| item.ends_with("last-image")) {
            command_success("xfconf-query", &["-c", "xfce4-desktop", "-p", property, "-s", path.to_string_lossy().as_ref()])?;
        }
        return Ok(());
    }
    Err("尚未识别此 Linux 桌面环境；当前支持 GNOME、KDE Plasma 与 Xfce".into())
}

#[cfg(not(any(target_os = "windows", target_os = "macos", target_os = "linux")))]
fn set_wallpaper(_: &Path) -> Result<()> { Err("此操作系统暂不受支持".into()) }

#[cfg(any(target_os = "windows", target_os = "linux", target_os = "macos"))]
fn command_success(program: &str, args: &[&str]) -> Result<()> {
    let status = Command::new(program).args(args).status().map_err(|error| format!("无法启动 {program}：{error}"))?;
    status.success().then_some(()).ok_or_else(|| format!("{program} 执行失败"))
}

#[cfg(test)]
mod tests {
    use super::{is_local_host, validate_remote_source};

    #[test]
    fn permits_https_and_local_http_sources() {
        assert_eq!(validate_remote_source("https://wallpapers.example/image.png").unwrap(), "wallpapers.example");
        assert_eq!(validate_remote_source("http://192.168.1.9/image.png").unwrap(), "192.168.1.9");
    }

    #[test]
    fn blocks_non_local_http_sources() {
        assert!(validate_remote_source("http://wallpapers.example/image.png").is_err());
        assert!(!is_local_host("172.32.0.1"));
        assert!(is_local_host("172.20.0.1"));
    }

    #[test]
    fn rejects_dns_names_that_merely_start_like_private_addresses() {
        assert!(!is_local_host("10.evil.com"));
        assert!(!is_local_host("192.168.evil.com"));
        assert!(!is_local_host("127.0.0.1.evil.com"));
        assert!(is_local_host("127.0.0.1"));
        assert!(is_local_host("10.0.0.5"));
        assert!(is_local_host("192.168.1.9"));
        assert!(validate_remote_source("http://10.evil.com/image.png").is_err());
    }
}

#[cfg(target_os = "windows")]
fn install_protocol() -> Result<()> {
    let executable = env::current_exe().map_err(|error| error.to_string())?;
    let command = format!("\"{}\" \"%1\"", executable.display());
    reg_add("HKCU\\Software\\Classes\\wallpaperwall", None, "URL:Wallpaper Wall Protocol")?;
    reg_add("HKCU\\Software\\Classes\\wallpaperwall", Some("URL Protocol"), "")?;
    reg_add("HKCU\\Software\\Classes\\wallpaperwall\\shell\\open\\command", None, &command)?;
    println!("已注册 wallpaperwall:// 协议（当前用户，无需管理员权限）");
    install_notice();
    Ok(())
}

#[cfg(target_os = "windows")]
fn reg_add(key: &str, name: Option<&str>, value: &str) -> Result<()> {
    let mut command = background_command("reg");
    command.args(["add", key]);
    if let Some(name) = name { command.args(["/v", name]); } else { command.arg("/ve"); }
    let status = command.args(["/d", value, "/f"]).status().map_err(|error| error.to_string())?;
    status.success().then_some(()).ok_or("注册表写入失败".into())
}

#[cfg(target_os = "windows")]
fn uninstall_protocol() -> Result<()> {
    command_success("reg", &["delete", "HKCU\\Software\\Classes\\wallpaperwall", "/f"])?;
    uninstall_notice();
    Ok(())
}

#[cfg(target_os = "macos")]
fn install_protocol() -> Result<()> {
    // macOS delivers protocol URLs as Apple Events, never as argv, so a plain
    // CLI binary inside an app bundle can register the scheme yet still never
    // receive the link. The installer therefore compiles a tiny AppleScript
    // applet — its runtime natively handles `on open location` — which relays
    // the URL to the real agent binary stored inside the bundle.
    let home = env::var_os("HOME").ok_or("无法确定 HOME")?;
    let applications = PathBuf::from(&home).join("Applications");
    let bundle = applications.join("WallpaperWall.app");
    if bundle.exists() {
        let _ = register_macos_bundle(&bundle, true);
        fs::remove_dir_all(&bundle).map_err(|error| format!("无法移除旧的协议助手：{error}"))?;
    }
    fs::create_dir_all(&applications).map_err(|error| error.to_string())?;

    let agent_target = bundle.join("Contents").join("Resources").join("wallpaperwall-agent");
    let script = format!(
        "on open location theURL\n    with timeout of 3600 seconds\n        do shell script quoted form of \"{}\" & \" \" & quoted form of theURL\n    end timeout\nend open location\n",
        applescript_escape(&agent_target.to_string_lossy()),
    );
    let cache = cache_dir();
    fs::create_dir_all(&cache).map_err(|error| error.to_string())?;
    let script_path = cache.join("wallpaperwall-install.applescript");
    fs::write(&script_path, script).map_err(|error| error.to_string())?;
    command_success("osacompile", &["-o", &bundle.to_string_lossy(), &script_path.to_string_lossy()])?;
    let _ = fs::remove_file(&script_path);

    let executable = env::current_exe().map_err(|error| error.to_string())?;
    fs::create_dir_all(agent_target.parent().unwrap()).map_err(|error| error.to_string())?;
    fs::copy(&executable, &agent_target).map_err(|error| error.to_string())?;
    ensure_macos_executable(&agent_target)?;
    // A browser-downloaded agent carries com.apple.quarantine; Gatekeeper
    // would refuse to run the unsigned copy inside the bundle. The user has
    // explicitly run the installer, so clear the flag on the installed copy.
    let _ = Command::new("xattr").args(["-d", "com.apple.quarantine"]).arg(&agent_target).status();

    register_url_scheme(&bundle)?;
    // Plist edits break the applet's seal; a fresh ad-hoc signature keeps
    // LaunchServices happy on Apple Silicon.
    let _ = Command::new("codesign").args(["--force", "--sign", "-"]).arg(&bundle).status();
    register_macos_bundle(&bundle, false)?;
    install_notice();
    Ok(())
}

#[cfg(target_os = "macos")]
fn applescript_escape(value: &str) -> String {
    value.replace('\\', "\\\\").replace('"', "\\\"")
}

#[cfg(target_os = "macos")]
fn register_url_scheme(bundle: &Path) -> Result<()> {
    let plist = bundle.join("Contents").join("Info.plist");
    let plist = plist.to_string_lossy();
    // Merge into the osacompile-generated plist instead of replacing it, so
    // the applet runtime keys survive. Delete-then-add keeps reinstalls clean.
    for delete in ["CFBundleURLTypes", "CFBundleIdentifier", "LSUIElement", "NSAppleEventsUsageDescription"] {
        let _ = Command::new("/usr/libexec/PlistBuddy").args(["-c", &format!("Delete :{delete}"), &plist]).output();
    }
    let additions = [
        "Add :CFBundleIdentifier string click.cyberdeck.wallpaperwall.agent".to_string(),
        "Add :LSUIElement bool true".to_string(),
        "Add :NSAppleEventsUsageDescription string Wallpaper Wall 需要控制系统事件以设置桌面壁纸。".to_string(),
        "Add :CFBundleURLTypes array".to_string(),
        "Add :CFBundleURLTypes:0 dict".to_string(),
        "Add :CFBundleURLTypes:0:CFBundleTypeRole string Viewer".to_string(),
        "Add :CFBundleURLTypes:0:CFBundleURLName string click.cyberdeck.wallpaperwall".to_string(),
        "Add :CFBundleURLTypes:0:CFBundleURLSchemes array".to_string(),
        "Add :CFBundleURLTypes:0:CFBundleURLSchemes:0 string wallpaperwall".to_string(),
    ];
    for addition in &additions {
        command_success("/usr/libexec/PlistBuddy", &["-c", addition, &plist])?;
    }
    Ok(())
}

#[cfg(target_os = "macos")]
fn ensure_macos_executable(path: &Path) -> Result<()> {
    use std::os::unix::fs::PermissionsExt;
    let mut permissions = fs::metadata(path).map_err(|error| error.to_string())?.permissions();
    permissions.set_mode(0o755);
    fs::set_permissions(path, permissions).map_err(|error| error.to_string())
}

#[cfg(target_os = "linux")]
fn install_protocol() -> Result<()> {
    let home = env::var_os("HOME").ok_or("无法确定 HOME")?;
    let target = PathBuf::from(home).join(".local/share/applications/wallpaperwall.desktop");
    fs::create_dir_all(target.parent().unwrap()).map_err(|error| error.to_string())?;
    let executable = env::current_exe().map_err(|error| error.to_string())?;
    fs::write(&target, format!("[Desktop Entry]\nType=Application\nName=Wallpaper Wall\nExec=\"{}\" %u\nNoDisplay=true\nMimeType=x-scheme-handler/wallpaperwall;\n", executable.display())).map_err(|error| error.to_string())?;
    command_success("xdg-mime", &["default", "wallpaperwall.desktop", "x-scheme-handler/wallpaperwall"])
}

#[cfg(target_os = "macos")]
fn uninstall_protocol() -> Result<()> {
    let home = env::var_os("HOME").ok_or("无法确定 HOME")?;
    let app = PathBuf::from(home).join("Applications").join("WallpaperWall.app");
    // Unregistering is best effort: a failed lsregister call must not leave the
    // bundle behind, or uninstall could never complete.
    if app.exists() { let _ = register_macos_bundle(&app, true); }
    if app.exists() { fs::remove_dir_all(app).map_err(|error| error.to_string())?; }
    uninstall_notice();
    Ok(())
}

#[cfg(target_os = "macos")]
fn register_macos_bundle(bundle: &Path, unregister: bool) -> Result<()> {
    let lsregister = "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister";
    let mut command = Command::new(lsregister);
    command.arg(if unregister { "-u" } else { "-f" }).arg(bundle);
    let status = command.status().map_err(|error| format!("无法注册 macOS 协议助手：{error}"))?;
    status.success().then_some(()).ok_or("macOS 协议注册失败".into())
}

#[cfg(target_os = "linux")]
fn uninstall_protocol() -> Result<()> {
    let home = env::var_os("HOME").ok_or("无法确定 HOME")?;
    let desktop = PathBuf::from(home).join(".local/share/applications/wallpaperwall.desktop");
    if desktop.exists() { fs::remove_file(desktop).map_err(|error| error.to_string())?; }
    Ok(())
}

#[cfg(not(any(target_os = "windows", target_os = "macos", target_os = "linux")))]
fn uninstall_protocol() -> Result<()> { Err("此操作系统暂不受支持".into()) }
