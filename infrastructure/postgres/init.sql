-- infrastructure/postgres/init.sql
-- Full DDL for the NAAS database: extensions, tables, indexes, seed data.
-- Executed automatically by the PostgreSQL Docker entrypoint on first start.
-- The naas database itself is created by the POSTGRES_DB environment variable.

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- USERS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) NOT NULL,
    display_name VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- EVENTS TABLE (core pipeline record)
-- ============================================================
CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
    protocol VARCHAR(10) NOT NULL CHECK (protocol IN ('oidc', 'saml', 'ldap')),
    client_ip INET NOT NULL,
    user_agent TEXT,
    timestamp TIMESTAMPTZ NOT NULL,
    source VARCHAR(20) DEFAULT 'user' CHECK (source IN ('user', 'simulator', 'api')),
    is_synthetic BOOLEAN DEFAULT FALSE,
    is_historical BOOLEAN DEFAULT FALSE,
    raw_attributes JSONB,
    normalized_attributes JSONB,
    enriched_signals JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_events_user_id ON events(user_id);
CREATE INDEX idx_events_timestamp ON events(timestamp DESC);
CREATE INDEX idx_events_protocol ON events(protocol);

-- ============================================================
-- POLICIES TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_id VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    version VARCHAR(50) NOT NULL,
    is_active BOOLEAN DEFAULT FALSE,
    is_shadow BOOLEAN DEFAULT FALSE,
    policy_yaml TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- RISK ASSESSMENTS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS risk_assessments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID REFERENCES events(id),
    policy_id UUID REFERENCES policies(id),
    rule_based_score FLOAT,
    ml_based_score FLOAT,
    final_score FLOAT NOT NULL,
    decision VARCHAR(20) NOT NULL CHECK (decision IN ('allow', 'step_up_mfa', 'deny')),
    shadow_decision VARCHAR(20),
    shadow_score FLOAT,
    contributing_factors JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_risk_assessments_event_id ON risk_assessments(event_id);
CREATE INDEX idx_risk_assessments_decision ON risk_assessments(decision);

-- ============================================================
-- ALERTS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID REFERENCES events(id),
    assessment_id UUID REFERENCES risk_assessments(id),
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low')),
    title VARCHAR(500) NOT NULL,
    status VARCHAR(20) DEFAULT 'new' CHECK (status IN ('new', 'acknowledged', 'investigating', 'dismissed')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_alerts_status ON alerts(status);

-- ============================================================
-- SEED DATA: Default policy
-- ============================================================
INSERT INTO policies (policy_id, name, version, is_active, is_shadow, policy_yaml) VALUES (
    'default-v1',
    'Default Risk Policy',
    '1.0.0',
    TRUE,
    FALSE,
    '
name: Default Risk Policy
version: "1.0.0"
description: Baseline risk evaluation policy for NAAS demo
is_shadow: false

signal_weights:
  ip_reputation_risk: 0.20
  normalization_risk: 0.15
  failed_login_risk: 0.15
  login_recency_risk: 0.10

conditions:
  - name: "impossible-travel"
    expression: "signals.impossible_travel"
    weight: 0.25
  - name: "contractor-after-hours"
    expression: "user.employee_type == ''contractor'' AND time.hour > 18"
    weight: 0.15
  - name: "unknown-device-off-network"
    expression: "NOT device.known_device AND NOT device.on_corporate_network"
    weight: 0.20
  - name: "known-device-off-network"
    expression: "device.known_device AND NOT device.on_corporate_network"
    weight: 0.05
  - name: "weekend-login"
    expression: "time.day_of_week >= 5"
    weight: 0.05
  - name: "foreign-contractor"
    expression: "user.employee_type == ''contractor'' AND signals.country != ''US''"
    weight: 0.15
  - name: "legacy-protocol-usage"
    expression: "event.protocol == ''ldap''"
    weight: 0.05
  - name: "dormant-account-login"
    expression: "signals.days_since_last_login > 90"
    weight: 0.10

thresholds:
  step_up_mfa: 0.3
  deny: 0.7

ensemble:
  rule_weight: 0.6
  ml_weight: 0.4
'
) ON CONFLICT (policy_id) DO NOTHING;
