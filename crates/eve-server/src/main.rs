mod ballpark;
mod bots;
mod bulkdata;
mod combat;
mod concord;
mod config;
mod conn;
mod db;
mod destiny;
mod drones;
mod dogma;
mod exceptions;
mod fight;
mod gates;
mod guard;
mod heartbeat;
mod i18n;
mod items;
mod logging;
mod losses;
mod loot;
mod npc;
mod pos;
mod services;
mod session;
mod sites;
mod svc;
mod web;
mod world;

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Instant;

use eve_marshal::StringTable;
use tokio::net::TcpListener;
use tracing::{debug, error, info, warn};

use config::Config;
use conn::{Conn, Server};

/// Bulk objects this close to the 1 MB frame cap are worth a warning.
const BULK_WARN_BYTES: usize = 900_000;

#[tokio::main]
async fn main() {
    // The config says how to log, so it is read before there is a log.
    let (config, note) = match Config::load() {
        Ok(c) => c,
        Err(e) => {
            eprintln!("{e}");
            std::process::exit(2);
        }
    };
    if let Err(e) = logging::init(&config.log_level, config.log_file.as_deref()) {
        eprintln!("{e}");
        std::process::exit(2);
    }
    info!("{note}");
    if let Err(e) = run(config).await {
        error!("{}", logging::chain(&*e));
        std::process::exit(1);
    }
}

async fn run(config: Config) -> Result<(), Box<dyn std::error::Error>> {

    let table = std::fs::read(&config.strings)
        .map(|raw| StringTable::parse(&raw))
        .map_err(|e| {
            format!("cannot read the shared string table at {}: {e}", config.strings.display())
        })?;
    info!("string table: {} entries from {}", table.len(), config.strings.display());

    let client = db::connect(&config.database).await.map_err(|e| {
        format!("cannot reach PostgreSQL at {}: {}", config.database_redacted(), logging::chain(&e))
    })?;
    let accounts: i64 = client
        .query_one(r#"SELECT count(*) FROM "account""#, &[])
        .await
        .map(|r| r.get(0))
        .unwrap_or(0);
    info!("database: {} ({accounts} accounts)", config.database_redacted());
    if let Err(e) = db::repair_language_names(&client).await {
        error!("repairing the language names: {}", logging::chain(&e));
    }
    let ids = db::sync_accounts(&client, &config.accounts)
        .await
        .map_err(|e| format!("setting up the config file's accounts: {}", logging::chain(&e)))?;
    if !ids.is_empty() {
        info!("{} account(s) from the config file", ids.len());
    }
    config::set_rules(config::Rules {
        starting_isk: config.starting_isk,
        account_isk: ids.iter().zip(&config.accounts).filter_map(|(id, a)| Some((*id, a.starting_isk?))).collect(),
        auto_create_accounts: config.auto_create_accounts,
    });

    let catalog = i18n::Catalog::load(&config.localization);
    let started = Instant::now();
    let base = bulkdata::BulkData::load(
        &client,
        &table,
        config.node_id,
        bulkdata::filetime_now(),
        None,
    )
    .await?;
    report_bulk("EN", &base, started);
    let mut by_lang = HashMap::new();
    for lang in catalog.languages() {
        let Some(overlay) = catalog.overlay(Some(lang)) else { continue };
        let started = Instant::now();
        let bulk = bulkdata::BulkData::load(
            &client,
            &table,
            config.node_id,
            bulkdata::filetime_now(),
            Some(overlay),
        )
        .await?;
        report_bulk(lang, &bulk, started);
        by_lang.insert(lang.to_string(), bulk);
    }
    let bulk = bulkdata::BulkSet { base, by_lang };

    let dogma = dogma::Catalog::load(&client).await.map_err(|e| format!("loading dogma: {}", logging::chain(&e)))?;

    let services = svc::registry();
    info!("{} services registered", services.len());

    let server = Arc::new(Server {
        table,
        db: client,
        db_url: config.database.clone(),
        node_id: config.node_id,
        bulk,
        dogma,
        services,
        world: world::World::default(),
        dump_dir: config.dump_dir.clone(),
        alliance_join_delay_secs: config.alliance_join_delay_secs,
        sov_claim_delay_secs: config.sov_claim_delay_secs,
    });
    pos::set_speedup(config.starbase_speedup);
    tokio::spawn(heartbeat::run(Arc::clone(&server)));
    bots::configure(config.bots_pirates_attack, config.bots_controls);
    tokio::spawn(bots::run(Arc::clone(&server), config.bots, config.bots_speed, config.bots_shown));
    tokio::spawn(web::run(Arc::clone(&server), config.web.clone()));
    let listener = TcpListener::bind(&config.bind).await?;
    info!("listening on {} as node {}", config.bind, config.node_id);

    let mut seq = 0i64;
    loop {
        let (stream, peer) = match listener.accept().await {
            Ok(v) => v,
            Err(e) => {
                warn!("accept failed: {err}", err = crate::logging::chain(&e));
                continue;
            }
        };
        let _ = stream.set_nodelay(true);
        seq += 1;
        tokio::spawn(Conn::new(stream, peer, Arc::clone(&server), seq).run());
    }
}

fn report_bulk(lang: &str, bulk: &bulkdata::BulkData, started: Instant) {
    let mut bytes = 0usize;
    let mut empty = Vec::new();
    for spec in bulkdata::SPECS {
        let e = &bulk.entries[spec.key];
        bytes += e.pickle.len();
        if e.rows == 0 {
            empty.push(spec.key);
        }
        if e.pickle.len() > BULK_WARN_BYTES {
            warn!("bulk object {} is {} bytes, near the 1 MB frame cap", spec.key, e.pickle.len());
        }
    }
    info!(
        "bulk data {lang}: {} objects, {} rows, {:.1} MB on the wire, built in {:.1}s",
        bulk.entries.len(),
        bulk.entries.values().map(|e| e.rows).sum::<usize>(),
        bytes as f64 / 1e6,
        started.elapsed().as_secs_f64()
    );
    if !empty.is_empty() {
        debug!("{} bulk object(s) served with no rows: {}", empty.len(), empty.join(", "));
    }
}
