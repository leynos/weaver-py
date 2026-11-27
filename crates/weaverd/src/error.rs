use std::{io, path::PathBuf, sync::Arc};

use ortho_config::OrthoError;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum DaemonError {
    #[error("failed to load configuration: {0}")]
    Config(#[from] Arc<OrthoError>),
    #[error("I/O error at {path}: {source}")]
    Io { path: PathBuf, source: io::Error },
    #[error("daemon already running with pid {pid}")]
    AlreadyRunning { pid: u32 },
    #[error("failed to install signal handler: {0}")]
    Signal(io::Error),
    #[error("runtime initialisation failed: {0}")]
    Runtime(String),
}

impl DaemonError {
    pub(crate) fn io(path: PathBuf, source: io::Error) -> Self {
        Self::Io { path, source }
    }
}
