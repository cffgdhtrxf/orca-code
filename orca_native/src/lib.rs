//! orca_native — Rust performance modules for Orca Code.
//!
//! Provides PyO3-bound native implementations of:
//! - `search`    — ripgrep-powered code search (10-100x faster than Python rglob)
//! - `diff`      — unified diff parsing and application
//! - `walk`      — gitignore-aware parallel file traversal
//! - `tokenizer` — fast BPE token counting (estimates for cl100k_base)
//! - `encoding`  — file encoding detection (BOM + frequency analysis)

use pyo3::prelude::*;

mod search;
mod diff;
mod walk;
mod tokenizer;
mod encoding;

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

/// Fast token count estimate (cl100k_base approximation).
#[pyfunction]
fn count_tokens(text: &str) -> PyResult<u64> {
    tokenizer::count_tokens(text)
}

/// Fast token count for a batch of texts (parallel via rayon).
#[pyfunction]
fn count_tokens_batch(texts: Vec<String>) -> PyResult<Vec<u64>> {
    tokenizer::count_tokens_batch(texts)
}

/// Detect file encoding. Returns EncodingInfo with encoding, confidence, has_bom.
#[pyfunction]
fn detect_encoding(path: &str) -> PyResult<encoding::EncodingInfo> {
    encoding::detect(path)
}

/// A Python module implemented in Rust.
#[pymodule]
fn orca_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(search_content, m)?)?;
    m.add_function(wrap_pyfunction!(apply_diff, m)?)?;
    m.add_function(wrap_pyfunction!(walk_files, m)?)?;
    m.add_function(wrap_pyfunction!(count_tokens, m)?)?;
    m.add_function(wrap_pyfunction!(count_tokens_batch, m)?)?;
    m.add_function(wrap_pyfunction!(detect_encoding, m)?)?;
    m.add_class::<encoding::EncodingInfo>()?;
    Ok(())
}
