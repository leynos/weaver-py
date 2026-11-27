use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};

use nix::errno::Errno;
use nix::sys::signal::kill;
use nix::unistd::Pid;

use crate::error::DaemonError;

pub struct PidFileGuard {
    path: PathBuf,
}

impl PidFileGuard {
    pub fn acquire(path: PathBuf) -> Result<Self, DaemonError> {
        if let Some(pid) = read_pid(&path)? {
            if is_pid_alive(pid) {
                return Err(DaemonError::AlreadyRunning { pid });
            }
            fs::remove_file(&path).ok();
        }
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).map_err(|err| DaemonError::io(parent.to_path_buf(), err))?;
        }
        write_pid(&path)?;
        Ok(Self { path })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }
}

impl Drop for PidFileGuard {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.path);
    }
}

fn read_pid(path: &Path) -> Result<Option<u32>, DaemonError> {
    match fs::read_to_string(path) {
        Ok(contents) => {
            let pid = contents.trim().parse::<u32>().map_err(|err| {
                DaemonError::io(
                    path.to_path_buf(),
                    io::Error::new(io::ErrorKind::InvalidData, err),
                )
            })?;
            Ok(Some(pid))
        }
        Err(err) if err.kind() == io::ErrorKind::NotFound => Ok(None),
        Err(err) => Err(DaemonError::io(path.to_path_buf(), err)),
    }
}

fn write_pid(path: &Path) -> Result<(), DaemonError> {
    let pid = std::process::id();
    let tmp = path.with_extension("tmp");
    let mut file = fs::File::create(&tmp).map_err(|err| DaemonError::io(tmp.clone(), err))?;
    writeln!(file, "{pid}").map_err(|err| DaemonError::io(tmp.clone(), err))?;
    file.flush()
        .map_err(|err| DaemonError::io(tmp.clone(), err))?;
    fs::rename(&tmp, path).map_err(|err| DaemonError::io(path.to_path_buf(), err))
}

fn is_pid_alive(pid: u32) -> bool {
    match kill(Pid::from_raw(pid as i32), None) {
        Ok(()) => true,
        Err(Errno::EPERM) => true,
        Err(Errno::ESRCH) => false,
        Err(_) => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serial_test::serial;
    use tempfile::TempDir;

    #[test]
    #[serial]
    fn stale_pid_is_removed() {
        let dir = TempDir::new().expect("tempdir");
        let path = dir.path().join("daemon.pid");
        fs::write(&path, "99999").expect("write pid");
        let guard = PidFileGuard::acquire(path.clone()).expect("acquire");
        assert!(guard.path().exists());
        drop(guard);
        assert!(!path.exists());
    }
}
