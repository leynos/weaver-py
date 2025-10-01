use std::env;
use std::path::PathBuf;
use std::time::Duration;

use clap::Parser;
use ortho_config::OrthoConfig;
use serde::{Deserialize, Serialize};
use weaver_runtime::{default_pid_file, default_socket_path};

use crate::error::CliError;

const DEFAULT_STARTUP_SECS: u64 = 10;
const DEFAULT_SHUTDOWN_SECS: u64 = 10;

/// Paths required to locate the daemons IPC socket and PID file.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DaemonPaths {
    pub socket_path: PathBuf,
    pub pid_file: PathBuf,
}

impl DaemonPaths {
    pub fn new(socket_path: PathBuf, pid_file: PathBuf) -> Self {
        Self {
            socket_path,
            pid_file,
        }
    }
}

/// Command-line options for starting the daemon.
#[derive(Debug, Clone, Parser, Deserialize, Serialize, OrthoConfig)]
#[command(about = "Start the weaverd daemon")]
#[ortho_config(prefix = "WEAVER_")]
pub struct StartCommand {
    #[arg(long = "socket-path")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub socket_path: Option<PathBuf>,
    #[arg(long = "pid-file")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pid_file: Option<PathBuf>,
    #[arg(long = "daemon-binary")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub daemon_binary: Option<PathBuf>,
    #[arg(long = "startup-timeout", default_value_t = DEFAULT_STARTUP_SECS)]
    #[serde(default = "StartCommand::default_startup_secs")]
    pub startup_timeout_secs: u64,
    #[arg(long = "shutdown-timeout", default_value_t = DEFAULT_SHUTDOWN_SECS)]
    #[serde(default = "StartCommand::default_shutdown_secs")]
    pub shutdown_timeout_secs: u64,
}

impl StartCommand {
    const DEFAULT_STARTUP: u64 = DEFAULT_STARTUP_SECS;
    const DEFAULT_SHUTDOWN: u64 = DEFAULT_SHUTDOWN_SECS;

    const fn default_startup_secs() -> u64 {
        Self::DEFAULT_STARTUP
    }

    const fn default_shutdown_secs() -> u64 {
        Self::DEFAULT_SHUTDOWN
    }

    pub fn resolve(self) -> Result<StartOptions, CliError> {
        let paths = resolve_paths(self.socket_path, self.pid_file);
        let daemon_binary = self.daemon_binary.unwrap_or_else(default_daemon_binary);
        let startup_timeout = Duration::from_secs(self.startup_timeout_secs.max(1));
        let shutdown_timeout = Duration::from_secs(self.shutdown_timeout_secs.max(1));
        Ok(StartOptions {
            paths,
            daemon_binary,
            startup_timeout,
            shutdown_timeout,
        })
    }
}

impl Default for StartCommand {
    fn default() -> Self {
        Self {
            socket_path: None,
            pid_file: None,
            daemon_binary: None,
            startup_timeout_secs: Self::DEFAULT_STARTUP,
            shutdown_timeout_secs: Self::DEFAULT_SHUTDOWN,
        }
    }
}

/// Command-line options for stopping the daemon.
#[derive(Debug, Clone, Parser, Deserialize, Serialize, OrthoConfig)]
#[command(about = "Stop the running weaverd daemon")]
#[ortho_config(prefix = "WEAVER_")]
pub struct StopCommand {
    #[arg(long = "socket-path")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub socket_path: Option<PathBuf>,
    #[arg(long = "pid-file")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pid_file: Option<PathBuf>,
    #[arg(long = "shutdown-timeout", default_value_t = DEFAULT_SHUTDOWN_SECS)]
    #[serde(default = "StopCommand::default_shutdown_secs")]
    pub shutdown_timeout_secs: u64,
}

impl StopCommand {
    const fn default_shutdown_secs() -> u64 {
        DEFAULT_SHUTDOWN_SECS
    }

    pub fn resolve(self) -> StopOptions {
        let paths = resolve_paths(self.socket_path, self.pid_file);
        let shutdown_timeout = Duration::from_secs(self.shutdown_timeout_secs.max(1));
        StopOptions {
            paths,
            shutdown_timeout,
        }
    }
}

impl Default for StopCommand {
    fn default() -> Self {
        Self {
            socket_path: None,
            pid_file: None,
            shutdown_timeout_secs: DEFAULT_SHUTDOWN_SECS,
        }
    }
}

/// Command-line options for querying daemon status.
#[derive(Debug, Clone, Parser, Deserialize, Serialize, OrthoConfig)]
#[command(about = "Query the daemon status")]
#[ortho_config(prefix = "WEAVER_")]
pub struct StatusCommand {
    #[arg(long = "socket-path")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub socket_path: Option<PathBuf>,
    #[arg(long = "pid-file")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pid_file: Option<PathBuf>,
}

impl StatusCommand {
    pub fn resolve(self) -> StatusOptions {
        let paths = resolve_paths(self.socket_path, self.pid_file);
        StatusOptions { paths }
    }
}

impl Default for StatusCommand {
    fn default() -> Self {
        Self {
            socket_path: None,
            pid_file: None,
        }
    }
}

/// Fully-resolved options required to start the daemon.
#[derive(Debug, Clone)]
pub struct StartOptions {
    pub paths: DaemonPaths,
    pub daemon_binary: PathBuf,
    pub startup_timeout: Duration,
    pub shutdown_timeout: Duration,
}

/// Fully-resolved options required to stop the daemon.
#[derive(Debug, Clone)]
pub struct StopOptions {
    pub paths: DaemonPaths,
    pub shutdown_timeout: Duration,
}

/// Options for querying daemon status.
#[derive(Debug, Clone)]
pub struct StatusOptions {
    pub paths: DaemonPaths,
}

fn resolve_paths(socket_path: Option<PathBuf>, pid_file: Option<PathBuf>) -> DaemonPaths {
    let socket_path = socket_path.unwrap_or_else(default_socket_path);
    let pid_file = pid_file.unwrap_or_else(default_pid_file);
    DaemonPaths::new(socket_path, pid_file)
}

fn default_daemon_binary() -> PathBuf {
    const BIN_NAME: &str = "weaverd";
    let current = env::current_exe().ok();
    if let Some(dir) = current.as_ref().and_then(|p| p.parent()) {
        let candidate = dir.join(BIN_NAME);
        if candidate.exists() {
            return candidate;
        }
        #[cfg(windows)]
        {
            let exe = dir.join(format!("{BIN_NAME}.exe"));
            if exe.exists() {
                return exe;
            }
        }
    }
    PathBuf::from(BIN_NAME)
}

fn _assert_send_sync<T: Send + Sync>() {}

#[cfg(test)]
mod tests {
    use super::*;
    use serial_test::serial;
    use std::ffi::OsString;
    use tempfile::TempDir;

    fn with_env_var(name: &str, value: Option<OsString>, f: impl FnOnce()) {
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
    fn defaults_respect_xdg_runtime_dir() {
        let dir = TempDir::new().expect("tempdir");
        let expected = dir.path().to_path_buf();
        with_env_var(
            "XDG_RUNTIME_DIR",
            Some(expected.clone().into_os_string()),
            || {
                let socket = weaver_runtime::default_socket_path();
                assert!(socket.starts_with(&expected));
                let pid = weaver_runtime::default_pid_file();
                assert!(pid.starts_with(&expected));
            },
        );
    }

    #[test]
    #[serial]
    fn resolve_start_command_falls_back_to_defaults() {
        let dir = TempDir::new().expect("tempdir");
        with_env_var("XDG_RUNTIME_DIR", Some(dir.path().into()), || {
            let opts = StartCommand::default()
                .resolve()
                .expect("resolve start options");
            assert!(opts.paths.socket_path.exists() || !opts.paths.socket_path.exists());
            assert!(opts.paths.socket_path.starts_with(dir.path()));
            assert!(opts.paths.pid_file.starts_with(dir.path()));
            assert_eq!(
                opts.startup_timeout,
                Duration::from_secs(DEFAULT_STARTUP_SECS)
            );
            assert_eq!(
                opts.shutdown_timeout,
                Duration::from_secs(DEFAULT_SHUTDOWN_SECS)
            );
        });
    }

    #[test]
    #[serial]
    fn stop_command_uses_defaults() {
        let dir = TempDir::new().expect("tempdir");
        with_env_var("XDG_RUNTIME_DIR", Some(dir.path().into()), || {
            let opts = StopCommand::default().resolve();
            assert!(opts.paths.socket_path.starts_with(dir.path()));
            assert!(opts.paths.pid_file.starts_with(dir.path()));
            assert_eq!(
                opts.shutdown_timeout,
                Duration::from_secs(DEFAULT_SHUTDOWN_SECS)
            );
        });
    }
}
