CREATE TABLE IF NOT EXISTS departments (
    id UUID PRIMARY KEY,
    name VARCHAR(150) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS employees (
    id UUID PRIMARY KEY,
    employee_number VARCHAR(50) NOT NULL UNIQUE,
    full_name VARCHAR(200) NOT NULL,
    designation VARCHAR(150) NOT NULL,
    department_id UUID NOT NULL REFERENCES departments(id),
    supervisor_id UUID REFERENCES employees(id),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS kpis (
    id UUID PRIMARY KEY,
    code VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(150) NOT NULL,
    description TEXT NOT NULL,
    default_weight NUMERIC(5,2) NOT NULL DEFAULT 0 CHECK (default_weight >= 0 AND default_weight <= 100),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE kpis ADD COLUMN IF NOT EXISTS default_weight NUMERIC(5,2) NOT NULL DEFAULT 0 CHECK (default_weight >= 0 AND default_weight <= 100);


CREATE TABLE IF NOT EXISTS recommendation_rules (
    id UUID PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    category VARCHAR(100) NOT NULL,
    priority VARCHAR(20) NOT NULL DEFAULT 'medium',
    conditions JSONB NOT NULL,
    action TEXT NOT NULL,
    explanation_template TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    email VARCHAR(320) NOT NULL UNIQUE,
    full_name VARCHAR(200) NOT NULL,
    password_hash VARCHAR(256) NOT NULL,
    role VARCHAR(30) NOT NULL CHECK (role IN ('admin', 'hr', 'supervisor', 'employee')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


ALTER TABLE users ADD COLUMN IF NOT EXISTS employee_id UUID UNIQUE REFERENCES employees(id);

CREATE TABLE IF NOT EXISTS evaluation_periods (
id UUID PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL CHECK (end_date >= start_date),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);





CREATE TABLE IF NOT EXISTS assessments (
    id UUID PRIMARY KEY,
    employee_id UUID NOT NULL REFERENCES employees(id),
    period_id UUID NOT NULL REFERENCES evaluation_periods(id),
    assessment_type VARCHAR(20) NOT NULL CHECK (assessment_type IN ('self', 'supervisor')),
    status VARCHAR(20) NOT NULL DEFAULT 'submitted',
    comments VARCHAR(4000) NOT NULL DEFAULT '',
    submitted_by UUID NOT NULL REFERENCES users(id),
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_assessment_employee_period_type UNIQUE (employee_id, period_id, assessment_type)
);

CREATE TABLE IF NOT EXISTS assessment_scores (
    id UUID PRIMARY KEY,
    assessment_id UUID NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    kpi_id UUID NOT NULL REFERENCES kpis(id),
    score NUMERIC(5,2) NOT NULL CHECK (score >= 0 AND score <= 100),
    comment VARCHAR(1000) NOT NULL DEFAULT '',
    CONSTRAINT uq_assessment_score_kpi UNIQUE (assessment_id, kpi_id)
);



CREATE TABLE IF NOT EXISTS recommendations (
    id UUID PRIMARY KEY,
    employee_id UUID NOT NULL REFERENCES employees(id),
    period_id UUID NOT NULL REFERENCES evaluation_periods(id),
    rule_id UUID NOT NULL REFERENCES recommendation_rules(id),
    category VARCHAR(100) NOT NULL,
    priority VARCHAR(20) NOT NULL,
    action TEXT NOT NULL,
    explanation TEXT NOT NULL,
    context JSONB NOT NULL,
    review_status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending', 'approved', 'rejected')),
    reviewer_id UUID REFERENCES users(id),
    review_note VARCHAR(2000) NOT NULL DEFAULT '',
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_recommendation_employee_period_rule UNIQUE (employee_id, period_id, rule_id)
);

CREATE TABLE IF NOT EXISTS assessment_evidence (
    id UUID PRIMARY KEY,
    assessment_id UUID NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    title VARCHAR(200) NOT NULL,
    summary VARCHAR(2000) NOT NULL,
    source_url VARCHAR(2000),
    added_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audit_events (
    id UUID PRIMARY KEY,
    actor_id UUID,
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(100) NOT NULL,
    resource_id VARCHAR(100) NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_audit_events_created_at ON audit_events(created_at DESC);
CREATE INDEX IF NOT EXISTS ix_audit_events_resource ON audit_events(resource_type, resource_id);
