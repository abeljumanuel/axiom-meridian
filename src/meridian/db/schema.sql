-- Scopes jerárquicos
CREATE TABLE scopes (
  id          TEXT PRIMARY KEY,
  type        TEXT NOT NULL,
  name        TEXT NOT NULL,
  parent_id   TEXT REFERENCES scopes(id)
);

-- Atributos dinámicos de scope (ADR-002)
CREATE TABLE scope_attributes (
  scope_id  TEXT NOT NULL REFERENCES scopes(id) ON DELETE CASCADE,
  key       TEXT NOT NULL,
  value     TEXT NOT NULL,
  PRIMARY KEY (scope_id, key)
);

-- Reglas técnicas
CREATE TABLE rules (
  id                  TEXT PRIMARY KEY,
  scope_id            TEXT NOT NULL REFERENCES scopes(id),
  code                TEXT NOT NULL UNIQUE,
  text                TEXT NOT NULL,
  category            TEXT NOT NULL,
  severity            TEXT NOT NULL,
  applies_to          TEXT,
  tags                TEXT,
  status              TEXT DEFAULT 'active' CHECK (status IN ('active', 'deprecated')),
  source_type         TEXT,
  source_ref          TEXT,
  file_path           TEXT,
  file_offset         INTEGER,
  byte_length         INTEGER,
  originated_lesson_id TEXT REFERENCES lessons(id),
  embedding_id        TEXT,
  created_at          TEXT DEFAULT (datetime('now')),
  updated_at          TEXT DEFAULT (datetime('now'))
);

-- Atributos dinámicos de reglas (ADR-002)
CREATE TABLE rule_attributes (
  rule_id   TEXT NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
  key       TEXT NOT NULL,
  value     TEXT NOT NULL,
  PRIMARY KEY (rule_id, key)
);

-- Historial de cambios de reglas (append-only)
CREATE TABLE rule_history (
  id            TEXT PRIMARY KEY,
  rule_id       TEXT NOT NULL REFERENCES rules(id),
  change_type   TEXT NOT NULL,
  previous_text TEXT,
  new_text      TEXT,
  reason        TEXT,
  triggered_by  TEXT,
  changed_at    TEXT DEFAULT (datetime('now'))
);

-- Historial de cambios de lecciones (append-only, simplificado)
CREATE TABLE lesson_history (
  id            TEXT PRIMARY KEY,
  lesson_id     TEXT NOT NULL REFERENCES lessons(id),
  change_type   TEXT NOT NULL,
  previous_text TEXT,
  new_text      TEXT,
  reason        TEXT,
  triggered_by  TEXT,
  changed_at    TEXT DEFAULT (datetime('now'))
);

-- Lecciones aprendidas
CREATE TABLE lessons (
  id                TEXT PRIMARY KEY,
  scope_id          TEXT NOT NULL REFERENCES scopes(id),
  code              TEXT NOT NULL UNIQUE,
  project           TEXT,
  date_occurred     TEXT,
  severity          TEXT,
  area_affected     TEXT,
  what_happened     TEXT,
  impact            TEXT,
  root_cause        TEXT,
  resolution        TEXT,
  tags              TEXT,
  originated_rule_id TEXT REFERENCES rules(id),
  status            TEXT DEFAULT 'active' CHECK (status IN ('active', 'deprecated')),
  file_path         TEXT,
  file_offset       INTEGER,
  byte_length       INTEGER,
  embedding_id      TEXT,
  source_type       TEXT,
  source_ref        TEXT,
  created_at        TEXT DEFAULT (datetime('now')),
  updated_at        TEXT DEFAULT (datetime('now'))
);

-- Vínculos bidireccionales regla ↔ lección
CREATE TABLE rule_lesson_links (
  rule_id   TEXT NOT NULL REFERENCES rules(id),
  lesson_id TEXT NOT NULL REFERENCES lessons(id),
  link_type TEXT NOT NULL,
  PRIMARY KEY (rule_id, lesson_id)
);

-- Cache de resolución de scopes
CREATE TABLE project_scope_resolution (
  project_id      TEXT PRIMARY KEY,
  resolved_scopes TEXT NOT NULL,
  updated_at      TEXT DEFAULT (datetime('now'))
);

-- Registro de auditorías de PR
CREATE TABLE pr_audits (
  id               TEXT PRIMARY KEY,
  project_id       TEXT NOT NULL,
  pr_ref           TEXT,
  diff_hash        TEXT,
  rules_evaluated  INTEGER,
  violations_found TEXT,
  feedback_analyzed TEXT,
  rule_version_snapshot TEXT,
  audited_at       TEXT DEFAULT (datetime('now'))
);

-- Registro de checks de planning
CREATE TABLE planning_checks (
  id                  TEXT PRIMARY KEY,
  project_id          TEXT NOT NULL,
  feature_description TEXT,
  conflicts_found     TEXT,
  rules_involved      TEXT,
  checked_at          TEXT DEFAULT (datetime('now'))
);

-- Propuestas pendientes de aprobación
CREATE TABLE pending_proposals (
  id                   TEXT PRIMARY KEY,
  type                 TEXT NOT NULL,
  scope_id             TEXT REFERENCES scopes(id),
  target_id            TEXT,
  proposed_text        TEXT NOT NULL,
  metadata             TEXT,
  suggested_attributes TEXT,
  source_type          TEXT,
  source_ref           TEXT,
  status               TEXT DEFAULT 'pending',
  reason               TEXT,
  legacy_original      TEXT,
  created_at           TEXT DEFAULT (datetime('now'))
);

-- Registro de acceso a tools (audit trail de seguridad)
CREATE TABLE access_log (
  id          TEXT PRIMARY KEY,
  timestamp   TEXT DEFAULT (datetime('now')),
  tool_name   TEXT NOT NULL,
  access_level TEXT NOT NULL,
  project_id  TEXT,
  parameters  TEXT,
  result      TEXT NOT NULL,
  transport   TEXT
);

-- Índices para rendimiento
CREATE INDEX idx_rules_scope_id ON rules(scope_id);
CREATE INDEX idx_rules_severity ON rules(severity);
CREATE INDEX idx_rules_category ON rules(category);
CREATE INDEX idx_rules_status ON rules(status);
CREATE INDEX idx_scope_attributes_key_value ON scope_attributes(key, value);
CREATE INDEX idx_rule_attributes_key_value ON rule_attributes(key, value);
CREATE INDEX idx_lessons_scope_id ON lessons(scope_id);
CREATE INDEX idx_pending_proposals_status ON pending_proposals(status);
CREATE INDEX idx_pending_proposals_target_id ON pending_proposals(target_id);
CREATE INDEX idx_access_log_timestamp ON access_log(timestamp);
CREATE INDEX idx_access_log_tool_name ON access_log(tool_name);

-- Inserts iniciales de scopes
INSERT INTO scopes VALUES ('global',              'global', 'Global',              NULL);
INSERT INTO scopes VALUES ('global-java',         'global', 'Global Java',         'global');
INSERT INTO scopes VALUES ('global-quarkus',      'global', 'Global Quarkus',      'global-java');
INSERT INTO scopes VALUES ('global-spring-boot',  'global', 'Global Spring Boot',  'global-java');
INSERT INTO scopes VALUES ('global-nestjs',       'global', 'Global NestJS',       'global');
INSERT INTO scopes VALUES ('global-go',           'global', 'Global Go',           'global');
INSERT INTO scopes VALUES ('global-go-fiber',     'global', 'Global Go Fiber',     'global-go');
INSERT INTO scopes VALUES ('global-go-gin',       'global', 'Global Go Gin',       'global-go');
INSERT INTO scopes VALUES ('global-flutter',      'global', 'Global Flutter',      'global');

INSERT INTO scopes VALUES ('project-project-example', 'project', 'Project Example',  'global-quarkus');
INSERT INTO scopes VALUES ('project-other-project-example',     'project', 'other-project-example',      'global-nestjs');
INSERT INTO scopes VALUES ('project-ledger',         'project', 'Ledger',          'global-flutter');

-- Atributos de proyecto
INSERT INTO scope_attributes VALUES ('project-project-example', 'framework',      'quarkus');
INSERT INTO scope_attributes VALUES ('project-project-example', 'component_role', 'gateway');
INSERT INTO scope_attributes VALUES ('project-project-example', 'runtime_version','java-21');
INSERT INTO scope_attributes VALUES ('project-other-project-example',     'framework',      'nestjs');
INSERT INTO scope_attributes VALUES ('project-other-project-example',     'component_role', 'last-mile');
INSERT INTO scope_attributes VALUES ('project-ledger',         'framework',      'flutter');
INSERT INTO scope_attributes VALUES ('project-ledger',         'component_role', 'mobile-client');

-- Atributos de scope global
INSERT INTO scope_attributes VALUES ('global-java',        'framework', 'java');
INSERT INTO scope_attributes VALUES ('global-quarkus',     'framework', 'quarkus');
INSERT INTO scope_attributes VALUES ('global-spring-boot', 'framework', 'spring-boot');
INSERT INTO scope_attributes VALUES ('global-nestjs',      'framework', 'nestjs');
INSERT INTO scope_attributes VALUES ('global-go',          'framework', 'go');
INSERT INTO scope_attributes VALUES ('global-go-fiber',    'framework', 'go-fiber');
INSERT INTO scope_attributes VALUES ('global-go-gin',      'framework', 'go-gin');
INSERT INTO scope_attributes VALUES ('global-flutter',     'framework', 'flutter');
