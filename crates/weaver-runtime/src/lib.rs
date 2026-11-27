use std::env;
use std::path::PathBuf;

pub const DEFAULT_SOCKET_FILENAME: &str = "weaverd.sock";
pub const DEFAULT_PID_FILENAME: &str = "weaverd.pid";

pub fn runtime_dir() -> PathBuf {
    env::var_os("XDG_RUNTIME_DIR")
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .or_else(|| env::var_os("TMPDIR").map(PathBuf::from))
        .unwrap_or_else(std::env::temp_dir)
}

pub fn default_socket_path() -> PathBuf {
    runtime_dir().join(DEFAULT_SOCKET_FILENAME)
}

pub fn default_pid_file() -> PathBuf {
    runtime_dir().join(DEFAULT_PID_FILENAME)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serial_test::serial;
    use std::ffi::OsString;
    use tempfile::TempDir;

    fn with_env(name: &str, value: Option<OsString>, f: impl FnOnce()) {
        let original = env::var_os(name);
        match value {
            Some(v) => env::set_var(name, v),
            None => env::remove_var(name),
        }
        f();
        match original {
            Some(v) => env::set_var(name, v),
            None => env::remove_var(name),
        }
    }

    #[test]
    #[serial]
    fn runtime_dir_prefers_xdg() {
        let dir = TempDir::new().expect("tempdir");
        with_env("TMPDIR", Some(OsString::from("ignored")), || {
            with_env("XDG_RUNTIME_DIR", Some(dir.path().into()), || {
                let runtime = runtime_dir();
                assert!(runtime.starts_with(dir.path()));
            });
        });
    }

    #[test]
    #[serial]
    fn runtime_dir_falls_back_to_tmpdir() {
        let dir = TempDir::new().expect("tempdir");
        with_env("XDG_RUNTIME_DIR", None, || {
            with_env("TMPDIR", Some(dir.path().into()), || {
                let runtime = runtime_dir();
                assert!(runtime.starts_with(dir.path()));
            });
        });
    }

    #[test]
    #[serial]
    fn defaults_share_runtime_dir() {
        let dir = TempDir::new().expect("tempdir");
        with_env("XDG_RUNTIME_DIR", Some(dir.path().into()), || {
            let socket = default_socket_path();
            let pid = default_pid_file();
            assert!(socket.starts_with(dir.path()));
            assert!(pid.starts_with(dir.path()));
        });
    }
}
