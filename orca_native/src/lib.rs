//! orca_native — Rust performance modules for Orca Code.
//!
//! Provides PyO3-bound native implementations of:
//! - `search`  — ripgrep-powered code search (10-100x faster than Python rglob)
//! - `diff`    — unified diff parsing and application
//! - `walk`    — gitignore-aware parallel file traversal

use pyo3::prelude::*;

mod search;
mod diff;
mod walk;

/// Search file contents using ripgrep's grep-searcher engine.
#[pyfunction]
fn search_content(pattern: &str, directory: &str, file_filter: Option<&str>,
                  max_results: Option<usize>, context_lines: Option<usize>)
    -> PyResult<String>
{
    search::search(pattern, directory, file_filter, max_results.unwrap_or(100),
                   context_lines.unwrap_or(0))
}

/// Apply a unified diff to a file. Returns a JSON summary of applied hunks.
#[pyfunction]
fn apply_diff(file_path: &str, diff_text: &str) -> PyResult<String> {
    diff::apply(file_path, diff_text)
}

/// Walk a directory tree, respecting .gitignore. Returns newline-separated paths.
#[pyfunction]
fn walk_files(directory: &str, pattern: Option<&str>, max_files: Option<usize>)
    -> PyResult<String>
{
    walk::walk(directory, pattern.unwrap_or("*"), max_files.unwrap_or(5000))
}

/// A Python module implemented in Rust.
#[pymodule]
fn orca_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(search_content, m)?)?;
    m.add_function(wrap_pyfunction!(apply_diff, m)?)?;
    m.add_function(wrap_pyfunction!(walk_files, m)?)?;
    Ok(())
}
