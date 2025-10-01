use std::fs;
use std::io::{self, Read, Write};
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

use nix::errno::Errno;
use nix::sys::signal::{kill, Signal};
use nix::unistd::Pid;
use serde::Deserialize;

use crate::config::{DaemonPaths, StartOptions, StatusOptions, StopOptions};
use crate::error::CliError;

/// Describes whether the daemon is active and any metadata returned by it.
#[derive(Debug, Clone)]
pub struct DaemonStatus {
    pub running: bool,
    pub pid: Option<u32>,
    pub socket_path: PathBuf,
    pub details: Option<StatusEnvelope>,
}

impl DaemonStatus {
    pub fn summary(&self) -> StatusSummary {
        StatusSummary {
            running: self.running,
            pid: self.pid,
            socket_path: self.socket_path.clone(),
        }
    }
}

/// A condensed view suitable for serialising to users.
#[derive(Debug, Clone, Deserialize, serde::Serialize)]
pub struct StatusSummary {
    pub running: bool,
    pub pid: Option<u32>,
    pub socket_path: PathBuf,
}

#[derive(Debug, Clone, Deserialize)]
pub struct StatusEnvelope {
    pub status: String,
    pub pid: u32,
    pub socket_path: PathBuf,
}

/// Trait abstracting process spawning so tests can inject fakes.
pub trait DaemonSpawner {
    fn spawn(&self, binary: &Path, options: &StartOptions) -> Result<(), io::Error>;
}

#[derive(Debug, Default, Clone, Copy)]
pub struct SystemSpawner;

impl DaemonSpawner for SystemSpawner {
    fn spawn(&self, binary: &Path, options: &StartOptions) -> Result<(), io::Error> {
        let mut command = Command::new(binary);
        command
            .arg("--socket-path")
            .arg(&options.paths.socket_path)
            .arg("--pid-file")
            .arg(&options.paths.pid_file)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        let child = command.spawn()?;
        // We intentionally drop the child handle immediately so the process detaches.
        drop(child);
        Ok(())
    }
}

#[derive(Debug, Default)]
pub struct DaemonController<S: DaemonSpawner = SystemSpawner> {
    spawner: S,
}

impl<S: DaemonSpawner> DaemonController<S> {
    pub fn new(spawner: S) -> Self {
        Self { spawner }
    }

    pub fn start(&self, options: &StartOptions) -> Result<DaemonStatus, CliError> {
        self.ensure_runtime_paths(&options.paths)?;
        match self.status(&StatusOptions {
            paths: options.paths.clone(),
        })? {
            DaemonStatus {
                running: true,
                pid: Some(pid),
                ..
            } => return Err(CliError::AlreadyRunning { pid }),
            _ => {
                self.remove_stale_artifacts(&options.paths)?;
            }
        }

        self.spawner
            .spawn(&options.daemon_binary, options)
            .map_err(|source| CliError::spawn(options.daemon_binary.clone(), source))?;
        self.wait_for_ready(options)?;
        self.status(&StatusOptions {
            paths: options.paths.clone(),
        })
    }

    pub fn stop(&self, options: &StopOptions) -> Result<(), CliError> {
        let status = self.status(&StatusOptions {
            paths: options.paths.clone(),
        })?;
        if !status.running {
            return Err(CliError::NotRunning);
        }

        match self.send_shutdown(&options.paths) {
            Ok(()) => {}
            Err(err) => {
                if let Some(pid) = status.pid {
                    self.signal_terminate(pid)?;
                }
                return Err(err);
            }
        }

        self.wait_for_shutdown(options)?;
        Ok(())
    }

    pub fn status(&self, options: &StatusOptions) -> Result<DaemonStatus, CliError> {
        match read_pid_file(&options.paths.pid_file)? {
            Some(pid) if is_pid_alive(pid) => match self.request_status(&options.paths) {
                Ok(envelope) => Ok(DaemonStatus {
                    running: true,
                    pid: Some(pid),
                    socket_path: options.paths.socket_path.clone(),
                    details: Some(envelope),
                }),
                Err(err) => match err {
                    CliError::Io { .. } => Ok(DaemonStatus {
                        running: true,
                        pid: Some(pid),
                        socket_path: options.paths.socket_path.clone(),
                        details: None,
                    }),
                    other => Err(other),
                },
            },
            Some(_) => {
                self.remove_stale_artifacts(&options.paths)?;
                Ok(DaemonStatus {
                    running: false,
                    pid: None,
                    socket_path: options.paths.socket_path.clone(),
                    details: None,
                })
            }
            None => Ok(DaemonStatus {
                running: false,
                pid: None,
                socket_path: options.paths.socket_path.clone(),
                details: None,
            }),
        }
    }

    fn wait_for_ready(&self, options: &StartOptions) -> Result<(), CliError> {
        let deadline = Instant::now() + options.startup_timeout;
        let status_opts = StatusOptions {
            paths: options.paths.clone(),
        };
        loop {
            if Instant::now() >= deadline {
                return Err(CliError::StartTimeout {
                    timeout: options.startup_timeout,
                });
            }
            if let Ok(status) = self.status(&status_opts) {
                if status.running {
                    return Ok(());
                }
            }
            thread::sleep(Duration::from_millis(100));
        }
    }

    fn wait_for_shutdown(&self, options: &StopOptions) -> Result<(), CliError> {
        let deadline = Instant::now() + options.shutdown_timeout;
        let status_opts = StatusOptions {
            paths: options.paths.clone(),
        };
        loop {
            if Instant::now() >= deadline {
                return Err(CliError::ShutdownTimeout {
                    timeout: options.shutdown_timeout,
                });
            }
            match self.status(&status_opts) {
                Ok(DaemonStatus { running: false, .. }) => return Ok(()),
                Ok(_) | Err(_) => thread::sleep(Duration::from_millis(100)),
            }
        }
    }

    fn ensure_runtime_paths(&self, paths: &DaemonPaths) -> Result<(), CliError> {
        if let Some(parent) = paths.pid_file.parent() {
            fs::create_dir_all(parent).map_err(|err| CliError::io(parent.to_path_buf(), err))?;
        }
        if let Some(parent) = paths.socket_path.parent() {
            fs::create_dir_all(parent).map_err(|err| CliError::io(parent.to_path_buf(), err))?;
        }
        Ok(())
    }

    fn remove_stale_artifacts(&self, paths: &DaemonPaths) -> Result<(), CliError> {
        if paths.pid_file.exists() {
            fs::remove_file(&paths.pid_file)
                .map_err(|err| CliError::io(paths.pid_file.clone(), err))?;
        }
        if paths.socket_path.exists() {
            fs::remove_file(&paths.socket_path)
                .map_err(|err| CliError::io(paths.socket_path.clone(), err))?;
        }
        Ok(())
    }

    fn request_status(&self, paths: &DaemonPaths) -> Result<StatusEnvelope, CliError> {
        let mut stream = UnixStream::connect(&paths.socket_path)
            .map_err(|err| CliError::io(paths.socket_path.clone(), err))?;
        stream
            .write_all(
                b"STATUS
",
            )
            .map_err(|err| CliError::io(paths.socket_path.clone(), err))?;
        stream.shutdown(std::net::Shutdown::Write).ok();
        let mut buf = String::new();
        stream
            .read_to_string(&mut buf)
            .map_err(|err| CliError::io(paths.socket_path.clone(), err))?;
        serde_json::from_str(&buf).map_err(|err| CliError::InvalidStatus(err.to_string()))
    }

    fn send_shutdown(&self, paths: &DaemonPaths) -> Result<(), CliError> {
        let mut stream = UnixStream::connect(&paths.socket_path)
            .map_err(|err| CliError::io(paths.socket_path.clone(), err))?;
        stream
            .write_all(
                b"SHUTDOWN
",
            )
            .map_err(|err| CliError::io(paths.socket_path.clone(), err))?;
        stream.shutdown(std::net::Shutdown::Write).ok();
        let mut buf = String::new();
        stream
            .read_to_string(&mut buf)
            .map_err(|err| CliError::io(paths.socket_path.clone(), err))?;
        if buf.trim().is_empty() {
            return Ok(());
        }
        serde_json::from_str::<serde_json::Value>(&buf)
            .map(|_| ())
            .map_err(|err| CliError::InvalidStatus(err.to_string()))
    }

    fn signal_terminate(&self, pid: u32) -> Result<(), CliError> {
        let pid = Pid::from_raw(pid as i32);
        kill(pid, Signal::SIGTERM)
            .map_err(|err| CliError::invalid_pid(PathBuf::from("pid"), err.to_string()))
    }
}

fn read_pid_file(path: &Path) -> Result<Option<u32>, CliError> {
    match fs::read_to_string(path) {
        Ok(contents) => {
            let pid = contents
                .trim()
                .parse::<u32>()
                .map_err(|err| CliError::invalid_pid(path.to_path_buf(), err.to_string()))?;
            Ok(Some(pid))
        }
        Err(err) if err.kind() == io::ErrorKind::NotFound => Ok(None),
        Err(err) => Err(CliError::io(path.to_path_buf(), err)),
    }
}

fn is_pid_alive(pid: u32) -> bool {
    let raw = pid as i32;
    let pid = Pid::from_raw(raw);
    let alive = match kill(pid, None) {
        Ok(()) => true,
        Err(Errno::EPERM) => true,
        Err(Errno::ESRCH) => false,
        Err(_) => false,
    };
    if !alive {
        return false;
    }
    #[cfg(target_os = "linux")]
    {
        // A stopped daemon briefly becomes a zombie before init reaps it.
        // Treat that transient state as "not running" for status polling.
        let stat_path = Path::new("/proc").join(raw.to_string()).join("stat");
        if let Ok(stat) = fs::read_to_string(stat_path) {
            if stat.split_whitespace().nth(2) == Some("Z") {
                return false;
            }
        }
    }
    true
}


#[cfg(test)]
mod tests {
    use super::*;
    use serial_test::serial;
    use tempfile::TempDir;

    #[test]
    #[serial]
    fn invalid_pid_file_is_reported() {
        let dir = TempDir::new().expect("tempdir");
        let path = dir.path().join("pid");
        fs::write(&path, "not-a-number").expect("write pid");
        let err = read_pid_file(&path).expect_err("should fail");
        assert!(matches!(err, CliError::InvalidPidFile { .. }));
    }

    #[test]
    fn detecting_current_process() {
        let pid = std::process::id();
        assert!(is_pid_alive(pid));
    }

    #[allow(dead_code)]
    struct FakeSpawner {
        path: PathBuf,
        spawned: std::sync::Mutex<Vec<Vec<String>>>,
    }

    #[allow(dead_code)]
    impl FakeSpawner {
        fn new(path: PathBuf) -> Self {
            Self {
                path,
                spawned: std::sync::Mutex::new(Vec::new()),
            }
        }
    }

    impl DaemonSpawner for FakeSpawner {
        fn spawn(&self, binary: &Path, options: &StartOptions) -> Result<(), io::Error> {
            assert_eq!(binary, self.path);
            let mut args = vec![
                "--socket-path".to_string(),
                options.paths.socket_path.display().to_string(),
            ];
            args.push("--pid-file".to_string());
            args.push(options.paths.pid_file.display().to_string());
            self.spawned.lock().expect("lock").push(args);
            Ok(())
        }
    }
}
