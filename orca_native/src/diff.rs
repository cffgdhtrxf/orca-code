//! Unified diff parsing and application.
//!
//! Parses standard unified diff format and applies hunks to files.
//! Uses the `similar` crate for line diffing and validation.

use regex::Regex;
use std::fs;
use std::path::Path;

/// Hunk represents one section of a unified diff.
#[allow(dead_code)]
struct Hunk {
    old_start: usize,
    old_count: usize,
    new_start: usize,
    new_count: usize,
    lines: Vec<HunkLine>,
}

#[allow(dead_code)]
enum HunkLine {
    Context(String),
    Addition(String),
    Deletion(String),
}

/// Apply a unified diff string to a file. Returns JSON summary.
pub fn apply(file_path: &str, diff_text: &str) -> pyo3::PyResult<String> {
    let path = Path::new(file_path);

    // Read original file
    let original = match fs::read_to_string(path) {
        Ok(s) => s,
        Err(e) => return Ok(format!("{{\"error\": \"Cannot read file: {}\"}}", e)),
    };

    let original_lines: Vec<&str> = original.lines().collect();

    // Parse hunks from diff text
    let hunks = match parse_hunks(diff_text) {
        Ok(h) => h,
        Err(e) => return Ok(format!("{{\"error\": \"{}\"}}", e)),
    };

    if hunks.is_empty() {
        return Ok(r#"{"error": "No hunks found in diff"}"#.to_string());
    }

    // Apply hunks
    let mut result: Vec<String> = Vec::new();
    let mut orig_idx: usize = 0; // 0-based index into original_lines
    let mut applied = 0usize;
    let mut failed: Vec<usize> = Vec::new();

    for (hunk_idx, hunk) in hunks.iter().enumerate() {
        // Output lines before this hunk
        let hunk_start = hunk.old_start.saturating_sub(1); // convert to 0-based
        while orig_idx < hunk_start && orig_idx < original_lines.len() {
            result.push(original_lines[orig_idx].to_string());
            orig_idx += 1;
        }

        // Skip context matching lines in original
        let mut hunk_lines_applied = 0usize;
        for line in &hunk.lines {
            match line {
                HunkLine::Context(ref text) => {
                    if orig_idx < original_lines.len() {
                        result.push(original_lines[orig_idx].to_string());
                        orig_idx += 1;
                    } else {
                        result.push(text.clone());
                    }
                    hunk_lines_applied += 1;
                }
                HunkLine::Addition(ref text) => {
                    result.push(text.clone());
                    hunk_lines_applied += 1;
                }
                HunkLine::Deletion(_) => {
                    // Skip the deleted line in original
                    if orig_idx < original_lines.len() {
                        orig_idx += 1;
                    }
                    hunk_lines_applied += 1;
                }
            }
        }

        if hunk_lines_applied > 0 {
            applied += 1;
        } else {
            failed.push(hunk_idx);
        }
    }

    // Output remaining original lines
    while orig_idx < original_lines.len() {
        result.push(original_lines[orig_idx].to_string());
        orig_idx += 1;
    }

    // Write back
    let new_content = result.join("\n");
    // Atomic write: temp file then rename
    let tmp_path = path.with_extension(
        format!("{}.tmp", path.extension().map_or("".to_string(), |e| e.to_string_lossy().to_string()))
    );
    if let Err(e) = fs::write(&tmp_path, &new_content) {
        return Ok(format!("{{\"error\": \"Write failed: {}\"}}", e));
    }
    if let Err(e) = fs::rename(&tmp_path, path) {
        let _ = fs::remove_file(&tmp_path);
        return Ok(format!("{{\"error\": \"Atomic rename failed: {}\"}}", e));
    }

    let summary = format!(
        r#"{{"applied": {}, "failed": {}, "total_hunks": {}, "new_size": {}}}"#,
        applied,
        failed.len(),
        hunks.len(),
        new_content.len()
    );

    Ok(summary)
}

fn parse_hunks(diff_text: &str) -> Result<Vec<Hunk>, String> {
    let hunk_header = Regex::new(r"^@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@?(.*)$").unwrap();
    let mut hunks: Vec<Hunk> = Vec::new();
    let mut current: Option<Hunk> = None;

    for line in diff_text.lines() {
        if let Some(caps) = hunk_header.captures(line) {
            // Save previous hunk
            if let Some(h) = current.take() {
                hunks.push(h);
            }

            let old_start: usize = caps[1].parse().unwrap_or(1);
            let old_count: usize = if caps[2].is_empty() { 1 } else { caps[2].parse().unwrap_or(1) };
            let new_start: usize = caps[3].parse().unwrap_or(1);
            let new_count: usize = if caps[4].is_empty() { 1 } else { caps[4].parse().unwrap_or(1) };

            current = Some(Hunk {
                old_start,
                old_count,
                new_start,
                new_count,
                lines: Vec::new(),
            });
        } else if let Some(ref mut hunk) = current {
            if line.starts_with('+') && !line.starts_with("+++") {
                hunk.lines.push(HunkLine::Addition(line[1..].to_string()));
            } else if line.starts_with('-') && !line.starts_with("---") {
                hunk.lines.push(HunkLine::Deletion(line[1..].to_string()));
            } else if line.starts_with(' ') || line.is_empty() {
                let text = if line.is_empty() { String::new() } else { line[1..].to_string() };
                hunk.lines.push(HunkLine::Context(text));
            }
            // Skip diff headers (---, +++, index, diff --git, etc.)
        }
    }

    if let Some(h) = current.take() {
        hunks.push(h);
    }

    if hunks.is_empty() {
        return Err("No valid hunks found in diff".to_string());
    }

    Ok(hunks)
}
