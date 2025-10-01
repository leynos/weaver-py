use std::fs;
use std::io::{self, ErrorKind};
use std::path::PathBuf;
use std::sync::Arc;

use serde::Serialize;
use serde_json::json;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::{UnixListener, UnixStream};
use tokio::signal::unix::{signal, SignalKind};
use tokio::sync::Notify;

use crate::config::ResolvedDaemonConfig;
use crate::error::DaemonError;
use crate::pid_file::PidFileGuard;

pub struct WeaverDaemon {
    config: ResolvedDaemonConfig,
}

impl WeaverDaemon {
    pub fn new(config: ResolvedDaemonConfig) -> Self {
        Self { config }
    }

    pub async fn run(self) -> Result<(), DaemonError> {
        let pid_guard = PidFileGuard::acquire(self.config.pid_file.clone())?;
        let (listener, socket_guard) = bind_listener(self.config.socket_path.clone())?;
        let state = Arc::new(DaemonState {
            config: self.config.clone(),
            notify: Notify::new(),
            pid: std::process::id(),
        });

        let mut term = signal(SignalKind::terminate()).map_err(DaemonError::Signal)?;
        let mut interrupt = signal(SignalKind::interrupt()).map_err(DaemonError::Signal)?;

        loop {
            tokio::select! {
                Ok((stream, _)) = listener.accept() => {
                    let inner = Arc::clone(&state);
                    tokio::spawn(async move {
                        if let Err(err) = handle_client(stream, inner).await {
                            eprintln!("client error: {err}");
                        }
                    });
                }
                _ = state.notify.notified() => break,
                _ = term.recv() => break,
                _ = interrupt.recv() => break,
            }
        }

        drop(socket_guard);
        drop(pid_guard);
        Ok(())
    }
}

struct DaemonState {
    config: ResolvedDaemonConfig,
    notify: Notify,
    pid: u32,
}

#[derive(Serialize)]
struct StatusPayload {
    status: &'static str,
    pid: u32,
    socket_path: PathBuf,
}

async fn handle_client(stream: UnixStream, state: Arc<DaemonState>) -> io::Result<()> {
    let mut reader = BufReader::new(stream);
    let mut line = String::new();
    if reader.read_line(&mut line).await? == 0 {
        return Ok(());
    }
    let mut stream = reader.into_inner();
    match line.trim() {
        "STATUS" => {
            let payload = StatusPayload {
                status: "ok",
                pid: state.pid,
                socket_path: state.config.socket_path.clone(),
            };
            write_json(&mut stream, &payload).await
        }
        "SHUTDOWN" => {
            let payload = json!({ "status": "shutting_down" });
            write_json(&mut stream, &payload).await?;
            state.notify.notify_waiters();
            Ok(())
        }
        other => {
            let payload = json!({
                "status": "error",
                "message": format!("unknown command {other}"),
            });
            write_json(&mut stream, &payload).await
        }
    }
}

async fn write_json<T: Serialize>(stream: &mut UnixStream, payload: &T) -> io::Result<()> {
    let mut bytes =
        serde_json::to_vec(payload).map_err(|err| io::Error::new(ErrorKind::Other, err))?;
    bytes.push(b'\n');
    stream.write_all(&bytes).await?;
    stream.flush().await
}

fn bind_listener(path: PathBuf) -> Result<(UnixListener, SocketGuard), DaemonError> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|err| DaemonError::io(parent.to_path_buf(), err))?;
    }
    if path.exists() {
        fs::remove_file(&path).map_err(|err| DaemonError::io(path.clone(), err))?;
    }
    let listener = UnixListener::bind(&path).map_err(|err| DaemonError::io(path.clone(), err))?;
    Ok((listener, SocketGuard { path }))
}

struct SocketGuard {
    path: PathBuf,
}

impl Drop for SocketGuard {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.path);
    }
}
