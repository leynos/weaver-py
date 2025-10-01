use std::path::PathBuf;
use std::time::Duration;

use clap::Parser;
use ortho_config::OrthoConfig;
use serde::{Deserialize, Serialize};
use weaver_runtime::{default_pid_file, default_socket_path};

const DEFAULT_SHUTDOWN_GRACE_SECS: u64 = 5;

#[derive(Debug, Clone, Parser, Deserialize, Serialize, OrthoConfig)]
#[command(name = "weaverd", about = "Weaver daemon process")]
#[ortho_config(prefix = "WEAVERD_")]
pub struct DaemonArgs {
    #[arg(long = "socket-path")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub socket_path: Option<PathBuf>,
    #[arg(long = "pid-file")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pid_file: Option<PathBuf>,
    #[arg(long = "shutdown-grace", default_value_t = DEFAULT_SHUTDOWN_GRACE_SECS)]
    #[serde(default = "DaemonArgs::default_shutdown_grace")]
    pub shutdown_grace_secs: u64,
}

impl DaemonArgs {
    const fn default_shutdown_grace() -> u64 {
        DEFAULT_SHUTDOWN_GRACE_SECS
    }

    pub fn resolve(self) -> ResolvedDaemonConfig {
        let socket_path = self.socket_path.unwrap_or_else(default_socket_path);
        let pid_file = self.pid_file.unwrap_or_else(default_pid_file);
        let shutdown_grace = Duration::from_secs(self.shutdown_grace_secs.max(1));
        ResolvedDaemonConfig {
            socket_path,
            pid_file,
            shutdown_grace,
        }
    }
}

impl Default for DaemonArgs {
    fn default() -> Self {
        Self {
            socket_path: None,
            pid_file: None,
            shutdown_grace_secs: DEFAULT_SHUTDOWN_GRACE_SECS,
        }
    }
}

#[derive(Debug, Clone)]
pub struct ResolvedDaemonConfig {
    pub socket_path: PathBuf,
    pub pid_file: PathBuf,
    pub shutdown_grace: Duration,
}

#[cfg(test)]
mod tests {
    use super::*;
    use serial_test::serial;
    use std::env;
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
    fn defaults_use_runtime_dir() {
        let dir = TempDir::new().expect("tempdir");
        with_env("XDG_RUNTIME_DIR", Some(dir.path().into()), || {
            let args = DaemonArgs::default();
            let config = args.resolve();
            assert!(config.socket_path.starts_with(dir.path()));
            assert!(config.pid_file.starts_with(dir.path()));
        });
    }
}
