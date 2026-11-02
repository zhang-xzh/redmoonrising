//! `authentication.SetLanguageID`: the only language call that changes the
//! session. The client also sets its own `prefs.languageID`, but the session
//! (and the bulk it is served) only moves when the server says so.

use eve_marshal::Value;
use eve_proto::MachoPacket;
use tracing::{error, info, warn};

use super::{Conn, Result};

impl Conn {
    pub(super) async fn set_language(&mut self, req: &MachoPacket, language_id: String) -> Result {
        let language = language_id.trim().to_ascii_uppercase();
        if language.is_empty() {
            return self.reply(req, &Value::None).await;
        }
        let known = self
            .server
            .db
            .query_opt(
                r#"SELECT 1 FROM "languages" WHERE "languageID" = $1"#,
                &[&language],
            )
            .await;
        match known {
            Ok(Some(_)) => {}
            Ok(None) => {
                warn!("refused unknown language {language:?}");
                return self.reply(req, &Value::None).await;
            }
            Err(e) => {
                error!(
                    "checking language {language:?}: {}",
                    crate::logging::chain(&e)
                );
                return self.reply(req, &Value::None).await;
            }
        }
        if self.session.language_id.as_deref() == Some(language.as_str()) {
            return self.reply(req, &Value::None).await;
        }

        let before = self.session.clone();
        self.session.language_id = Some(language.clone());
        if let Some(account_id) = self.session.user_id {
            if let Err(e) =
                crate::db::set_account_language(&self.server.db, account_id, &language).await
            {
                error!(
                    "saving language for account {account_id}: {}",
                    crate::logging::chain(&e)
                );
            }
        }
        self.send_session_change_from(&before).await?;
        info!(language = %language, "session language changed");
        self.reply(req, &Value::None).await
    }
}
