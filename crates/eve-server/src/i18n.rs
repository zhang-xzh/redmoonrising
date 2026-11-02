//! Per-language text overlays for the server's static table data.
//!
//! The official 3913 database is English only. A language directory may hold
//! `server_<lang>.json`, shaped as `table -> column -> primary key -> text`;
//! the server builds one extra bulk set for every such file at startup and
//! serves it to sessions with that language. Anything the file does not cover
//! stays English, so a partial translation is always usable.

use std::collections::HashMap;
use std::path::Path;

use serde::Deserialize;
use tracing::{info, warn};

/// `table -> column -> key -> text`.
#[derive(Debug, Default, Deserialize)]
pub struct Overlay {
    #[serde(flatten)]
    tables: HashMap<String, HashMap<String, HashMap<String, String>>>,
}

impl Overlay {
    /// The translated text for one table cell, if the overlay has it.
    pub fn text(&self, table: &str, column: &str, key: &str) -> Option<&str> {
        self.tables
            .get(table)?
            .get(column)?
            .get(key)
            .map(String::as_str)
    }
}

/// Every `server_<lang>.json` in one directory, keyed by upper-case language ID.
#[derive(Debug, Default)]
pub struct Catalog {
    by_lang: HashMap<String, Overlay>,
}

impl Catalog {
    /// Reads the directory. A missing directory means no translations; a file
    /// that does not parse is reported and skipped, so one bad language cannot
    /// keep the server down.
    pub fn load(dir: &Path) -> Self {
        let mut catalog = Catalog::default();
        let entries = match std::fs::read_dir(dir) {
            Ok(entries) => entries,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                info!(
                    "no localization directory at {}; serving English only",
                    dir.display()
                );
                return catalog;
            }
            Err(e) => {
                warn!("cannot read {}: {e}; serving English only", dir.display());
                return catalog;
            }
        };
        for entry in entries.flatten() {
            let path = entry.path();
            let Some(name) = path.file_name().and_then(|n| n.to_str()) else {
                continue;
            };
            let Some(lang) = name
                .strip_prefix("server_")
                .and_then(|n| n.strip_suffix(".json"))
            else {
                continue;
            };
            let lang = lang.to_ascii_uppercase();
            let raw = match std::fs::read(&path) {
                Ok(raw) => raw,
                Err(e) => {
                    warn!("cannot read {}: {e}", path.display());
                    continue;
                }
            };
            match serde_json::from_slice::<Overlay>(&raw) {
                Ok(overlay) => {
                    let cells: usize = overlay
                        .tables
                        .values()
                        .flat_map(|columns| columns.values())
                        .map(HashMap::len)
                        .sum();
                    info!("localization {lang}: {cells} texts from {}", path.display());
                    catalog.by_lang.insert(lang, overlay);
                }
                Err(e) => warn!("cannot parse {}: {e}", path.display()),
            }
        }
        catalog
    }

    pub fn overlay(&self, lang: Option<&str>) -> Option<&Overlay> {
        let lang = lang?.trim().to_ascii_uppercase();
        self.by_lang.get(&lang)
    }

    pub fn languages(&self) -> impl Iterator<Item = &str> {
        self.by_lang.keys().map(String::as_str)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_table_column_key() {
        let raw = br#"{"invTypes":{"typeName":{"587":"Rifter"}}}"#;
        let overlay: Overlay = serde_json::from_slice(raw).unwrap();
        assert_eq!(overlay.text("invTypes", "typeName", "587"), Some("Rifter"));
        assert_eq!(overlay.text("invTypes", "typeName", "588"), None);
        assert_eq!(overlay.text("invGroups", "groupName", "587"), None);
    }
}
