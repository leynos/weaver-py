pub mod config;
pub mod daemon;
pub mod error;
pub mod pid_file;

use crate::config::DaemonArgs;
use crate::daemon::WeaverDaemon;
use crate::error::DaemonError;
use ortho_config::OrthoConfig;

pub fn run() -> Result<(), DaemonError> {
    let args = DaemonArgs::load()?;
    let config = args.resolve();
    let daemon = WeaverDaemon::new(config);
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_io()
        .enable_time()
        .build()
        .map_err(|err| DaemonError::Runtime(err.to_string()))?;
    runtime.block_on(daemon.run())
}
