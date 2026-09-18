-- Migration 004: Node.js/React scopes (matching the user's actual repos —
-- React + Express/TypeScript, AdonisJS) and Python/FastMCP scopes (for
-- developing axiom-meridian itself), plus a real project-axiom-meridian
-- project scope. Fresh installs get the same data directly from
-- schema.sql; this migration backfills existing databases.
--
-- INSERT OR IGNORE / idempotent UPDATE throughout: safe to re-run, and a
-- no-op on a fresh database where schema.sql already has this data.

INSERT OR IGNORE INTO scopes VALUES ('global-nodejs',  'global', 'Global Node.js',  'global');
INSERT OR IGNORE INTO scopes VALUES ('global-express',  'global', 'Global Express',  'global-nodejs');
INSERT OR IGNORE INTO scopes VALUES ('global-adonisjs', 'global', 'Global AdonisJS', 'global-nodejs');
INSERT OR IGNORE INTO scopes VALUES ('global-react',    'global', 'Global React',    'global');
INSERT OR IGNORE INTO scopes VALUES ('global-python',   'global', 'Global Python',   'global');
INSERT OR IGNORE INTO scopes VALUES ('global-fastmcp',  'global', 'Global FastMCP',  'global-python');

-- global-nestjs previously hung directly off 'global'; move it under the
-- new global-nodejs umbrella for consistency with global-java/global-go.
UPDATE scopes SET parent_id = 'global-nodejs' WHERE id = 'global-nestjs';

INSERT OR IGNORE INTO scopes VALUES ('project-axiom-meridian', 'project', 'Axiom Meridian', 'global-fastmcp');

INSERT OR IGNORE INTO scope_attributes VALUES ('global-nodejs',  'framework', 'nodejs');
INSERT OR IGNORE INTO scope_attributes VALUES ('global-express', 'framework', 'express');
INSERT OR IGNORE INTO scope_attributes VALUES ('global-adonisjs','framework', 'adonisjs');
INSERT OR IGNORE INTO scope_attributes VALUES ('global-react',   'framework', 'react');
INSERT OR IGNORE INTO scope_attributes VALUES ('global-python',  'framework', 'python');
INSERT OR IGNORE INTO scope_attributes VALUES ('global-fastmcp', 'framework', 'fastmcp');

INSERT OR IGNORE INTO scope_attributes VALUES ('project-axiom-meridian', 'framework',       'fastmcp');
INSERT OR IGNORE INTO scope_attributes VALUES ('project-axiom-meridian', 'component_role',  'mcp-server');
INSERT OR IGNORE INTO scope_attributes VALUES ('project-axiom-meridian', 'runtime_version', 'python-3.11');
