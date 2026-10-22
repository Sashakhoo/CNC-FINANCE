"""initial schema

Revision ID: 55c19b4bff17
Revises: 
Create Date: 2026-10-22 14:06:38.966514
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '55c19b4bff17'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table('provider_cache',
    sa.Column('cache_key', sa.String(length=300), nullable=False),
    sa.Column('provider', sa.String(length=80), nullable=False),
    sa.Column('value', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('cache_key', name=op.f('pk_provider_cache'))
    )
    op.create_index(op.f('ix_provider_cache_expires_at'), 'provider_cache', ['expires_at'], unique=False)
    op.create_index(op.f('ix_provider_cache_provider'), 'provider_cache', ['provider'], unique=False)
    op.create_table('training_programs',
    sa.Column('code', sa.String(length=60), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('target_departments', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('keywords', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_training_programs')),
    sa.UniqueConstraint('code', name=op.f('uq_training_programs_code'))
    )
    op.create_table('users',
    sa.Column('finance_username', sa.String(length=80), nullable=False),
    sa.Column('finance_role', sa.String(length=40), nullable=False),
    sa.Column('role', sa.Enum('ADMIN', 'SALES', 'VIEWER', name='role', native_enum=False, length=40), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('finance_username', name=op.f('uq_users_finance_username'))
    )
    op.create_table('audit_logs',
    sa.Column('user_id', sa.BigInteger(), nullable=True),
    sa.Column('action', sa.String(length=60), nullable=False),
    sa.Column('entity_type', sa.String(length=40), nullable=True),
    sa.Column('entity_id', sa.String(length=60), nullable=True),
    sa.Column('meta', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_audit_logs_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs'))
    )
    op.create_index(op.f('ix_audit_logs_action'), 'audit_logs', ['action'], unique=False)
    op.create_index(op.f('ix_audit_logs_created_at'), 'audit_logs', ['created_at'], unique=False)
    op.create_index(op.f('ix_audit_logs_user_id'), 'audit_logs', ['user_id'], unique=False)
    op.create_table('campaigns',
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('program_id', sa.BigInteger(), nullable=True),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('owner_id', sa.BigInteger(), nullable=True),
    sa.Column('target_filters', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=20), server_default='DRAFT', nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_campaigns_owner_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['program_id'], ['training_programs.id'], name=op.f('fk_campaigns_program_id_training_programs'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_campaigns'))
    )
    op.create_index(op.f('ix_campaigns_deleted_at'), 'campaigns', ['deleted_at'], unique=False)
    op.create_table('companies',
    sa.Column('legal_name', sa.String(length=300), nullable=False),
    sa.Column('display_name', sa.String(length=300), nullable=False),
    sa.Column('normalized_name', sa.String(length=300), nullable=False),
    sa.Column('website', sa.String(length=500), nullable=True),
    sa.Column('domain', sa.String(length=255), nullable=True),
    sa.Column('domain_confidence', sa.Float(), nullable=True),
    sa.Column('domain_status', sa.String(length=20), server_default='UNRESOLVED', nullable=False),
    sa.Column('industry', sa.String(length=120), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('employee_estimate', sa.Integer(), nullable=True),
    sa.Column('employee_estimate_source', sa.String(length=300), nullable=True),
    sa.Column('phone', sa.String(length=60), nullable=True),
    sa.Column('general_email', sa.String(length=320), nullable=True),
    sa.Column('deal_value', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('is_demo', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('created_by_id', sa.BigInteger(), nullable=True),
    sa.Column('last_crawled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_enriched_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=op.f('fk_companies_created_by_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_companies'))
    )
    op.create_index(op.f('ix_companies_deleted_at'), 'companies', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_companies_domain'), 'companies', ['domain'], unique=False)
    op.create_index(op.f('ix_companies_industry'), 'companies', ['industry'], unique=False)
    op.create_index(op.f('ix_companies_is_demo'), 'companies', ['is_demo'], unique=False)
    op.create_index(op.f('ix_companies_normalized_name'), 'companies', ['normalized_name'], unique=False)
    op.create_index('ix_companies_normalized_name_trgm', 'companies', ['normalized_name'], unique=False, postgresql_using='gin', postgresql_ops={'normalized_name': 'gin_trgm_ops'})
    op.create_index('uq_companies_domain_live', 'companies', ['domain'], unique=True, postgresql_where='domain IS NOT NULL AND deleted_at IS NULL')
    op.create_table('duplicate_candidates',
    sa.Column('entity_type', sa.String(length=20), nullable=False),
    sa.Column('left_id', sa.Integer(), nullable=False),
    sa.Column('right_id', sa.Integer(), nullable=False),
    sa.Column('similarity', sa.Float(), nullable=False),
    sa.Column('reasons', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='OPEN', nullable=False),
    sa.Column('resolved_by_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['resolved_by_id'], ['users.id'], name=op.f('fk_duplicate_candidates_resolved_by_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_duplicate_candidates')),
    sa.UniqueConstraint('entity_type', 'left_id', 'right_id', name='uq_duplicate_pair')
    )
    op.create_index(op.f('ix_duplicate_candidates_left_id'), 'duplicate_candidates', ['left_id'], unique=False)
    op.create_index(op.f('ix_duplicate_candidates_right_id'), 'duplicate_candidates', ['right_id'], unique=False)
    op.create_index(op.f('ix_duplicate_candidates_status'), 'duplicate_candidates', ['status'], unique=False)
    op.create_table('notifications',
    sa.Column('user_id', sa.BigInteger(), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('link', sa.String(length=300), nullable=True),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_notifications_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notifications'))
    )
    op.create_index(op.f('ix_notifications_created_at'), 'notifications', ['created_at'], unique=False)
    op.create_index(op.f('ix_notifications_user_id'), 'notifications', ['user_id'], unique=False)
    op.create_table('prospect_searches',
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('criteria', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_by_id', sa.BigInteger(), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=op.f('fk_prospect_searches_created_by_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_prospect_searches'))
    )
    op.create_index(op.f('ix_prospect_searches_deleted_at'), 'prospect_searches', ['deleted_at'], unique=False)
    op.create_table('settings',
    sa.Column('key', sa.String(length=80), nullable=False),
    sa.Column('value', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('updated_by_id', sa.BigInteger(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['updated_by_id'], ['users.id'], name=op.f('fk_settings_updated_by_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('key', name=op.f('pk_settings'))
    )
    op.create_table('suppression_list',
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('value', sa.String(length=320), nullable=False),
    sa.Column('reason', sa.Text(), server_default='', nullable=False),
    sa.Column('created_by_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=op.f('fk_suppression_list_created_by_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_suppression_list')),
    sa.UniqueConstraint('kind', 'value', name='uq_suppression_kind_value')
    )
    op.create_table('contacts',
    sa.Column('company_id', sa.BigInteger(), nullable=False),
    sa.Column('full_name', sa.String(length=200), nullable=False),
    sa.Column('normalized_name', sa.String(length=200), nullable=False),
    sa.Column('first_name', sa.String(length=100), nullable=True),
    sa.Column('last_name', sa.String(length=100), nullable=True),
    sa.Column('original_title', sa.String(length=200), nullable=True),
    sa.Column('normalized_title', sa.String(length=120), nullable=True),
    sa.Column('department', sa.Enum('HR', 'L&D', 'IT', 'Engineering', 'Operations', 'Management', 'Other', name='department', native_enum=False, length=40), nullable=True),
    sa.Column('seniority', sa.Enum('Individual', 'Manager', 'Head', 'Director', 'VP', 'C-Level', 'Owner', name='seniority', native_enum=False, length=40), nullable=True),
    sa.Column('phone', sa.String(length=60), nullable=True),
    sa.Column('status', sa.Enum('NEW', 'REVIEW', 'APPROVED', 'REJECTED', 'CONTACTED', 'REPLIED', 'MEETING', 'PROPOSAL', 'WON', 'LOST', 'DO_NOT_CONTACT', name='pipeline_status', native_enum=False, length=40), server_default='REVIEW', nullable=False),
    sa.Column('status_changed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_contacted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('follow_up_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('owner_id', sa.BigInteger(), nullable=True),
    sa.Column('is_demo', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_contacts_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_contacts_owner_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_contacts'))
    )
    op.create_index(op.f('ix_contacts_company_id'), 'contacts', ['company_id'], unique=False)
    op.create_index(op.f('ix_contacts_deleted_at'), 'contacts', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_contacts_department'), 'contacts', ['department'], unique=False)
    op.create_index(op.f('ix_contacts_is_demo'), 'contacts', ['is_demo'], unique=False)
    op.create_index(op.f('ix_contacts_normalized_name'), 'contacts', ['normalized_name'], unique=False)
    op.create_index('ix_contacts_normalized_name_trgm', 'contacts', ['normalized_name'], unique=False, postgresql_using='gin', postgresql_ops={'normalized_name': 'gin_trgm_ops'})
    op.create_index(op.f('ix_contacts_status'), 'contacts', ['status'], unique=False)
    op.create_table('jobs',
    sa.Column('job_type', sa.String(length=60), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('status', sa.Enum('QUEUED', 'RUNNING', 'PAUSED', 'COMPLETED', 'FAILED', 'CANCELLED', name='job_status', native_enum=False, length=40), server_default='QUEUED', nullable=False),
    sa.Column('search_id', sa.BigInteger(), nullable=True),
    sa.Column('provider', sa.String(length=80), nullable=True),
    sa.Column('celery_task_id', sa.String(length=80), nullable=True),
    sa.Column('params', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('counters', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('progress', sa.Float(), server_default='0', nullable=False),
    sa.Column('stage', sa.String(length=80), nullable=True),
    sa.Column('records_processed', sa.Integer(), server_default='0', nullable=False),
    sa.Column('records_created', sa.Integer(), server_default='0', nullable=False),
    sa.Column('warnings', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('errors', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('cancel_requested', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by_id', sa.BigInteger(), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=op.f('fk_jobs_created_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['search_id'], ['prospect_searches.id'], name=op.f('fk_jobs_search_id_prospect_searches'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_jobs'))
    )
    op.create_index(op.f('ix_jobs_job_type'), 'jobs', ['job_type'], unique=False)
    op.create_index(op.f('ix_jobs_status'), 'jobs', ['status'], unique=False)
    op.create_table('training_opportunities',
    sa.Column('company_id', sa.BigInteger(), nullable=False),
    sa.Column('program_id', sa.BigInteger(), nullable=False),
    sa.Column('match_score', sa.Integer(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('target_department', sa.String(length=60), nullable=True),
    sa.Column('recommended_decision_maker', sa.String(length=120), nullable=True),
    sa.Column('evidence', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('alternative_program_ids', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('method', sa.String(length=20), nullable=False),
    sa.Column('is_current', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('computed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_training_opportunities_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['program_id'], ['training_programs.id'], name=op.f('fk_training_opportunities_program_id_training_programs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_training_opportunities'))
    )
    op.create_index(op.f('ix_training_opportunities_company_id'), 'training_opportunities', ['company_id'], unique=False)
    op.create_index(op.f('ix_training_opportunities_is_current'), 'training_opportunities', ['is_current'], unique=False)
    op.create_index(op.f('ix_training_opportunities_program_id'), 'training_opportunities', ['program_id'], unique=False)
    op.create_table('activities',
    sa.Column('contact_id', sa.BigInteger(), nullable=True),
    sa.Column('company_id', sa.BigInteger(), nullable=True),
    sa.Column('activity_type', sa.String(length=40), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('meta', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_activities_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], name=op.f('fk_activities_contact_id_contacts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_activities_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_activities'))
    )
    op.create_index(op.f('ix_activities_activity_type'), 'activities', ['activity_type'], unique=False)
    op.create_index(op.f('ix_activities_company_id'), 'activities', ['company_id'], unique=False)
    op.create_index(op.f('ix_activities_contact_id'), 'activities', ['contact_id'], unique=False)
    op.create_index(op.f('ix_activities_created_at'), 'activities', ['created_at'], unique=False)
    op.create_table('campaign_contacts',
    sa.Column('campaign_id', sa.BigInteger(), nullable=False),
    sa.Column('contact_id', sa.BigInteger(), nullable=False),
    sa.Column('added_by_id', sa.BigInteger(), nullable=True),
    sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['added_by_id'], ['users.id'], name=op.f('fk_campaign_contacts_added_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], name=op.f('fk_campaign_contacts_campaign_id_campaigns'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], name=op.f('fk_campaign_contacts_contact_id_contacts'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('campaign_id', 'contact_id', name=op.f('pk_campaign_contacts'))
    )
    op.create_index(op.f('ix_campaign_contacts_contact_id'), 'campaign_contacts', ['contact_id'], unique=False)
    op.create_table('contact_confidence_scores',
    sa.Column('contact_id', sa.BigInteger(), nullable=False),
    sa.Column('score', sa.Integer(), nullable=False),
    sa.Column('breakdown', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('is_current', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('computed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], name=op.f('fk_contact_confidence_scores_contact_id_contacts'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_contact_confidence_scores'))
    )
    op.create_index(op.f('ix_contact_confidence_scores_contact_id'), 'contact_confidence_scores', ['contact_id'], unique=False)
    op.create_index(op.f('ix_contact_confidence_scores_is_current'), 'contact_confidence_scores', ['is_current'], unique=False)
    op.create_table('contact_emails',
    sa.Column('contact_id', sa.BigInteger(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('email_type', sa.Enum('PERSONAL_BUSINESS', 'ROLE', 'GENERIC', name='email_type', native_enum=False, length=40), nullable=False),
    sa.Column('discovery_method', sa.Enum('PUBLIC_WEBSITE', 'PROVIDER', 'EMAIL_PATTERN', 'USER_IMPORT', 'USER_ENTRY', name='email_discovery_method', native_enum=False, length=40), nullable=False),
    sa.Column('provenance', sa.Enum('DISCOVERED', 'INFERRED', 'ENRICHED', 'VERIFIED', 'USER_PROVIDED', name='provenance', native_enum=False, length=40), nullable=False),
    sa.Column('source', sa.String(length=120), nullable=True),
    sa.Column('source_url', sa.String(length=1000), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('verification_status', sa.Enum('VERIFIED', 'LIKELY', 'UNKNOWN', 'INVALID', 'RISKY', 'UNVERIFIED', name='verification_status', native_enum=False, length=40), server_default='UNVERIFIED', nullable=False),
    sa.Column('verification_provider', sa.String(length=80), nullable=True),
    sa.Column('verification_confidence', sa.Float(), nullable=True),
    sa.Column('verification_meta', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_primary', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], name=op.f('fk_contact_emails_contact_id_contacts'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_contact_emails')),
    sa.UniqueConstraint('contact_id', 'email', name='uq_contact_emails_contact_email')
    )
    op.create_index(op.f('ix_contact_emails_contact_id'), 'contact_emails', ['contact_id'], unique=False)
    op.create_index(op.f('ix_contact_emails_email'), 'contact_emails', ['email'], unique=False)
    op.create_index(op.f('ix_contact_emails_verification_status'), 'contact_emails', ['verification_status'], unique=False)
    op.create_table('contact_profiles',
    sa.Column('contact_id', sa.BigInteger(), nullable=False),
    sa.Column('platform', sa.String(length=40), nullable=False),
    sa.Column('url', sa.String(length=1000), nullable=False),
    sa.Column('source_type', sa.Enum('COMPANY_WEBSITE', 'SEARCH_PROVIDER', 'DIRECTORY', 'BUSINESS_DATA_PROVIDER', 'EMAIL_PROVIDER', 'VERIFICATION_PROVIDER', 'USER_IMPORT', 'USER_ENTRY', 'LLM', 'DEMO', name='source_type', native_enum=False, length=40), nullable=False),
    sa.Column('provider', sa.String(length=80), nullable=True),
    sa.Column('source_url', sa.String(length=1000), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('retrieved_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], name=op.f('fk_contact_profiles_contact_id_contacts'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_contact_profiles')),
    sa.UniqueConstraint('contact_id', 'url', name='uq_contact_profiles_contact_url')
    )
    op.create_index(op.f('ix_contact_profiles_contact_id'), 'contact_profiles', ['contact_id'], unique=False)
    op.create_index(op.f('ix_contact_profiles_url'), 'contact_profiles', ['url'], unique=False)
    op.create_table('crawl_jobs',
    sa.Column('job_id', sa.BigInteger(), nullable=True),
    sa.Column('company_id', sa.BigInteger(), nullable=False),
    sa.Column('domain', sa.String(length=255), nullable=False),
    sa.Column('status', sa.Enum('QUEUED', 'RUNNING', 'PAUSED', 'COMPLETED', 'FAILED', 'CANCELLED', name='job_status', native_enum=False, length=40), nullable=False),
    sa.Column('robots_allowed', sa.Boolean(), nullable=True),
    sa.Column('pages_fetched', sa.Integer(), nullable=False),
    sa.Column('pages_skipped', sa.Integer(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_crawl_jobs_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], name=op.f('fk_crawl_jobs_job_id_jobs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_crawl_jobs'))
    )
    op.create_index(op.f('ix_crawl_jobs_company_id'), 'crawl_jobs', ['company_id'], unique=False)
    op.create_index(op.f('ix_crawl_jobs_job_id'), 'crawl_jobs', ['job_id'], unique=False)
    op.create_table('enrichment_jobs',
    sa.Column('job_id', sa.BigInteger(), nullable=True),
    sa.Column('company_id', sa.BigInteger(), nullable=True),
    sa.Column('contact_id', sa.BigInteger(), nullable=True),
    sa.Column('step', sa.String(length=60), nullable=False),
    sa.Column('provider', sa.String(length=80), nullable=True),
    sa.Column('status', sa.Enum('QUEUED', 'RUNNING', 'PAUSED', 'COMPLETED', 'FAILED', 'CANCELLED', name='job_status', native_enum=False, length=40), nullable=False),
    sa.Column('result', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_enrichment_jobs_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], name=op.f('fk_enrichment_jobs_contact_id_contacts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], name=op.f('fk_enrichment_jobs_job_id_jobs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_enrichment_jobs'))
    )
    op.create_index(op.f('ix_enrichment_jobs_company_id'), 'enrichment_jobs', ['company_id'], unique=False)
    op.create_index(op.f('ix_enrichment_jobs_contact_id'), 'enrichment_jobs', ['contact_id'], unique=False)
    op.create_index(op.f('ix_enrichment_jobs_job_id'), 'enrichment_jobs', ['job_id'], unique=False)
    op.create_table('finance_invoices',
    sa.Column('company_id', sa.BigInteger(), nullable=False),
    sa.Column('contact_id', sa.BigInteger(), nullable=True),
    sa.Column('finance_invoice_id', sa.BigInteger(), nullable=False),
    sa.Column('invoice_number', sa.String(length=40), nullable=False),
    sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_finance_invoices_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], name=op.f('fk_finance_invoices_contact_id_contacts'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_finance_invoices'))
    )
    op.create_index(op.f('ix_finance_invoices_company_id'), 'finance_invoices', ['company_id'], unique=False)
    op.create_table('lead_scores',
    sa.Column('contact_id', sa.BigInteger(), nullable=False),
    sa.Column('score', sa.Integer(), nullable=False),
    sa.Column('priority', sa.Enum('HIGH', 'MEDIUM', 'LOW', name='priority', native_enum=False, length=40), nullable=False),
    sa.Column('breakdown', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('settings_version', sa.Integer(), nullable=False),
    sa.Column('is_current', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('computed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], name=op.f('fk_lead_scores_contact_id_contacts'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_lead_scores'))
    )
    op.create_index(op.f('ix_lead_scores_contact_id'), 'lead_scores', ['contact_id'], unique=False)
    op.create_index(op.f('ix_lead_scores_is_current'), 'lead_scores', ['is_current'], unique=False)
    op.create_index(op.f('ix_lead_scores_priority'), 'lead_scores', ['priority'], unique=False)
    op.create_index(op.f('ix_lead_scores_score'), 'lead_scores', ['score'], unique=False)
    op.create_table('notes',
    sa.Column('contact_id', sa.BigInteger(), nullable=True),
    sa.Column('company_id', sa.BigInteger(), nullable=True),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_notes_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], name=op.f('fk_notes_contact_id_contacts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_notes_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notes'))
    )
    op.create_index(op.f('ix_notes_company_id'), 'notes', ['company_id'], unique=False)
    op.create_index(op.f('ix_notes_contact_id'), 'notes', ['contact_id'], unique=False)
    op.create_table('outreach_drafts',
    sa.Column('contact_id', sa.BigInteger(), nullable=False),
    sa.Column('campaign_id', sa.BigInteger(), nullable=True),
    sa.Column('channel', sa.String(length=20), nullable=False),
    sa.Column('tone', sa.String(length=20), nullable=False),
    sa.Column('subject', sa.String(length=300), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('evidence', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('generated_by', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='DRAFT', nullable=False),
    sa.Column('created_by_id', sa.BigInteger(), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], name=op.f('fk_outreach_drafts_campaign_id_campaigns'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], name=op.f('fk_outreach_drafts_contact_id_contacts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=op.f('fk_outreach_drafts_created_by_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_outreach_drafts'))
    )
    op.create_index(op.f('ix_outreach_drafts_contact_id'), 'outreach_drafts', ['contact_id'], unique=False)
    op.create_table('provider_usage',
    sa.Column('provider', sa.String(length=80), nullable=False),
    sa.Column('kind', sa.String(length=40), nullable=False),
    sa.Column('operation', sa.String(length=80), nullable=False),
    sa.Column('success', sa.Boolean(), nullable=False),
    sa.Column('http_status', sa.Integer(), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('error_type', sa.String(length=80), nullable=True),
    sa.Column('cost_estimate', sa.Float(), nullable=True),
    sa.Column('job_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], name=op.f('fk_provider_usage_job_id_jobs'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_provider_usage'))
    )
    op.create_index(op.f('ix_provider_usage_created_at'), 'provider_usage', ['created_at'], unique=False)
    op.create_index(op.f('ix_provider_usage_provider'), 'provider_usage', ['provider'], unique=False)
    op.create_table('crawl_pages',
    sa.Column('crawl_job_id', sa.BigInteger(), nullable=True),
    sa.Column('company_id', sa.BigInteger(), nullable=False),
    sa.Column('url', sa.String(length=1000), nullable=False),
    sa.Column('canonical_url', sa.String(length=1000), nullable=True),
    sa.Column('page_type', sa.String(length=40), nullable=True),
    sa.Column('status_code', sa.Integer(), nullable=True),
    sa.Column('content_type', sa.String(length=120), nullable=True),
    sa.Column('content_hash', sa.String(length=64), nullable=True),
    sa.Column('title', sa.String(length=500), nullable=True),
    sa.Column('text', sa.Text(), nullable=True),
    sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_crawl_pages_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['crawl_job_id'], ['crawl_jobs.id'], name=op.f('fk_crawl_pages_crawl_job_id_crawl_jobs'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_crawl_pages'))
    )
    op.create_index(op.f('ix_crawl_pages_company_id'), 'crawl_pages', ['company_id'], unique=False)
    op.create_index(op.f('ix_crawl_pages_content_hash'), 'crawl_pages', ['content_hash'], unique=False)
    op.create_index(op.f('ix_crawl_pages_crawl_job_id'), 'crawl_pages', ['crawl_job_id'], unique=False)
    op.create_table('company_signals',
    sa.Column('company_id', sa.BigInteger(), nullable=False),
    sa.Column('signal_type', sa.String(length=60), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('evidence_text', sa.Text(), nullable=True),
    sa.Column('source_url', sa.String(length=1000), nullable=True),
    sa.Column('source_date', sa.DateTime(timezone=True), nullable=True),
    sa.Column('provenance', sa.Enum('DISCOVERED', 'INFERRED', 'ENRICHED', 'VERIFIED', 'USER_PROVIDED', name='provenance', native_enum=False, length=40), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('crawl_page_id', sa.BigInteger(), nullable=True),
    sa.Column('discovered_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_company_signals_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['crawl_page_id'], ['crawl_pages.id'], name=op.f('fk_company_signals_crawl_page_id_crawl_pages'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_company_signals'))
    )
    op.create_index(op.f('ix_company_signals_company_id'), 'company_signals', ['company_id'], unique=False)
    op.create_index(op.f('ix_company_signals_signal_type'), 'company_signals', ['signal_type'], unique=False)
    op.create_table('company_sources',
    sa.Column('company_id', sa.BigInteger(), nullable=False),
    sa.Column('field_name', sa.String(length=60), nullable=False),
    sa.Column('value', sa.Text(), nullable=True),
    sa.Column('provenance', sa.Enum('DISCOVERED', 'INFERRED', 'ENRICHED', 'VERIFIED', 'USER_PROVIDED', name='provenance', native_enum=False, length=40), nullable=False),
    sa.Column('source_type', sa.Enum('COMPANY_WEBSITE', 'SEARCH_PROVIDER', 'DIRECTORY', 'BUSINESS_DATA_PROVIDER', 'EMAIL_PROVIDER', 'VERIFICATION_PROVIDER', 'USER_IMPORT', 'USER_ENTRY', 'LLM', 'DEMO', name='source_type', native_enum=False, length=40), nullable=False),
    sa.Column('provider', sa.String(length=80), nullable=True),
    sa.Column('source_url', sa.String(length=1000), nullable=True),
    sa.Column('evidence_text', sa.Text(), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('crawl_page_id', sa.BigInteger(), nullable=True),
    sa.Column('retrieved_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_company_sources_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['crawl_page_id'], ['crawl_pages.id'], name=op.f('fk_company_sources_crawl_page_id_crawl_pages'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_company_sources'))
    )
    op.create_index(op.f('ix_company_sources_company_id'), 'company_sources', ['company_id'], unique=False)
    op.create_table('contact_sources',
    sa.Column('contact_id', sa.BigInteger(), nullable=False),
    sa.Column('field_name', sa.String(length=60), nullable=False),
    sa.Column('value', sa.Text(), nullable=True),
    sa.Column('provenance', sa.Enum('DISCOVERED', 'INFERRED', 'ENRICHED', 'VERIFIED', 'USER_PROVIDED', name='provenance', native_enum=False, length=40), nullable=False),
    sa.Column('source_type', sa.Enum('COMPANY_WEBSITE', 'SEARCH_PROVIDER', 'DIRECTORY', 'BUSINESS_DATA_PROVIDER', 'EMAIL_PROVIDER', 'VERIFICATION_PROVIDER', 'USER_IMPORT', 'USER_ENTRY', 'LLM', 'DEMO', name='source_type', native_enum=False, length=40), nullable=False),
    sa.Column('provider', sa.String(length=80), nullable=True),
    sa.Column('source_url', sa.String(length=1000), nullable=True),
    sa.Column('evidence_text', sa.Text(), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('crawl_page_id', sa.BigInteger(), nullable=True),
    sa.Column('retrieved_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], name=op.f('fk_contact_sources_contact_id_contacts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['crawl_page_id'], ['crawl_pages.id'], name=op.f('fk_contact_sources_crawl_page_id_crawl_pages'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_contact_sources'))
    )
    op.create_index(op.f('ix_contact_sources_contact_id'), 'contact_sources', ['contact_id'], unique=False)
    op.create_table('company_locations',
    sa.Column('company_id', sa.BigInteger(), nullable=False),
    sa.Column('address', sa.Text(), nullable=True),
    sa.Column('city', sa.String(length=120), nullable=True),
    sa.Column('state', sa.String(length=120), nullable=True),
    sa.Column('postcode', sa.String(length=20), nullable=True),
    sa.Column('country', sa.String(length=80), server_default='Malaysia', nullable=False),
    sa.Column('is_primary', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('source_id', sa.BigInteger(), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_company_locations_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_id'], ['company_sources.id'], name=op.f('fk_company_locations_source_id_company_sources'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_company_locations'))
    )
    op.create_index(op.f('ix_company_locations_city'), 'company_locations', ['city'], unique=False)
    op.create_index(op.f('ix_company_locations_company_id'), 'company_locations', ['company_id'], unique=False)
    op.create_index(op.f('ix_company_locations_state'), 'company_locations', ['state'], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_company_locations_state'), table_name='company_locations')
    op.drop_index(op.f('ix_company_locations_company_id'), table_name='company_locations')
    op.drop_index(op.f('ix_company_locations_city'), table_name='company_locations')
    op.drop_table('company_locations')
    op.drop_index(op.f('ix_contact_sources_contact_id'), table_name='contact_sources')
    op.drop_table('contact_sources')
    op.drop_index(op.f('ix_company_sources_company_id'), table_name='company_sources')
    op.drop_table('company_sources')
    op.drop_index(op.f('ix_company_signals_signal_type'), table_name='company_signals')
    op.drop_index(op.f('ix_company_signals_company_id'), table_name='company_signals')
    op.drop_table('company_signals')
    op.drop_index(op.f('ix_crawl_pages_crawl_job_id'), table_name='crawl_pages')
    op.drop_index(op.f('ix_crawl_pages_content_hash'), table_name='crawl_pages')
    op.drop_index(op.f('ix_crawl_pages_company_id'), table_name='crawl_pages')
    op.drop_table('crawl_pages')
    op.drop_index(op.f('ix_provider_usage_provider'), table_name='provider_usage')
    op.drop_index(op.f('ix_provider_usage_created_at'), table_name='provider_usage')
    op.drop_table('provider_usage')
    op.drop_index(op.f('ix_outreach_drafts_contact_id'), table_name='outreach_drafts')
    op.drop_table('outreach_drafts')
    op.drop_index(op.f('ix_notes_contact_id'), table_name='notes')
    op.drop_index(op.f('ix_notes_company_id'), table_name='notes')
    op.drop_table('notes')
    op.drop_index(op.f('ix_lead_scores_score'), table_name='lead_scores')
    op.drop_index(op.f('ix_lead_scores_priority'), table_name='lead_scores')
    op.drop_index(op.f('ix_lead_scores_is_current'), table_name='lead_scores')
    op.drop_index(op.f('ix_lead_scores_contact_id'), table_name='lead_scores')
    op.drop_table('lead_scores')
    op.drop_index(op.f('ix_finance_invoices_company_id'), table_name='finance_invoices')
    op.drop_table('finance_invoices')
    op.drop_index(op.f('ix_enrichment_jobs_job_id'), table_name='enrichment_jobs')
    op.drop_index(op.f('ix_enrichment_jobs_contact_id'), table_name='enrichment_jobs')
    op.drop_index(op.f('ix_enrichment_jobs_company_id'), table_name='enrichment_jobs')
    op.drop_table('enrichment_jobs')
    op.drop_index(op.f('ix_crawl_jobs_job_id'), table_name='crawl_jobs')
    op.drop_index(op.f('ix_crawl_jobs_company_id'), table_name='crawl_jobs')
    op.drop_table('crawl_jobs')
    op.drop_index(op.f('ix_contact_profiles_url'), table_name='contact_profiles')
    op.drop_index(op.f('ix_contact_profiles_contact_id'), table_name='contact_profiles')
    op.drop_table('contact_profiles')
    op.drop_index(op.f('ix_contact_emails_verification_status'), table_name='contact_emails')
    op.drop_index(op.f('ix_contact_emails_email'), table_name='contact_emails')
    op.drop_index(op.f('ix_contact_emails_contact_id'), table_name='contact_emails')
    op.drop_table('contact_emails')
    op.drop_index(op.f('ix_contact_confidence_scores_is_current'), table_name='contact_confidence_scores')
    op.drop_index(op.f('ix_contact_confidence_scores_contact_id'), table_name='contact_confidence_scores')
    op.drop_table('contact_confidence_scores')
    op.drop_index(op.f('ix_campaign_contacts_contact_id'), table_name='campaign_contacts')
    op.drop_table('campaign_contacts')
    op.drop_index(op.f('ix_activities_created_at'), table_name='activities')
    op.drop_index(op.f('ix_activities_contact_id'), table_name='activities')
    op.drop_index(op.f('ix_activities_company_id'), table_name='activities')
    op.drop_index(op.f('ix_activities_activity_type'), table_name='activities')
    op.drop_table('activities')
    op.drop_index(op.f('ix_training_opportunities_program_id'), table_name='training_opportunities')
    op.drop_index(op.f('ix_training_opportunities_is_current'), table_name='training_opportunities')
    op.drop_index(op.f('ix_training_opportunities_company_id'), table_name='training_opportunities')
    op.drop_table('training_opportunities')
    op.drop_index(op.f('ix_jobs_status'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_job_type'), table_name='jobs')
    op.drop_table('jobs')
    op.drop_index(op.f('ix_contacts_status'), table_name='contacts')
    op.drop_index('ix_contacts_normalized_name_trgm', table_name='contacts', postgresql_using='gin', postgresql_ops={'normalized_name': 'gin_trgm_ops'})
    op.drop_index(op.f('ix_contacts_normalized_name'), table_name='contacts')
    op.drop_index(op.f('ix_contacts_is_demo'), table_name='contacts')
    op.drop_index(op.f('ix_contacts_department'), table_name='contacts')
    op.drop_index(op.f('ix_contacts_deleted_at'), table_name='contacts')
    op.drop_index(op.f('ix_contacts_company_id'), table_name='contacts')
    op.drop_table('contacts')
    op.drop_table('suppression_list')
    op.drop_table('settings')
    op.drop_index(op.f('ix_prospect_searches_deleted_at'), table_name='prospect_searches')
    op.drop_table('prospect_searches')
    op.drop_index(op.f('ix_notifications_user_id'), table_name='notifications')
    op.drop_index(op.f('ix_notifications_created_at'), table_name='notifications')
    op.drop_table('notifications')
    op.drop_index(op.f('ix_duplicate_candidates_status'), table_name='duplicate_candidates')
    op.drop_index(op.f('ix_duplicate_candidates_right_id'), table_name='duplicate_candidates')
    op.drop_index(op.f('ix_duplicate_candidates_left_id'), table_name='duplicate_candidates')
    op.drop_table('duplicate_candidates')
    op.drop_index('uq_companies_domain_live', table_name='companies', postgresql_where='domain IS NOT NULL AND deleted_at IS NULL')
    op.drop_index('ix_companies_normalized_name_trgm', table_name='companies', postgresql_using='gin', postgresql_ops={'normalized_name': 'gin_trgm_ops'})
    op.drop_index(op.f('ix_companies_normalized_name'), table_name='companies')
    op.drop_index(op.f('ix_companies_is_demo'), table_name='companies')
    op.drop_index(op.f('ix_companies_industry'), table_name='companies')
    op.drop_index(op.f('ix_companies_domain'), table_name='companies')
    op.drop_index(op.f('ix_companies_deleted_at'), table_name='companies')
    op.drop_table('companies')
    op.drop_index(op.f('ix_campaigns_deleted_at'), table_name='campaigns')
    op.drop_table('campaigns')
    op.drop_index(op.f('ix_audit_logs_user_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_created_at'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_action'), table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_table('users')
    op.drop_table('training_programs')
    op.drop_index(op.f('ix_provider_cache_provider'), table_name='provider_cache')
    op.drop_index(op.f('ix_provider_cache_expires_at'), table_name='provider_cache')
    op.drop_table('provider_cache')
    # ### end Alembic commands ###
