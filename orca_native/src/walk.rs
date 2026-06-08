//! Gitignore-aware file traversal via ignore::WalkBuilder.

use ignore::WalkBuilder;
use std::path::Path;

pub fn walk(directory: &str, pattern: &str, max_files: usize) -> pyo3::PyResult<String> {
    let dir = Path::new(directory);
    if !dir.is_dir() {
        return Ok(format!("Error: not a directory — {}", directory));
    }

    let mut builder = WalkBuilder::new(dir);
    builder.standard_filters(true);
    builder.hidden(false);
    builder.follow_links(false);
    builder.threads(1);

    let walker = builder.build();
    let is_glob = pattern.contains('*') || pattern.contains('?') || pattern.contains('[');
    let mut results: Vec<String> = Vec::new();

    for entry in walker {
        if results.len() >= max_files {
            break;
        }

        let entry = match entry {
            Ok(e) => e,
            Err(_) => continue,
        };

        if !entry.file_type().map_or(false, |ft| ft.is_file()) {
            continue;
        }

        let path = entry.path();
        let rel = path.strip_prefix(dir).unwrap_or(path);
        let name = rel.to_string_lossy();

        if is_glob {
            if glob_match(pattern, &name) {
                results.push(rel.display().to_string());
            }
        } else {
            let fname = rel
                .file_name()
                .map(|n| n.to_string_lossy().to_string())
                .unwrap_or_default();
            if fname.contains(pattern) {
                results.push(rel.display().to_string());
            }
        }
    }

    if results.is_empty() {
        Ok(format!("No files matching '{}'", pattern))
    } else {
        Ok(results.join("\n"))
    }
}

fn glob_match(pattern: &str, name: &str) -> bool {
    let parts: Vec<&str> = pattern.split('*').collect();
    if parts.len() == 1 {
        return name == pattern;
    }
    let mut remaining = name;
    for (i, part) in parts.iter().enumerate() {
        if i == 0 {
            if !remaining.starts_with(part) {
                return false;
            }
            remaining = &remaining[part.len()..];
        } else if i == parts.len() - 1 {
            if !remaining.ends_with(part) {
                return false;
            }
        } else if let Some(pos) = remaining.find(part) {
            remaining = &remaining[pos + part.len()..];
        } else {
            return false;
        }
    }
    true
}
