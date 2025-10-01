use std::env;
use std::path::PathBuf;
use std::time::Duration;

use clap::Parser;
use ortho_config::OrthoConfig;
use serde::{Deserialize, Serialize};

const DEFAULT_SOCKET_FILENAME: &str = "weaverd.sock";
const DEFAULT_PID_FILENAME: &str = "weaverd.pid";
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

fn default_socket_path() -> PathBuf {
    runtime_dir().join(DEFAULT_SOCKET_FILENAME)
}

fn default_pid_file() -> PathBuf {
    runtime_dir().join(DEFAULT_PID_FILENAME)
}

fn runtime_dir() -> PathBuf {
    env::var_os("XDG_RUNTIME_DIR")
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .or_else(|| env::var_os("TMPDIR").map(PathBuf::from))
        .unwrap_or_else(std::env::temp_dir)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serial_test::serial;
    use tempfile::TempDir;

    #[test]
    #[serial]
    fn defaults_use_runtime_dir() {
        let dir = TempDir::new().expect("tempdir");
        env::set_var("XDG_RUNTIME_DIR", dir.path());
        let args = DaemonArgs::default();
        let config = args.resolve();
        assert!(config.socket_path.starts_with(dir.path()));
        assert!(config.pid_file.starts_with(dir.path()));
        env::remove_var("XDG_RUNTIME_DIR");
    }
}
