fn main() -> std::process::ExitCode {
    match weaverd::run() {
        Ok(()) => std::process::ExitCode::SUCCESS,
        Err(err) => {
            eprintln!("daemon error: {err}");
            std::process::ExitCode::FAILURE
        }
    }
}
