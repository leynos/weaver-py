use std::cell::RefCell;
use std::fs;
use std::path::PathBuf;

use rstest::fixture;
use rstest_bdd_macros::{given, scenario, then, when};
use serde_json::Value;
use serial_test::serial;
use tempfile::TempDir;

#[derive(Clone)]
struct CommandResult {
    status: std::process::ExitStatus,
    stdout: String,
}

struct Harness {
    tempdir: TempDir,
    socket_path: PathBuf,
    pid_file: PathBuf,
    daemon_binary: PathBuf,
    binary_override: RefCell<Option<PathBuf>>,
    last: RefCell<Option<CommandResult>>,
}

impl Harness {
    fn new() -> Self {
        let tempdir = TempDir::new().expect("tempdir");
        let socket_path = tempdir.path().join("daemon.sock");
        let pid_file = tempdir.path().join("daemon.pid");
        let daemon_binary = assert_cmd::cargo::cargo_bin("weaverd");
        Self {
            tempdir,
            socket_path,
            pid_file,
            daemon_binary,
            binary_override: RefCell::new(None),
            last: RefCell::new(None),
        }
    }

    fn reset(&self) {
        let _ = fs::remove_file(&self.socket_path);
        let _ = fs::remove_file(&self.pid_file);
        self.binary_override.borrow_mut().take();
        self.last.borrow_mut().take();
    }

    fn run_start(&self) {
        let binary = self.current_daemon_binary();
        let args = [
            "start",
            "--socket-path",
            self.socket_path.to_str().expect("socket path"),
            "--pid-file",
            self.pid_file.to_str().expect("pid file"),
            "--daemon-binary",
            binary.to_str().expect("daemon binary"),
            "--startup-timeout",
            "5",
            "--shutdown-timeout",
            "5",
        ];
        let _ = self.run_cli(&args);
    }

    fn run_stop(&self) {
        let args = [
            "stop",
            "--socket-path",
            self.socket_path.to_str().expect("socket path"),
            "--pid-file",
            self.pid_file.to_str().expect("pid file"),
            "--shutdown-timeout",
            "5",
        ];
        let _ = self.run_cli(&args);
    }

    fn run_status(&self) -> Option<Value> {
        let args = [
            "status",
            "--socket-path",
            self.socket_path.to_str().expect("socket path"),
            "--pid-file",
            self.pid_file.to_str().expect("pid file"),
        ];
        let output = self.run_cli(&args);
        output
            .ok()
            .and_then(|res| serde_json::from_str(&res.stdout).ok())
    }

    fn run_start_with_missing_binary(&self) {
        self.binary_override
            .borrow_mut()
            .replace(self.tempdir.path().join("missing-weaverd"));
        let binary = self.current_daemon_binary();
        let args = [
            "start",
            "--socket-path",
            self.socket_path.to_str().expect("socket path"),
            "--pid-file",
            self.pid_file.to_str().expect("pid file"),
            "--daemon-binary",
            binary.to_str().expect("daemon binary"),
            "--startup-timeout",
            "1",
            "--shutdown-timeout",
            "1",
        ];
        let _ = self.run_cli(&args);
    }

    fn run_cli(&self, args: &[&str]) -> Result<CommandResult, std::io::Error> {
        let mut cmd = assert_cmd::Command::cargo_bin("weaver-cli").expect("weaver-cli binary");
        cmd.args(args);
        let output = cmd.output()?;
        let result = CommandResult {
            status: output.status,
            stdout: String::from_utf8_lossy(&output.stdout).into_owned(),
        };
        self.last.borrow_mut().replace(result.clone());
        Ok(result)
    }

    fn current_daemon_binary(&self) -> PathBuf {
        self.binary_override
            .borrow()
            .clone()
            .unwrap_or_else(|| self.daemon_binary.clone())
    }

    fn last(&self) -> CommandResult {
        self.last
            .borrow()
            .clone()
            .expect("command result available")
    }

    fn is_running(&self) -> bool {
        self.run_status()
            .and_then(|value| value.get("running").and_then(|r| r.as_bool()))
            .unwrap_or(false)
    }
}

impl Drop for Harness {
    fn drop(&mut self) {
        let args = [
            "stop",
            "--socket-path",
            self.socket_path.to_str().expect("socket path"),
            "--pid-file",
            self.pid_file.to_str().expect("pid file"),
            "--shutdown-timeout",
            "1",
        ];
        let _ = assert_cmd::Command::cargo_bin("weaver-cli")
            .ok()
            .map(|mut cmd| {
                let _ = cmd.args(&args).output();
            });
    }
}

#[fixture]
fn harness() -> Harness {
    Harness::new()
}

#[given("a temporary runtime directory")]
fn prepare(harness: &Harness) {
    harness.reset();
}

#[when("I run the cli start command")]
fn start(harness: &Harness) {
    harness.run_start();
}

#[when("I run the cli stop command")]
fn stop(harness: &Harness) {
    harness.run_stop();
}

#[when("I run the cli start command with a missing binary")]
fn start_missing(harness: &Harness) {
    harness.run_start_with_missing_binary();
}

#[then("the daemon should report running status")]
fn assert_running(harness: &Harness) {
    assert!(harness.is_running());
}

#[then("the daemon should not be running")]
fn assert_not_running(harness: &Harness) {
    assert!(!harness.is_running());
}

#[then("the command should exit with failure")]
fn assert_failure(harness: &Harness) {
    let last = harness.last();
    assert!(
        !last.status.success(),
        "expected command failure, stdout: {}",
        last.stdout
    );
}
#[scenario(path = "tests/features/daemon.feature", index = 0)]
#[serial]
fn start_and_stop(harness: Harness) {
    drop(harness);
}

#[scenario(path = "tests/features/daemon.feature", index = 1)]
#[serial]
fn start_missing_binary(harness: Harness) {
    drop(harness);
}
