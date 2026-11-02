use std::collections::HashMap;

use eve_marshal::{StringTable, Value};
use flate2::write::ZlibEncoder;
use flate2::Compression;
use tokio_postgres::error::SqlState;
use std::io::Write;

use crate::i18n::Overlay;

#[derive(Copy, Clone, PartialEq)]
pub enum Shape {
    Tuple,
    Rowset,
    /// (header, [util.Row]): for tables the client walks reading row.column
    /// (cfg.py:594, :604).
    RowTuple,
}

pub struct Spec {
    pub key: &'static str,
    pub shape: Shape,
    pub sql: Option<&'static str>,
    pub header: &'static [&'static str],
    pub numeric_text: &'static [&'static str],
}

const fn s(key: &'static str, shape: Shape, sql: &'static str) -> Spec {
    Spec { key, shape, sql: Some(sql), header: &[], numeric_text: &[] }
}

const fn s_num(
    key: &'static str,
    shape: Shape,
    sql: &'static str,
    numeric_text: &'static [&'static str],
) -> Spec {
    Spec { key, shape, sql: Some(sql), header: &[], numeric_text }
}

const fn empty(key: &'static str, shape: Shape, header: &'static [&'static str]) -> Spec {
    Spec { key, shape, sql: None, header, numeric_text: &[] }
}

pub const SPECS: &[Spec] = &[
    s("config.BulkData.constants", Shape::Tuple,
      r#"SELECT "constantID","constantValue" FROM "eveConstants""#),
    s("config.BulkData.messages", Shape::Tuple,
      r#"SELECT "messageID","messageType","messageText","urlAudio","urlIcon" FROM "eveMessages""#),
    s("config.BulkData.graphics", Shape::Tuple,
      r#"SELECT "graphicID","url3D","urlWeb","description","published","obsolete","icon","urlSound","explosionID" FROM "eveGraphics""#),
    empty("config.BulkData.owners", Shape::Tuple, &["ownerID", "ownerName", "typeID"]),
    s("config.BulkData.tickernames", Shape::Tuple,
      r#"SELECT "corporationID","tickerName","shape1","shape2","shape3","color1","color2","color3" FROM "corporation""#),
    empty("config.BulkData.allianceshortnames", Shape::Tuple, &["allianceID", "shortName"]),
    empty("config.BulkData.locations", Shape::Tuple,
          &["locationID", "locationName", "x", "y", "z"]),
    s("config.BulkData.categories", Shape::Tuple,
      r#"SELECT "categoryID","categoryName","description","graphicID" FROM "invCategories""#),
    s("config.BulkData.metagroups", Shape::Tuple,
      r#"SELECT "metaGroupID","metaGroupName","description","graphicID" FROM "invMetaGroups""#),
    s("config.BulkData.groups", Shape::Tuple,
      r#"SELECT "groupID","categoryID","groupName","description","graphicID","useBasePrice","allowManufacture","allowRecycler","anchored","anchorable","fittableNonSingleton" FROM "invGroups""#),
    s("config.BulkData.types", Shape::Tuple,
      r#"SELECT "typeID","groupID","typeName","description","graphicID","radius","mass","volume","capacity","portionSize","raceID","basePrice","published","marketGroupID","chanceOfDuplicating" FROM "invTypes""#),
    s("config.BulkData.bptypes", Shape::Tuple,
      r#"SELECT "blueprintTypeID","parentBlueprintTypeID","productTypeID","productionTime","techLevel" FROM "invBlueprintTypes""#),
    s("config.BulkData.invtypereactions", Shape::Tuple,
      r#"SELECT "reactionTypeID","input","typeID","quantity" FROM "invTypeReactions""#),
    s("config.BulkData.invmetatypes", Shape::Tuple,
      r#"SELECT "typeID","parentTypeID","metaGroupID" FROM "invMetaTypes""#),
    s("config.BulkData.dgmattribs", Shape::Tuple,
      r#"SELECT "attributeID","attributeName","attributeCategory","description","maxAttributeID","attributeIdx","graphicID","chargeRechargeTimeID","defaultValue","published","displayName","unitID","stackable","highIsGood" FROM "dgmAttributeTypes""#),
    s("config.BulkData.dgmeffects", Shape::Tuple,
      r#"SELECT "effectID","effectName","effectCategory","preExpression","postExpression","description","guid","graphicID","isOffensive","isAssistance","durationAttributeID","trackingSpeedAttributeID","dischargeAttributeID","rangeAttributeID","falloffAttributeID","published","displayName","isWarpSafe","rangeChance","electronicChance","propulsionChance","distribution","sfxName","npcUsageChanceAttributeID","npcActivationChanceAttributeID" FROM "dgmEffects""#),
    s_num("config.BulkData.dgmtypeattribs", Shape::Tuple,
      r#"SELECT "typeID","attributeID","value" FROM "dgmTypeAttribs""#,
      &["value"]),
    s("config.BulkData.dgmtypeeffects", Shape::Tuple,
      r#"SELECT "typeID","effectID","isDefault" FROM "dgmTypeEffects""#),
    s("config.BulkData.shiptypes", Shape::Tuple,
      r#"SELECT "shipTypeID","powerCoreTypeID","capacitorTypeID","shieldTypeID","propulsionTypeID","sensorTypeID","armorTypeID","computerTypeID","weaponTypeID","miningTypeID","skillTypeID" FROM "invShipTypes""#),
    s("config.BulkData.billtypes", Shape::Tuple,
      r#"SELECT "billTypeID","billTypeName","description" FROM "billTypes""#),
    s("config.BulkData.ramaltypes", Shape::Tuple,
      r#"SELECT "assemblyLineTypeID","assemblyLineTypeName","description","baseTimeMultiplier","baseMaterialMultiplier","volume","activityID","minCostPerHour" FROM "ramAssemblyLineTypes""#),
    s("config.BulkData.ramaltypesdetailpercategory", Shape::Tuple,
      r#"SELECT "assemblyLineTypeID","categoryID","timeMultiplier","materialMultiplier" FROM "ramAssemblyLineTypeDetailPerCategory""#),
    s("config.BulkData.ramaltypesdetailpergroup", Shape::Tuple,
      r#"SELECT "assemblyLineTypeID","groupID","timeMultiplier","materialMultiplier" FROM "ramAssemblyLineTypeDetailPerGroup""#),
    s("config.BulkData.ramactivities", Shape::Tuple,
      r#"SELECT "activityID","activityName","iconNo","description","published" FROM "ramActivities""#),
    s("config.BulkData.ramcompletedstatuses", Shape::Tuple,
      r#"SELECT "completedStatusID","completedStatusName","completedStatusText" FROM "ramCompletedStatuses""#),
    // A product's base materials, keyed by the product (cfg.py:592): what it is
    // built from and what reprocessing gives back. In this data they are the
    // product-keyed activity-6 rows consumed whole; skills (damage 0) and tools
    // (fractional damage) are requirements, not materials.
    s("config.BulkData.ramtypematerials", Shape::RowTuple,
      r#"SELECT "typeID","requiredTypeID","quantity" FROM "TL2MaterialsForTypeWithActivity"
          WHERE "activity" = 6 AND "damagePerJob" = 1 ORDER BY "typeID","requiredTypeID""#),
    // Extra requirements per (blueprint, activity); the client reads row.activity
    // (cfg.py:604).
    s("config.BulkData.ramtyperequirements", Shape::RowTuple,
      r#"SELECT "typeID","activity","requiredTypeID","quantity","damagePerJob"
           FROM "TL2MaterialsForTypeWithActivity"
          WHERE "activity" BETWEEN 1 AND 5 ORDER BY "typeID","activity","requiredTypeID""#),
    s("config.InvContrabandTypes", Shape::Rowset,
      r#"SELECT "factionID","typeID","standingLoss","confiscateMinSec","fineByValue","attackMinSec" FROM "invContrabandTypes""#),
    s("config.Roles", Shape::Rowset,
      r#"SELECT "roleID","roleName","description" FROM "eveRoles""#),
    s("config.Flags", Shape::Rowset,
      r#"SELECT "flagID","flagName","flagText","flagType","orderID" FROM "eveFlags""#),
    s("config.Races", Shape::Rowset,
      r#"SELECT "raceID","raceName","description","graphicID" FROM "chrRaces""#),
    s("config.Bloodlines", Shape::Rowset,
      r#"SELECT "bloodlineID","bloodlineName","raceID","description","maleDescription","femaleDescription","shipTypeID","corporationID" FROM "chrBloodlines""#),
    s("config.Statistics", Shape::Rowset,
      r#"SELECT "statisticID","statisticName","statisticType","description","orderID","graphicID" FROM "eveStatistics""#),
    s("config.Units", Shape::Rowset,
      r#"SELECT "unitID","unitName","displayName","description" FROM "eveUnits""#),
    s("config.ChannelTypes", Shape::Rowset,
      r#"SELECT "channelTypeID","channelTypeName","defaultName" FROM "channelTypes""#),
    empty("config.EncyclopediaTypes", Shape::Rowset,
          &["encyclopediaTypeID", "encyclopediaTypeName"]),
    // Sent whole at login, so within the 1 MB a message may be: bots are left
    // out (the client asks for them by GetMultiOwnersEx, which finds them).
    s("config.StaticOwners", Shape::Rowset,
      r#"SELECT o."ownerID",o."ownerName",o."typeID" FROM "eveStaticOwners" o
          WHERE NOT EXISTS (SELECT 1 FROM "bots" b WHERE b."characterID" = o."ownerID")"#),
    s("config.StaticLocations", Shape::Rowset,
      r#"SELECT "locationID","locationName","x","y","z" FROM "eveStaticLocations""#),
];

pub struct Entry {
    pub key: String,
    pub version: (i64, i64),
    pub pickle: Vec<u8>,
    pub compressed: bool,
    pub rows: usize,
}

pub struct BulkData {
    pub entries: HashMap<String, Entry>,
    pub node_id: i64,
}

/// The English bulk data plus one build per translated language.
pub struct BulkSet {
    pub base: BulkData,
    pub by_lang: HashMap<String, BulkData>,
}

impl BulkSet {
    /// The bulk a session with `lang` gets; unknown and untranslated languages
    /// fall back to English.
    pub fn for_lang(&self, lang: Option<&str>) -> &BulkData {
        lang
            .map(|l| l.trim().to_ascii_uppercase())
            .and_then(|l| self.by_lang.get(&l))
            .unwrap_or(&self.base)
    }
}

const CACHED_OBJECT_GUID: &[u8] = b"util.CachedObject";
const PAYLOAD_GUID: &[u8] = b"objectCaching.CachedObject";
const ROWSET_GUID: &[u8] = b"util.Rowset";

pub fn crc_hqx(data: &[u8], seed: u16) -> u16 {
    let mut crc = seed;
    for &b in data {
        crc ^= (b as u16) << 8;
        for _ in 0..8 {
            crc = if crc & 0x8000 != 0 { (crc << 1) ^ 0x1021 } else { crc << 1 };
        }
    }
    crc
}

pub const CRC_SEED: u16 = 170_611_u32 as u16;

impl BulkData {
    pub async fn load(
        db: &tokio_postgres::Client,
        table: &StringTable,
        node_id: i64,
        now: i64,
        overlay: Option<&Overlay>,
    ) -> Result<Self, tokio_postgres::Error> {
        let mut entries = HashMap::new();
        for spec in SPECS {
            let (header, mut lines) = match spec.sql {
                Some(sql) => match query_rows(db, sql, spec.numeric_text).await {
                    Ok(v) => v,
                    // A static table this object reads is missing: serve it empty
                    // rather than refuse to start. The client will fail on it.
                    Err(e) if e.code() == Some(&SqlState::UNDEFINED_TABLE) => {
                        tracing::error!(
                            "bulk object {} unavailable, served empty: {}",
                            spec.key,
                            crate::logging::chain(&e)
                        );
                        (Vec::new(), Vec::new())
                    }
                    Err(e) => return Err(e),
                },
                None => (
                    spec.header.iter().map(|h| Value::bytes(*h)).collect::<Vec<_>>(),
                    Vec::new(),
                ),
            };
            if let Some(overlay) = overlay {
                let replaced = translate(spec.key, &header, &mut lines, overlay);
                if replaced > 0 {
                    tracing::debug!(object = spec.key, texts = replaced, "bulk text translated");
                }
            }
            let rows = lines.len();
            let payload = match spec.shape {
                Shape::Tuple => {
                    Value::Tuple(vec![Value::List(header), Value::List(lines)])
                }
                Shape::RowTuple => {
                    let rows = lines
                        .into_iter()
                        .map(|line| Value::Instance {
                            class: Box::new(Value::bytes("util.Row")),
                            state: Box::new(Value::Dict(vec![
                                (Value::bytes("header"), Value::List(header.clone())),
                                (Value::bytes("line"), line),
                            ])),
                        })
                        .collect();
                    Value::Tuple(vec![Value::List(header), Value::List(rows)])
                }
                Shape::Rowset => Value::Instance {
                    class: Box::new(Value::Bytes(ROWSET_GUID.to_vec())),
                    state: Box::new(Value::Dict(vec![
                        (Value::bytes("header"), Value::List(header)),
                        (Value::bytes("lines"), Value::List(lines)),
                    ])),
                },
            };

            let inner = eve_marshal::save(&payload, table).expect("bulk payload is encodable");
            let checksum = crc_hqx(&inner, CRC_SEED) as i64;
            let (pickle, compressed) = maybe_deflate(&inner);

            entries.insert(
                spec.key.to_string(),
                Entry {
                    key: spec.key.to_string(),
                    version: (now, checksum),
                    pickle,
                    compressed,
                    rows,
                },
            );
        }
        Ok(BulkData { entries, node_id })
    }

    pub fn handle(&self, entry: &Entry) -> Value {
        Value::Instance {
            class: Box::new(Value::Bytes(CACHED_OBJECT_GUID.to_vec())),
            state: Box::new(Value::Tuple(vec![
                Value::Bytes(entry.key.as_bytes().to_vec()),
                Value::Int(self.node_id),
                version_value(entry.version),
            ])),
        }
    }

    pub fn init_vals(&self) -> Value {
        let mut pairs: Vec<(Value, Value)> = self
            .entries
            .values()
            .map(|e| (Value::Bytes(e.key.as_bytes().to_vec()), self.handle(e)))
            .collect();
        pairs.sort_by(|a, b| a.0.as_bytes().cmp(&b.0.as_bytes()));
        Value::Dict(pairs)
    }

    pub fn payload(&self, entry: &Entry) -> Value {
        Value::Instance {
            class: Box::new(Value::Bytes(PAYLOAD_GUID.to_vec())),
            state: Box::new(Value::Tuple(vec![
                version_value(entry.version),
                Value::None,
                Value::Int(self.node_id),
                Value::Int(1),
                Value::Bytes(entry.pickle.clone()),
                Value::Int(entry.compressed as i64),
                Value::Bytes(entry.key.as_bytes().to_vec()),
            ])),
        }
    }
}

/// The official table behind a bulk object, for language overlays.
fn translation_table(key: &str) -> Option<&'static str> {
    Some(match key {
        "config.BulkData.types" => "invTypes",
        "config.BulkData.groups" => "invGroups",
        "config.BulkData.categories" => "invCategories",
        "config.BulkData.metagroups" => "invMetaGroups",
        "config.BulkData.dgmattribs" => "dgmAttributeTypes",
        "config.BulkData.dgmeffects" => "dgmEffects",
        "config.BulkData.billtypes" => "billTypes",
        "config.BulkData.ramaltypes" => "ramAssemblyLineTypes",
        "config.BulkData.ramactivities" => "ramActivities",
        "config.BulkData.ramcompletedstatuses" => "ramCompletedStatuses",
        "config.Roles" => "eveRoles",
        "config.Flags" => "eveFlags",
        "config.Races" => "chrRaces",
        "config.Bloodlines" => "chrBloodlines",
        "config.Statistics" => "eveStatistics",
        "config.Units" => "eveUnits",
        "config.ChannelTypes" => "channelTypes",
        "config.StaticLocations" => "eveStaticLocations",
        _ => return None,
    })
}

/// Replaces text cells named in the overlay. The first column is the table's
/// primary key; every bulk object here lists it first. Returns how many cells
/// were replaced.
fn translate(spec: &str, header: &[Value], lines: &mut [Value], overlay: &Overlay) -> usize {
    let Some(table) = translation_table(spec) else { return 0 };
    let columns: Vec<Option<String>> = header.iter().map(column_name).collect();
    let mut replaced = 0;
    for line in lines {
        let Value::List(cells) = line else { continue };
        let Some(key) = cells.first().and_then(id_text) else { continue };
        for (i, cell) in cells.iter_mut().enumerate().skip(1) {
            let Some(column) = columns.get(i).and_then(Option::as_deref) else { continue };
            let Value::Bytes(text) = cell else { continue };
            if let Some(translated) = overlay.text(table, column, &key) {
                *text = translated.as_bytes().to_vec();
                replaced += 1;
            }
        }
    }
    replaced
}

fn column_name(value: &Value) -> Option<String> {
    match value {
        Value::Bytes(b) | Value::Buffer(b) => Some(String::from_utf8_lossy(b).into_owned()),
        Value::Unicode(s) => Some(s.clone()),
        _ => None,
    }
}

fn id_text(value: &Value) -> Option<String> {
    match value {
        Value::Int(i) | Value::Long(i) => Some(i.to_string()),
        Value::Bytes(b) | Value::Buffer(b) => Some(String::from_utf8_lossy(b).into_owned()),
        Value::Unicode(s) => Some(s.clone()),
        _ => None,
    }
}

fn version_value(v: (i64, i64)) -> Value {
    Value::Tuple(vec![Value::Long(v.0), Value::Int(v.1)])
}

fn maybe_deflate(data: &[u8]) -> (Vec<u8>, bool) {
    if data.len() <= 200 {
        return (data.to_vec(), false);
    }
    let mut enc = ZlibEncoder::new(Vec::new(), Compression::new(9));
    if enc.write_all(data).is_err() {
        return (data.to_vec(), false);
    }
    match enc.finish() {
        Ok(out) if out.len() < data.len() => (out, true),
        _ => (data.to_vec(), false),
    }
}

async fn query_rows(
    db: &tokio_postgres::Client,
    sql: &str,
    numeric_text: &[&str],
) -> Result<(Vec<Value>, Vec<Value>), tokio_postgres::Error> {
    use tokio_postgres::types::Type;

    let stmt = db.prepare(sql).await?;
    let header: Vec<Value> = stmt.columns().iter().map(|c| Value::bytes(c.name())).collect();
    let numeric: Vec<bool> =
        stmt.columns().iter().map(|c| numeric_text.contains(&c.name())).collect();
    let rows = db.query(&stmt, &[]).await?;
    let mut lines = Vec::new();
    for row in &rows {
        let mut line = Vec::with_capacity(row.len());
        for (i, col) in row.columns().iter().enumerate() {
            line.push(match *col.type_() {
                Type::INT2 => opt(row.get::<_, Option<i16>>(i).map(|v| Value::Int(v as i64))),
                Type::INT4 => opt(row.get::<_, Option<i32>>(i).map(|v| Value::Int(v as i64))),
                Type::INT8 => opt(row.get::<_, Option<i64>>(i).map(Value::Long)),
                Type::FLOAT4 => {
                    opt(row.get::<_, Option<f32>>(i).map(|v| Value::Double(v as f64)))
                }
                Type::FLOAT8 => opt(row.get::<_, Option<f64>>(i).map(Value::Double)),
                Type::BOOL => opt(row.get::<_, Option<bool>>(i).map(|v| Value::Int(v as i64))),
                _ => opt(row.get::<_, Option<String>>(i).map(|v| {
                    if numeric[i] {
                        numeric_value(&v)
                    } else {
                        Value::Bytes(v.into_bytes())
                    }
                })),
            });
        }
        lines.push(Value::List(line));
    }
    Ok((header, lines))
}

fn opt(v: Option<Value>) -> Value {
    v.unwrap_or(Value::None)
}

fn numeric_value(s: &str) -> Value {
    let t = s.trim();
    if let Ok(i) = t.parse::<i64>() {
        return Value::Int(i);
    }
    match t.parse::<f64>() {
        Ok(f) => Value::Double(f),
        Err(_) => Value::Bytes(s.as_bytes().to_vec()),
    }
}

pub fn filetime_now() -> i64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    const EPOCH_DIFF_SECS: i64 = 11_644_473_600;
    let d = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default();
    (d.as_secs() as i64 + EPOCH_DIFF_SECS) * 10_000_000 + (d.subsec_nanos() as i64 / 100)
}

pub fn service_info() -> Value {
    Value::Dict(Vec::new())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn overlay(raw: &str) -> Overlay {
        serde_json::from_str(raw).unwrap()
    }

    #[test]
    fn translation_replaces_only_overlaid_cells() {
        let overlay = overlay(
            r#"{"invTypes":{"typeName":{"587":"裂谷级"},"description":{"587":"描述"}}}"#,
        );
        let header = vec![
            Value::bytes("typeID"),
            Value::bytes("typeName"),
            Value::bytes("description"),
            Value::bytes("groupID"),
        ];
        let mut lines = vec![
            Value::List(vec![
                Value::Int(587),
                Value::bytes("Rifter"),
                Value::bytes("A frigate."),
                Value::Int(25),
            ]),
            // A type the overlay does not know stays English.
            Value::List(vec![
                Value::Int(588),
                Value::bytes("Reaper"),
                Value::None,
                Value::Int(237),
            ]),
        ];
        assert_eq!(
            translate("config.BulkData.types", &header, &mut lines, &overlay),
            2
        );
        let Value::List(first) = &lines[0] else { panic!("line is not a list") };
        assert_eq!(first[0], Value::Int(587));
        assert_eq!(first[1], Value::bytes("裂谷级"));
        assert_eq!(first[2], Value::bytes("描述"));
        assert_eq!(first[3], Value::Int(25));
        let Value::List(second) = &lines[1] else { panic!("line is not a list") };
        assert_eq!(second[1], Value::bytes("Reaper"));
    }

    #[test]
    fn objects_without_a_table_are_left_alone() {
        let overlay = overlay(r#"{"invTypes":{"typeName":{"587":"裂谷级"}}}"#);
        let header = vec![Value::bytes("messageID"), Value::bytes("messageText")];
        let mut lines = vec![Value::List(vec![Value::Int(587), Value::bytes("Rifter")])];
        assert_eq!(
            translate("config.BulkData.messages", &header, &mut lines, &overlay),
            0
        );
        let Value::List(cells) = &lines[0] else { panic!("line is not a list") };
        assert_eq!(cells[1], Value::bytes("Rifter"));
    }

    #[test]
    fn a_language_picks_its_bulk_or_falls_back_to_english() {
        let empty = || BulkData { entries: HashMap::new(), node_id: 1 };
        let mut by_lang = HashMap::new();
        by_lang.insert("ZH".to_string(), empty());
        let set = BulkSet { base: empty(), by_lang };
        assert!(std::ptr::eq(set.for_lang(Some("zh")), &set.by_lang["ZH"]));
        assert!(std::ptr::eq(set.for_lang(Some("DE")), &set.base));
        assert!(std::ptr::eq(set.for_lang(None), &set.base));
    }
}
