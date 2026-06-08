//! Fast code search powered by ripgrep's grep-searcher + ignore walker.

use grep_regex::RegexMatcher;
use grep_searcher::{Searcher, SearcherBuilder, Sink, SinkMatch};
use ignore::WalkBuilder;
use std::path::{Path, PathBuf};

struct CollectSink {
    results: Vec<String>,
    current_path: PathBuf,
    max_results: usize,
    count: usize,
}

impl CollectSink {
    fn new(max_results: usize) -> Self {
        Self {
            results: Vec::new(),
            current_path: PathBuf::new(),
            max_results,
            count: 0,
        }
    }
}

impl Sink for CollectSink {
    type Error = std::io::Error;

    fn matched(
        &mut self,
        _searcher: &Searcher,
        mat: &SinkMatch<'_>,
    ) -> Result<bool, Self::Error> {
        if self.count >= self.max_results {
            return Ok(false);
        }
        self.count += 1;

        let path = self.current_path.display().to_string();
        let line = mat.line_number().unwrap_or(0);
        let content = String::from_utf8_lossy(mat.buffer()).trim().to_string();
        let content = if content.len() > 300 {
            format!("{}...", &content[..297])
        } else {
            content
        };

        self.results.push(format!("{}:{}: {}", path, line, content));
        Ok(true)
    }
}

pub fn search(
    pattern: &str,
    directory: &str,
    file_filter: Option<&str>,
    max_results: usize,
    _context_lines: usize,
) -> pyo3::PyResult<String> {
    let dir = Path::new(directory);
    if !dir.is_dir() {
        return Ok(format!("Error: not a directory — {}", directory));
    }

    let matcher = match RegexMatcher::new(pattern) {
        Ok(m) => m,
        Err(e) => return Ok(format!("Error: invalid regex pattern — {}", e)),
    };

    let mut searcher = SearcherBuilder::new().multi_line(true).build();

    // Use WalkBuilder for configuration, then build a Walk iterator
    let mut builder = WalkBuilder::new(dir);
    builder.standard_filters(true);
    builder.hidden(false);
    builder.follow_links(false);
    builder.threads(1); // single-threaded for &mut Sink compatibility

    if let Some(filter) = file_filter {
        let ext = filter.trim_start_matches("*.");
        let mut types_builder = ignore::types::TypesBuilder::new();
        if types_builder.add("custom", &format!("*.{}", ext)).is_ok() {
            // select() returns &mut Self on older ignore versions
            types_builder.select("custom");
            if let Ok(types) = types_builder.build() {
                builder.types(types);
            }
        }
    }

    let walker = builder.build();
    let mut sink = CollectSink::new(max_results);

    for entry in walker {
        let entry = match entry {
            Ok(e) => e,
            Err(_) => continue,
        };

        if !entry.file_type().map_or(false, |ft| ft.is_file()) {
            continue;
        }

        if entry.metadata().map_or(false, |m| m.len() > 1_048_576) {
            continue;
        }

        // Store path before search so sink can access it
        sink.current_path = entry.path().to_path_buf();
        let _ = searcher.search_path(&matcher, entry.path(), &mut sink);

        if sink.count >= sink.max_results {
            break;
        }
    }

    if sink.results.is_empty() {
        Ok(format!("No matches found for '{}'", pattern))
    } else {
        Ok(sink.results.join("\n"))
    }
}
