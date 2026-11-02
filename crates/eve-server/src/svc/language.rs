//! `languageSvc`: the languages the client may choose and the slide text packs.
//!
//! The language list comes from the official `languages` table (11 rows). Item,
//! group and place names are translated separately by the bulk overlay; this
//! service only serves the list itself.

use eve_marshal::Value;

use crate::services::{Call, Ctx, Outcome};
use crate::svc::rows::rowset;

pub async fn language_svc(call: &Call, ctx: &Ctx<'_>) -> Option<Outcome> {
    let value = match call.method.as_str() {
        // GameUI.GetLanguages, as the client reads it: one row per language.
        "GetLanguages" => {
            let sql = r#"SELECT "languageID","languageName","translatedLanguageName"
                           FROM "languages" ORDER BY "languageID""#;
            ctx.rowset(&["languageID", "languageName", "translatedLanguageName"], sql, &[])
                .await
        }
        // mlsUtil.LoadLanguagePack: {(columnID, keyID): text}.
        "GetMessagesByLanguageID" => Value::Dict(Vec::new()),
        // slides.__LoadTextGroup indexes the rows by textLabel.
        "GetTextsForGroup" => rowset(&["textLabel", "text"], Vec::new()),
        _ => return None,
    };
    Some(Outcome::Value(value))
}
