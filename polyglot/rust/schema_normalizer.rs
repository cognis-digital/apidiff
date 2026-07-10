use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashMap, HashSet};
use std::hash::{Hash, Hasher};
use sha2::{Sha256, Digest};
use thiserror::Error;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Info {
    pub title: String,
    #[serde(default)]
    pub version: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PathItem {
    #[serde(flatten)]
    pub operations: BTreeMap<String, Operation>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Operation {
    #[serde(default)]
    pub responses: BTreeMap<u32, Response>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Response {
    #[serde(default)]
    pub content: BTreeMap<String, MediaType>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MediaType {
    #[serde(default)]
    pub schema: SchemaRef,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum SchemaRef {
    Inline(Schema),
    Ref(String),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Schema {
    #[serde(default)]
    pub type_: String,
    #[serde(default)]
    pub properties: BTreeMap<String, Schema>,
    #[serde(default)]
    pub required: Vec<String>,
    #[serde(default)]
    pub items: Option<Box<Schema>>,
}

#[derive(Debug, Error)]
pub enum NormalizationError {
    #[error("Missing required field in schema")]
    MissingRequiredField(String),
    #[error("Invalid type specification")]
    InvalidType(String),
    #[error("Circular reference detected at path: {0:?}")]
    CircularReference(Vec<String>),
}

pub struct NormalizerConfig {
    pub snake_case_fields: bool,
    pub sort_properties: bool,
    pub normalize_types: bool,
    pub include_metadata: bool,
}

impl Default for NormalizerConfig {
    fn default() -> Self {
        Self {
            snake_case_fields: true,
            sort_properties: true,
            normalize_types: true,
            include_metadata: false,
        }
    }
}

pub struct SchemaNormalizer {
    config: NormalizerConfig,
    visited: HashSet<String>,
    current_path: Vec<String>,
}

impl Default for SchemaNormalizer {
    fn default() -> Self {
        Self::new(NormalizerConfig::default())
    }
}

impl SchemaNormalizer {
    pub fn new(config: NormalizerConfig) -> Self {
        Self {
            config,
            visited: HashSet::new(),
            current_path: Vec::new(),
        }
    }

    pub fn normalize(&mut self, schema: &mut Schema) -> Result<(), NormalizationError> {
        if self.config.sort_properties {
            let mut props = schema.properties.clone();
            let mut required = schema.required.clone();
            
            // Sort properties by name for consistent ordering
            let sorted_props: BTreeMap<_, _> = props.into_iter()
                .collect::<Vec<_>>()
                .into_iter()
                .sorted_by_key(|(name, _)| {
                    self.normalize_name(name)
                })
                .collect();
            
            schema.properties = sorted_props;
            
            // Sort required fields too
            let sorted_required: Vec<_> = required.into_iter()
                .map(|n| self.normalize_name(&n))
                .sorted()
                .collect();
            schema.required = sorted_required;
        }

        if self.config.normalize_types {
            Self::normalize_type_recursive(schema, &mut HashSet::new())?;
        }

        Ok(())
    }

    fn normalize_name(&self, name: &str) -> String {
        let normalized = if self.config.snake_case_fields {
            // Convert camelCase/PascalCase to snake_case
            name.chars()
                .flat_map(|c| c.to_string().chars())
                .collect::<String>()
                .replace(['-', '_'], " ")
                .split_whitespace()
                .map(|s| s.to_ascii_lowercase())
                .collect::<Vec<_>>()
                .join("_")
        } else {
            name.to_ascii_lowercase()
        };

        // Remove leading/trailing underscores and collapse multiple
        normalized.trim_matches('_').replace('_', "")
    }

    fn normalize_type_recursive(
        schema: &mut Schema,
        visited_types: &mut HashSet<String>,
    ) -> Result<(), NormalizationError> {
        let type_key = format!("{}::{}", self.current_path.join("::"), schema.type_);

        if self.config.normalize_types && !schema.type_.is_empty() {
            // Normalize common type variations
            let normalized_type = match schema.type_.to_lowercase().as_str() {
                "string" | "String" => "STRING",
                "integer" | "Integer" | "int" | "Int" => "INTEGER",
                "number" | "Number" | "float" | "Float" => "FLOAT",
                "boolean" | "Boolean" | "bool" | "Bool" => "BOOLEAN",
                "array" | "Array" | "list" | "List" => "ARRAY",
                _ => &schema.type_,
            };

            if schema.type_ != normalized_type {
                schema.type_ = normalized_type.to_string();
            }
        }

        // Recurse into properties
        for (_name, prop) in schema.properties.iter_mut() {
            Self::normalize_type_recursive(prop, visited_types)?;
        }

        // Handle items (for arrays)
        if let Some(items) = &mut schema.items {
            Self::normalize_type_recursive(items, visited_types)?;
        }

        Ok(())
    }

    pub fn compute_hash(&self, schema: &Schema) -> String {
        let mut hasher = Sha256::new();
        
        // Serialize with sorted keys for deterministic output
        let normalized_schema = serde_json::to_string(schema).unwrap_or_default();
        hasher.update(normalized_schema.as_bytes());
        
        format!("{:x}", hasher.finalize())
    }

    pub fn detect_changes(
        &self,
        old: &Schema,
        new: &Schema,
    ) -> Vec<ChangeType> {
        let mut changes = Vec::new();

        // Check type changes
        if old.type_ != new.type_ {
            changes.push(ChangeType::TypeChanged(old.type_.clone(), new.type_.clone()));
        }

        // Check property additions/removals
        let old_props: HashSet<_> = old.properties.keys().cloned().collect();
        let new_props: HashSet<_> = new.properties.keys().cloned().collect();

        if !old_props.symmetric_difference(&new_props).is_empty() {
            let added: Vec<_> = new_props.symmetric_difference(&old_props)
                .filter(|k| old_props.contains(k))
                .map(|k| ChangeType::PropertyRemoved((*k).clone(), "removed".to_string()))
                .collect();
            changes.extend(added);

            let removed: Vec<_> = old_props.symmetric_difference(&new_props)
                .filter(|k| new_props.contains(k))
                .map(|k| ChangeType::PropertyAdded((*k).clone(), "added".to_string()))
                .collect();
            changes.extend(removed);
        }

        // Check property type changes
        for (name, old_prop) in &old.properties {
            if let Some(new_prop) = new.properties.get(name) {
                if old_prop.type_ != new_prop.type_ {
                    changes.push(ChangeType::PropertyTypeChanged(
                        name.clone(),
                        old_prop.type_.clone(),
                        new_prop.type_.clone(),
                    ));
                }

                // Check required status
                let was_required = old.required.contains(name);
                let is_required = new.required.contains(name);
                if was_required != is_required {
                    changes.push(ChangeType::PropertyRequiredChanged(
                        name.clone(),
                        was_required,
                        is_required,
                    ));
                }

                // Check property removal from required list
                if !was_required && is_required && old.required.contains(name) {
                    continue;
                }
            } else {
                changes.push(ChangeType::PropertyRemoved(
                    name.clone(),
                    "removed".to_string(),
                ));
            }
        }

        // Check items type change (for arrays)
        if let Some(old_items) = &old.items {
            if let Some(new_items) = &new.items {
                if old_items.type_ != new_items.type_ {
                    changes.push(ChangeType::ArrayTypeChanged(
                        old_items.type_.clone(),
                        new_items.type_.clone(),
                    ));
                }
            } else {
                changes.push(ChangeType::ArrayItemsRemoved);
            }
        }

        // Check items removal (array becoming non-array)
        if let Some(old_items) = &old.items {
            if new.items.is_none() {
                changes.push(ChangeType::ArrayBecameNonArray);
            }
        }

        // Check items addition (non-array becoming array)
        if old.items.is_none() && new.items.is_some() {
            changes.push(ChangeType::NonArrayBecameArray);
        }

        changes.sort();
        changes.dedup();
        changes
    }

    pub fn is_breaking_change(&self, changes: &[ChangeType]) -> bool {
        let breaking_types = [
            ChangeType::PropertyRemoved(_),
            ChangeType::PropertyTypeChanged(_, _, _),
            ChangeType::ArrayTypeChanged(_, _),
            ChangeType::ArrayBecameNonArray,
            ChangeType::NonArrayBecameArray,
        ];

        changes.iter().any(|c| {
            breaking_types.iter()
                .any(|bt| bt == c || (bt.0 == &ChangeType::PropertyRemoved(_) && c == bt))
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub enum ChangeType {
    PropertyAdded(String, String),
    PropertyRemoved(String, String),
    TypeChanged(String, String),
    PropertyTypeChanged(String, String, String),
    PropertyRequiredChanged(String, bool, bool),
    ArrayTypeChanged(String, String),
    ArrayBecameNonArray,
    NonArrayBecameArray,
}

impl ChangeType {
    pub fn is_breaking(&self) -> bool {
        matches!(
            self,
            Self::PropertyRemoved(_, _)
                | Self::PropertyTypeChanged(_, _, _)
                | Self::ArrayTypeChanged(_, _)
                | Self::ArrayBecameNonArray
                | Self::NonArrayBecameArray
        )
    }

    pub fn severity(&self) -> u8 {
        match self {
            Self::PropertyRemoved(_, _) => 3,
            Self::PropertyTypeChanged(_, _, _) => 2,
            Self::ArrayTypeChanged(_, _) | Self::ArrayBecameNonArray | Self::NonArrayBecameArray => 2,
            _ => 1,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_normalize_camel_case_to_snake() {
        let mut schema = Schema {
            type_: "User".to_string(),
            properties: BTreeMap::new(),
            required: Vec::new(),
            items: None,
        };

        let mut normalizer = SchemaNormalizer::default();
        normalizer.normalize(&mut schema).unwrap();

        assert_eq!(schema.type_, "USER");
    }

    #[test]
    fn test_normalize_type_consistency() {
        let mut schema = Schema {
            type_: "String".to_string(),
            properties: BTreeMap::new(),
            required: Vec::new(),
            items: None,
        };

        let mut normalizer = SchemaNormalizer::default();
        normalizer.normalize(&mut schema).unwrap();

        assert_eq!(schema.type_, "STRING");
    }

    #[test]
    fn test_detect_property_addition() {
        let old_schema = Schema {
            type_: "User".to_string(),
            properties: BTreeMap::from([("name".into(), Schema {
                type_: "String".to_string(),
                properties: BTreeMap::new(),
                required: Vec::new(),
                items: None,
            })]),
            required: vec!["name".to_string()],
            items: None,
        };

        let new_schema = Schema {
            type_: "User".to_string(),
            properties: BTreeMap::from([
                ("name".into(), Schema {
                    type_: "String".to_string(),
                    properties: BTreeMap::new(),
                    required: Vec::new(),
                    items: None,
                }),
                ("email".into(), Schema {
                    type_: "String".to_string(),
                    properties: BTreeMap::new(),
                    required: Vec::new(),
                    items: None,
                }),
            ]),
            required: vec!["name".to_string()],
            items: None,
        };

        let normalizer = SchemaNormalizer::default();
        let changes = normalizer.detect_changes(&old_schema, &new_schema);

        assert!(changes.iter().any(|c| c == &ChangeType::PropertyAdded("email".into(), "added".to_string())));
    }

    #[test]
    fn test_detect_property_removal() {
        let old_schema = Schema {
            type_: "User".to_string(),
            properties: BTreeMap::from([
                ("name".into(), Schema {
                    type_: "String".to_string(),
                    properties: BTreeMap::new(),
                    required: Vec::new(),
                    items: None,
                }),
                ("email".into(), Schema {
                    type_: "String".to_string(),
                    properties: BTreeMap::new(),
                    required: Vec::new(),
                    items: None,
                }),
            ]),
            required: vec!["name".to_string()],
            items: None,
        };

        let new_schema = Schema {
            type_: "User".to_string(),
            properties: BTreeMap::from([("name".into(), Schema {
                    type_: "String".to_string(),
                    properties: BTreeMap::new(),
                    required: Vec::new(),
                    items: None,
                })]),
            required: vec!["name".to_string()],
            items: None,
        };

        let normalizer = SchemaNormalizer::default();
        let changes = normalizer.detect_changes(&old_schema, &new_schema);

        assert!(changes.iter().any(|c| c == &ChangeType::PropertyRemoved("email".into(), "removed".to_string())));
    }

    #[test]
    fn test_detect_type_change() {
        let old_schema = Schema {
            type_: "User".to_string(),
            properties: BTreeMap::from([("name".into(), Schema {
                type_: "String".to_string(),
                properties: BTreeMap::new(),
                required: Vec::new(),
                items: None,
            })]),
            required: vec!["name".to_string()],
            items: None,
        };

        let new_schema = Schema {
            type_: "User".to_string(),
            properties: BTreeMap::from([("name".into(), Schema {
                type_: "INTEGER".to_string(), // Changed from STRING to INTEGER