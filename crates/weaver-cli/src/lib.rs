pub mod config;
pub mod controller;
pub mod error;

use clap::Parser;
use ortho_config::SubcmdConfigMerge;
use serde::Serialize;

use crate::config::{StartCommand, StatusCommand, StatusOptions, StopCommand};
use crate::controller::{DaemonController, StatusSummary, SystemSpawner};
use crate::error::CliError;

#[derive(Debug, Parser)]
#[command(name = "weaver", about = "CLI client for the weaverd daemon")]
pub struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Debug, Parser)]
pub enum Command {
    Start(StartCommand),
    Stop(StopCommand),
    Status(StatusCommand),
}

pub fn run() -> Result<(), CliError> {
    let cli = Cli::parse();
    let controller = DaemonController::<SystemSpawner>::default();
    match cli.command {
        Command::Start(cmd) => {
            let merged = cmd.load_and_merge()?;
            let options = merged.resolve()?;
            let status = controller.start(&options)?;
            emit("start", &status.summary())?;
        }
        Command::Stop(cmd) => {
            let merged = cmd.load_and_merge()?;
            let options = merged.resolve();
            controller.stop(&options)?;
            let status = controller.status(&StatusOptions {
                paths: options.paths.clone(),
            })?;
            emit("stop", &status.summary())?;
        }
        Command::Status(cmd) => {
            let merged = cmd.load_and_merge()?;
            let options = merged.resolve();
            let status = controller.status(&options)?;
            emit("status", &status.summary())?;
        }
    }
    Ok(())
}

fn emit(action: &str, summary: &StatusSummary) -> Result<(), CliError> {
    #[derive(Serialize)]
    struct Payload<'a> {
        action: &'a str,
        #[serde(flatten)]
        summary: &'a StatusSummary,
    }
    let payload = Payload { action, summary };
    let json = serde_json::to_string_pretty(&payload)
        .map_err(|err| CliError::InvalidStatus(err.to_string()))?;
    println!("{json}");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn payload_serialises() {
        let summary = StatusSummary {
            running: true,
            pid: Some(42),
            socket_path: std::path::PathBuf::from("/tmp/weaverd.sock"),
        };
        emit("status", &summary).expect("emit succeeds");
    }
}
