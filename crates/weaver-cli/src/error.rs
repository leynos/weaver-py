use std::{io, path::PathBuf, sync::Arc, time::Duration};

use ortho_config::OrthoError;
use thiserror::Error;

/// Errors produced by the `weaver-cli` commands.
#[derive(Debug, Error)]
pub enum CliError {
    /// Configuration parsing failed when loading ortho-config layers.
    #[error("failed to load configuration: {0}")]
    Config(#[from] Arc<OrthoError>),
    /// Attempted to start the daemon when it is already running.
    #[error("daemon already running with pid {pid}")]
    AlreadyRunning { pid: u32 },
    /// Attempted to stop or inspect the daemon when it is not running.
    #[error("daemon is not running")]
    NotRunning,
    /// Failed to spawn the background daemon process.
    #[error("failed to spawn daemon binary at {path}: {source}")]
    Spawn { path: PathBuf, source: io::Error },
    /// Low-level I/O error when interacting with filesystem or IPC resources.
    #[error("I/O error at {path}: {source}")]
    Io { path: PathBuf, source: io::Error },
    /// The daemon PID file existed but contained an invalid value.
    #[error("failed to parse pid file at {path}: {message}")]
    InvalidPidFile { path: PathBuf, message: String },
    /// The daemon failed to become ready within the configured timeout.
    #[error("daemon start timed out after {timeout:?}")]
    StartTimeout { timeout: Duration },
    /// The daemon did not shut down before the timeout elapsed.
    #[error("daemon shutdown timed out after {timeout:?}")]
    ShutdownTimeout { timeout: Duration },
    /// The daemon returned a malformed status payload.
    #[error("status response from daemon was invalid: {0}")]
    InvalidStatus(String),
}

impl CliError {
    /// Helper constructor for spawning failures that captures the target path.
    pub(crate) fn spawn(path: PathBuf, source: io::Error) -> Self {
        Self::Spawn { path, source }
    }

    /// Helper constructor for I/O failures associated with a specific path.
    pub(crate) fn io(path: PathBuf, source: io::Error) -> Self {
        Self::Io { path, source }
    }

    /// Helper constructor for PID parsing failures that preserves context.
    pub(crate) fn invalid_pid(path: PathBuf, message: impl Into<String>) -> Self {
        Self::InvalidPidFile {
            path,
            message: message.into(),
        }
    }
}
