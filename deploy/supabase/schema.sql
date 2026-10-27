BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 0001_baseline

CREATE TABLE audit_log (
    user_id VARCHAR(32), 
    actor VARCHAR(10) NOT NULL, 
    action VARCHAR(60) NOT NULL, 
    subject_id VARCHAR(32), 
    detail JSON NOT NULL, 
    at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_audit_log PRIMARY KEY (id)
);

CREATE INDEX ix_audit_user_at ON audit_log (user_id, at);

CREATE TABLE dnc_registry (
    phone_hmac VARCHAR(64) NOT NULL, 
    phone TEXT NOT NULL, 
    reason VARCHAR(40) NOT NULL, 
    number_phone VARCHAR(20), 
    at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_dnc_registry PRIMARY KEY (id), 
    CONSTRAINT uq_dnc_registry_phone_hmac UNIQUE (phone_hmac)
);

CREATE TABLE friday_numbers (
    phone VARCHAR(20) NOT NULL, 
    provider VARCHAR(20) NOT NULL, 
    city VARCHAR(80), 
    circle VARCHAR(8), 
    status VARCHAR(10) NOT NULL, 
    warmup_day INTEGER NOT NULL, 
    limits JSON NOT NULL, 
    health JSON NOT NULL, 
    cooldowns INTEGER NOT NULL, 
    cooling_until TIMESTAMP WITH TIME ZONE, 
    retired_at TIMESTAMP WITH TIME ZONE, 
    forward_until TIMESTAMP WITH TIME ZONE, 
    verified_caller_name VARCHAR(80), 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_friday_numbers PRIMARY KEY (id), 
    CONSTRAINT uq_friday_numbers_phone UNIQUE (phone)
);

CREATE INDEX ix_friday_numbers_circle ON friday_numbers (circle);

CREATE INDEX ix_friday_numbers_status ON friday_numbers (status);

CREATE TABLE idempotency_keys (
    key VARCHAR(200) NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_idempotency_keys PRIMARY KEY (key)
);

CREATE INDEX ix_idempotency_keys_expires_at ON idempotency_keys (expires_at);

CREATE TABLE jobs (
    kind VARCHAR(40) NOT NULL, 
    payload TEXT NOT NULL, 
    priority INTEGER NOT NULL, 
    due_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    dedupe_key VARCHAR(200), 
    partition_key VARCHAR(64), 
    attempts INTEGER NOT NULL, 
    max_attempts INTEGER NOT NULL, 
    status VARCHAR(10) NOT NULL, 
    claimed_by VARCHAR(80), 
    lease_until TIMESTAMP WITH TIME ZONE, 
    last_error VARCHAR(300), 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_jobs PRIMARY KEY (id)
);

CREATE INDEX ix_jobs_claim ON jobs (status, priority, due_at);

CREATE UNIQUE INDEX uq_jobs_live_dedupe ON jobs (dedupe_key) WHERE status IN ('queued','claimed');

CREATE TABLE number_assignments (
    business_phone_hmac VARCHAR(64) NOT NULL, 
    business_phone TEXT NOT NULL, 
    number_phone VARCHAR(20) NOT NULL, 
    assigned_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    last_used_at TIMESTAMP WITH TIME ZONE, 
    previous_number VARCHAR(20), 
    CONSTRAINT pk_number_assignments PRIMARY KEY (business_phone_hmac)
);

CREATE INDEX ix_number_assignments_number_phone ON number_assignments (number_phone);

CREATE TABLE number_outcomes (
    number_phone VARCHAR(20) NOT NULL, 
    outcome VARCHAR(16) NOT NULL, 
    business_phone_hmac VARCHAR(64), 
    duration_s FLOAT NOT NULL, 
    archived BOOLEAN NOT NULL, 
    at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_number_outcomes PRIMARY KEY (id)
);

CREATE INDEX ix_number_outcomes_number_at ON number_outcomes (number_phone, at);

CREATE TABLE pending_deletions (
    kind VARCHAR(16) NOT NULL, 
    url TEXT NOT NULL, 
    attempts INTEGER NOT NULL, 
    last_error VARCHAR(200), 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_pending_deletions PRIMARY KEY (id)
);

CREATE TABLE suppressions (
    phone_hmac VARCHAR(64) NOT NULL, 
    scope VARCHAR(16) NOT NULL, 
    reason VARCHAR(40), 
    at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_suppressions PRIMARY KEY (id), 
    CONSTRAINT uq_suppressions_phone_hmac UNIQUE (phone_hmac, scope)
);

CREATE INDEX ix_suppressions_phone_hmac ON suppressions (phone_hmac);

CREATE TABLE users (
    phone TEXT NOT NULL, 
    phone_hmac VARCHAR(64) NOT NULL, 
    status VARCHAR(20) NOT NULL, 
    onboarding_step VARCHAR(20) NOT NULL, 
    pin_hash VARCHAR(255), 
    pin_failed_attempts INTEGER NOT NULL, 
    invited_by_user_id VARCHAR(32), 
    invites_remaining INTEGER NOT NULL, 
    rate_limited BOOLEAN NOT NULL, 
    last_inbound_at TIMESTAMP WITH TIME ZONE, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_users PRIMARY KEY (id), 
    CONSTRAINT uq_users_phone_hmac UNIQUE (phone_hmac)
);

CREATE TABLE account_identifiers (
    user_id VARCHAR(32) NOT NULL, 
    company VARCHAR(120), 
    label VARCHAR(120) NOT NULL, 
    value_encrypted TEXT NOT NULL, 
    last4 VARCHAR(4), 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_account_identifiers PRIMARY KEY (id), 
    CONSTRAINT fk_account_identifiers_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_account_identifiers_user_id ON account_identifiers (user_id);

CREATE TABLE autonomy_settings (
    user_id VARCHAR(32) NOT NULL, 
    category VARCHAR(20) NOT NULL, 
    level INTEGER NOT NULL, 
    enabled BOOLEAN NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_autonomy_settings PRIMARY KEY (user_id, category), 
    CONSTRAINT fk_autonomy_settings_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE businesses (
    name VARCHAR(200) NOT NULL, 
    phone VARCHAR(20) NOT NULL, 
    whatsapp_phone VARCHAR(20), 
    category VARCHAR(60), 
    city VARCHAR(120), 
    address TEXT, 
    lat FLOAT, 
    lng FLOAT, 
    hours JSON, 
    best_call_times JSON NOT NULL, 
    is_customer_care BOOLEAN NOT NULL, 
    ivr_notes JSON NOT NULL, 
    verification VARCHAR(12), 
    notes TEXT, 
    language_hint VARCHAR(12), 
    directory_provider VARCHAR(30), 
    directory_place_id VARCHAR(255), 
    rating FLOAT, 
    review_count INTEGER, 
    created_by_user_id VARCHAR(32), 
    last_called_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_businesses PRIMARY KEY (id), 
    CONSTRAINT fk_businesses_created_by_user_id_users FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_businesses_directory_place_id ON businesses (directory_place_id);

CREATE INDEX ix_businesses_phone ON businesses (phone);

CREATE TABLE cost_entries (
    user_id VARCHAR(32) NOT NULL, 
    task_id VARCHAR(32), 
    call_id VARCHAR(32), 
    kind VARCHAR(16) NOT NULL, 
    amount_inr FLOAT NOT NULL, 
    at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_cost_entries PRIMARY KEY (id), 
    CONSTRAINT fk_cost_entries_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_cost_entries_user_id ON cost_entries (user_id);

CREATE INDEX ix_cost_user_at ON cost_entries (user_id, at);

CREATE TABLE invites (
    code VARCHAR(16) NOT NULL, 
    created_by_user_id VARCHAR(32), 
    redeemed_by_user_id VARCHAR(32), 
    redeemed_at TIMESTAMP WITH TIME ZONE, 
    expires_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_invites PRIMARY KEY (code), 
    CONSTRAINT fk_invites_created_by_user_id_users FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT fk_invites_redeemed_by_user_id_users FOREIGN KEY(redeemed_by_user_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_invites_created_by_user_id ON invites (created_by_user_id);

CREATE TABLE people (
    owner_user_id VARCHAR(32) NOT NULL, 
    name TEXT NOT NULL, 
    relation VARCHAR(40), 
    aliases JSON NOT NULL, 
    phone TEXT, 
    phone_hmac VARCHAR(64), 
    language VARCHAR(12), 
    notes TEXT, 
    contact_consent VARCHAR(16) NOT NULL, 
    consent_at TIMESTAMP WITH TIME ZONE, 
    checkin_consent VARCHAR(16) NOT NULL, 
    linked_user_id VARCHAR(32), 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_people PRIMARY KEY (id), 
    CONSTRAINT fk_people_linked_user_id_users FOREIGN KEY(linked_user_id) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT fk_people_owner_user_id_users FOREIGN KEY(owner_user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_people_owner_user_id ON people (owner_user_id);

CREATE INDEX ix_people_phone_hmac ON people (phone_hmac);

CREATE TABLE pin_locks (
    user_id VARCHAR(32) NOT NULL, 
    strikes INTEGER NOT NULL, 
    locked_until TIMESTAMP WITH TIME ZONE, 
    support_required BOOLEAN NOT NULL, 
    reason VARCHAR(40), 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_pin_locks PRIMARY KEY (user_id), 
    CONSTRAINT fk_pin_locks_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE profiles (
    user_id VARCHAR(32) NOT NULL, 
    name TEXT, 
    city VARCHAR(120), 
    language VARCHAR(12) NOT NULL, 
    tone VARCHAR(12) NOT NULL, 
    morning_briefing BOOLEAN NOT NULL, 
    briefing_hour_ist INTEGER NOT NULL, 
    preferred_channel VARCHAR(12) NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_profiles PRIMARY KEY (user_id), 
    CONSTRAINT fk_profiles_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE consents (
    user_id VARCHAR(32) NOT NULL, 
    kind VARCHAR(32) NOT NULL, 
    granted BOOLEAN NOT NULL, 
    person_id VARCHAR(32), 
    policy_version VARCHAR(20) NOT NULL, 
    evidence_text TEXT, 
    phone_hmac VARCHAR(64), 
    message_id VARCHAR(32), 
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_consents PRIMARY KEY (id), 
    CONSTRAINT fk_consents_person_id_people FOREIGN KEY(person_id) REFERENCES people (id) ON DELETE CASCADE, 
    CONSTRAINT fk_consents_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_consents_phone_hmac ON consents (phone_hmac);

CREATE INDEX ix_consents_user_id ON consents (user_id);

CREATE TABLE facts (
    user_id VARCHAR(32) NOT NULL, 
    kind VARCHAR(16) NOT NULL, 
    key VARCHAR(80) NOT NULL, 
    value TEXT NOT NULL, 
    due_on DATE, 
    recurrence VARCHAR(10) NOT NULL, 
    business_id VARCHAR(32), 
    person_id VARCHAR(32), 
    confidence FLOAT NOT NULL, 
    source_message_id VARCHAR(32), 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_facts PRIMARY KEY (id), 
    CONSTRAINT fk_facts_business_id_businesses FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE SET NULL, 
    CONSTRAINT fk_facts_person_id_people FOREIGN KEY(person_id) REFERENCES people (id) ON DELETE CASCADE, 
    CONSTRAINT fk_facts_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_facts_due_on ON facts (due_on);

CREATE INDEX ix_facts_user_id ON facts (user_id);

CREATE TABLE messages (
    user_id VARCHAR(32), 
    person_id VARCHAR(32), 
    business_id VARCHAR(32), 
    direction VARCHAR(8) NOT NULL, 
    channel VARCHAR(12) NOT NULL, 
    kind VARCHAR(16) NOT NULL, 
    phone TEXT NOT NULL, 
    phone_hmac VARCHAR(64), 
    text TEXT, 
    buttons JSON NOT NULL, 
    button_id VARCHAR(256), 
    template TEXT, 
    media_url TEXT, 
    location TEXT, 
    provider_message_id VARCHAR(128), 
    task_id VARCHAR(32), 
    nudge_id VARCHAR(32), 
    question_id VARCHAR(32), 
    ok BOOLEAN NOT NULL, 
    error TEXT, 
    at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_messages PRIMARY KEY (id), 
    CONSTRAINT fk_messages_business_id_businesses FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE SET NULL, 
    CONSTRAINT fk_messages_person_id_people FOREIGN KEY(person_id) REFERENCES people (id) ON DELETE SET NULL, 
    CONSTRAINT fk_messages_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_messages_phone_dir_at ON messages (phone_hmac, direction, at);

CREATE INDEX ix_messages_phone_hmac ON messages (phone_hmac);

CREATE INDEX ix_messages_provider_message_id ON messages (provider_message_id);

CREATE INDEX ix_messages_task_id ON messages (task_id);

CREATE INDEX ix_messages_user_at ON messages (user_id, at);

CREATE TABLE places (
    owner_user_id VARCHAR(32) NOT NULL, 
    label VARCHAR(80) NOT NULL, 
    aliases JSON NOT NULL, 
    address_text TEXT, 
    formatted_address TEXT, 
    city VARCHAR(120), 
    lat TEXT, 
    lng TEXT, 
    source VARCHAR(16) NOT NULL, 
    person_id VARCHAR(32), 
    ephemeral BOOLEAN NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_places PRIMARY KEY (id), 
    CONSTRAINT fk_places_owner_user_id_users FOREIGN KEY(owner_user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT fk_places_person_id_people FOREIGN KEY(person_id) REFERENCES people (id) ON DELETE SET NULL
);

CREATE INDEX ix_places_owner_user_id ON places (owner_user_id);

CREATE INDEX ix_places_person_id ON places (person_id);

CREATE TABLE vendor_interactions (
    user_id VARCHAR(32) NOT NULL, 
    business_id VARCHAR(32) NOT NULL, 
    kind VARCHAR(16) NOT NULL, 
    task_id VARCHAR(32), 
    call_id VARCHAR(32), 
    amount_inr INTEGER, 
    rating INTEGER, 
    outcome VARCHAR(200), 
    note TEXT, 
    at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_vendor_interactions PRIMARY KEY (id), 
    CONSTRAINT fk_vendor_interactions_business_id_businesses FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE CASCADE, 
    CONSTRAINT fk_vendor_interactions_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_vendor_interactions_user_id ON vendor_interactions (user_id);

CREATE INDEX ix_vendor_user_business ON vendor_interactions (user_id, business_id);

CREATE TABLE tasks (
    requester_user_id VARCHAR(32) NOT NULL, 
    beneficiary_person_id VARCHAR(32), 
    place_id VARCHAR(32), 
    parent_task_id VARCHAR(32), 
    type VARCHAR(16) NOT NULL, 
    status VARCHAR(20) NOT NULL, 
    spec TEXT NOT NULL, 
    target TEXT, 
    recurrence JSON, 
    next_run_at TIMESTAMP WITH TIME ZONE, 
    attempts INTEGER NOT NULL, 
    max_attempts INTEGER NOT NULL, 
    next_attempt_at TIMESTAMP WITH TIME ZONE, 
    last_outcome VARCHAR(20), 
    result TEXT, 
    candidate JSON, 
    shortlist JSON NOT NULL, 
    approved_terms TEXT, 
    delegation JSON, 
    cost_inr_est FLOAT NOT NULL, 
    source_message_id VARCHAR(32), 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_tasks PRIMARY KEY (id), 
    CONSTRAINT fk_tasks_beneficiary_person_id_people FOREIGN KEY(beneficiary_person_id) REFERENCES people (id) ON DELETE SET NULL, 
    CONSTRAINT fk_tasks_parent_task_id_tasks FOREIGN KEY(parent_task_id) REFERENCES tasks (id) ON DELETE CASCADE, 
    CONSTRAINT fk_tasks_place_id_places FOREIGN KEY(place_id) REFERENCES places (id) ON DELETE SET NULL, 
    CONSTRAINT fk_tasks_requester_user_id_users FOREIGN KEY(requester_user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_tasks_next_run_at ON tasks (next_run_at);

CREATE INDEX ix_tasks_parent_task_id ON tasks (parent_task_id);

CREATE INDEX ix_tasks_requester_status ON tasks (requester_user_id, status);

CREATE INDEX ix_tasks_status_next ON tasks (status, next_attempt_at);

CREATE TABLE call_memory (
    call_id VARCHAR(32), 
    task_id VARCHAR(32) NOT NULL, 
    user_id VARCHAR(32) NOT NULL, 
    business_id VARCHAR(32), 
    business_phone TEXT NOT NULL, 
    business_phone_hmac VARCHAR(64) NOT NULL, 
    friday_number VARCHAR(20), 
    direction VARCHAR(10) NOT NULL, 
    outcome VARCHAR(24), 
    at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_call_memory PRIMARY KEY (id), 
    CONSTRAINT fk_call_memory_business_id_businesses FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE SET NULL, 
    CONSTRAINT fk_call_memory_task_id_tasks FOREIGN KEY(task_id) REFERENCES tasks (id) ON DELETE CASCADE, 
    CONSTRAINT fk_call_memory_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_call_memory_call_id UNIQUE (call_id)
);

CREATE INDEX ix_call_memory_business_phone_hmac ON call_memory (business_phone_hmac);

CREATE INDEX ix_call_memory_friday_number ON call_memory (friday_number);

CREATE INDEX ix_call_memory_phone_at ON call_memory (business_phone_hmac, at);

CREATE INDEX ix_call_memory_task_id ON call_memory (task_id);

CREATE INDEX ix_call_memory_user_id ON call_memory (user_id);

CREATE TABLE call_questions (
    task_id VARCHAR(32) NOT NULL, 
    call_id VARCHAR(32), 
    purpose VARCHAR(20) NOT NULL, 
    text TEXT NOT NULL, 
    options JSON NOT NULL, 
    timeout_s INTEGER NOT NULL, 
    asked_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    answer_text TEXT, 
    answer_option_index INTEGER, 
    answer_approves BOOLEAN, 
    answered_at TIMESTAMP WITH TIME ZONE, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_call_questions PRIMARY KEY (id), 
    CONSTRAINT fk_call_questions_task_id_tasks FOREIGN KEY(task_id) REFERENCES tasks (id) ON DELETE CASCADE
);

CREATE INDEX ix_call_questions_task_id ON call_questions (task_id);

CREATE TABLE calls (
    task_id VARCHAR(32) NOT NULL, 
    provider VARCHAR(20) NOT NULL, 
    provider_call_id VARCHAR(128), 
    direction VARCHAR(10) NOT NULL, 
    to_phone TEXT NOT NULL, 
    business_id VARCHAR(32), 
    dial_status VARCHAR(16) NOT NULL, 
    outcome VARCHAR(20) NOT NULL, 
    collected TEXT NOT NULL, 
    languages_heard JSON NOT NULL, 
    care JSON, 
    hold_seconds INTEGER NOT NULL, 
    cost_inr_est FLOAT NOT NULL, 
    mode VARCHAR(16) NOT NULL, 
    recording_url TEXT, 
    started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    answered_at TIMESTAMP WITH TIME ZONE, 
    ended_at TIMESTAMP WITH TIME ZONE, 
    error TEXT, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_calls PRIMARY KEY (id), 
    CONSTRAINT fk_calls_business_id_businesses FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE SET NULL, 
    CONSTRAINT fk_calls_task_id_tasks FOREIGN KEY(task_id) REFERENCES tasks (id) ON DELETE CASCADE
);

CREATE INDEX ix_calls_provider_call_id ON calls (provider_call_id);

CREATE INDEX ix_calls_task_id ON calls (task_id);

CREATE TABLE hotel_bookings (
    task_id VARCHAR(32), 
    user_id VARCHAR(32) NOT NULL, 
    guest_person_id VARCHAR(32), 
    provider VARCHAR(20) NOT NULL, 
    mode VARCHAR(16) NOT NULL, 
    status VARCHAR(16) NOT NULL, 
    property JSON NOT NULL, 
    business_id VARCHAR(32), 
    room_type VARCHAR(120), 
    check_in DATE NOT NULL, 
    check_out DATE NOT NULL, 
    guests INTEGER NOT NULL, 
    total_inr INTEGER, 
    confirmation_ref VARCHAR(80), 
    booking_link TEXT, 
    hold_until TIMESTAMP WITH TIME ZONE, 
    guest_name TEXT, 
    notes TEXT, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_hotel_bookings PRIMARY KEY (id), 
    CONSTRAINT fk_hotel_bookings_business_id_businesses FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE SET NULL, 
    CONSTRAINT fk_hotel_bookings_guest_person_id_people FOREIGN KEY(guest_person_id) REFERENCES people (id) ON DELETE SET NULL, 
    CONSTRAINT fk_hotel_bookings_task_id_tasks FOREIGN KEY(task_id) REFERENCES tasks (id) ON DELETE SET NULL, 
    CONSTRAINT fk_hotel_bookings_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_hotel_bookings_check_in ON hotel_bookings (check_in);

CREATE INDEX ix_hotel_bookings_task_id ON hotel_bookings (task_id);

CREATE INDEX ix_hotel_bookings_user_id ON hotel_bookings (user_id);

CREATE TABLE inbound_contacts (
    kind VARCHAR(12) NOT NULL, 
    channel VARCHAR(12) NOT NULL, 
    from_phone TEXT NOT NULL, 
    from_phone_hmac VARCHAR(64) NOT NULL, 
    friday_number VARCHAR(20), 
    provider_ref VARCHAR(128), 
    call_id VARCHAR(128), 
    status VARCHAR(12) NOT NULL, 
    business_id VARCHAR(32), 
    task_id VARCHAR(32), 
    user_id VARCHAR(32), 
    candidate_task_ids JSON NOT NULL, 
    note TEXT, 
    handled BOOLEAN NOT NULL, 
    at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_inbound_contacts PRIMARY KEY (id), 
    CONSTRAINT fk_inbound_contacts_business_id_businesses FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE SET NULL, 
    CONSTRAINT fk_inbound_contacts_task_id_tasks FOREIGN KEY(task_id) REFERENCES tasks (id) ON DELETE SET NULL, 
    CONSTRAINT fk_inbound_contacts_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_inbound_contacts_phone_at ON inbound_contacts (from_phone_hmac, at);

CREATE INDEX ix_inbound_contacts_task_id ON inbound_contacts (task_id);

CREATE INDEX ix_inbound_contacts_user_id ON inbound_contacts (user_id);

CREATE TABLE nudges (
    user_id VARCHAR(32) NOT NULL, 
    kind VARCHAR(20) NOT NULL, 
    category VARCHAR(20) NOT NULL, 
    urgency VARCHAR(10) NOT NULL, 
    status VARCHAR(12) NOT NULL, 
    dedupe_key VARCHAR(200) NOT NULL, 
    text TEXT, 
    buttons JSON NOT NULL, 
    proposed_task JSON, 
    task_id VARCHAR(32), 
    fact_id VARCHAR(32), 
    person_id VARCHAR(32), 
    recipient_person_id VARCHAR(32), 
    scheduled_for TIMESTAMP WITH TIME ZONE, 
    sent_at TIMESTAMP WITH TIME ZONE, 
    responded_at TIMESTAMP WITH TIME ZONE, 
    reason TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_nudges PRIMARY KEY (id), 
    CONSTRAINT fk_nudges_fact_id_facts FOREIGN KEY(fact_id) REFERENCES facts (id) ON DELETE SET NULL, 
    CONSTRAINT fk_nudges_person_id_people FOREIGN KEY(person_id) REFERENCES people (id) ON DELETE SET NULL, 
    CONSTRAINT fk_nudges_recipient_person_id_people FOREIGN KEY(recipient_person_id) REFERENCES people (id) ON DELETE SET NULL, 
    CONSTRAINT fk_nudges_task_id_tasks FOREIGN KEY(task_id) REFERENCES tasks (id) ON DELETE SET NULL, 
    CONSTRAINT fk_nudges_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_nudges_user_id UNIQUE (user_id, dedupe_key)
);

CREATE INDEX ix_nudges_scheduled_for ON nudges (scheduled_for);

CREATE INDEX ix_nudges_user_id ON nudges (user_id);

CREATE INDEX ix_nudges_user_sent ON nudges (user_id, sent_at);

CREATE TABLE call_turns (
    id SERIAL NOT NULL, 
    call_id VARCHAR(32) NOT NULL, 
    seq INTEGER NOT NULL, 
    speaker VARCHAR(8) NOT NULL, 
    text TEXT NOT NULL, 
    language VARCHAR(12), 
    confidence FLOAT, 
    at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_call_turns PRIMARY KEY (id), 
    CONSTRAINT fk_call_turns_call_id_calls FOREIGN KEY(call_id) REFERENCES calls (id) ON DELETE CASCADE, 
    CONSTRAINT uq_call_turns_call_id UNIQUE (call_id, seq)
);

CREATE INDEX ix_call_turns_call_id ON call_turns (call_id);

CREATE TABLE nudge_feedback (
    nudge_id VARCHAR(32) NOT NULL, 
    user_id VARCHAR(32) NOT NULL, 
    type VARCHAR(12) NOT NULL, 
    at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_nudge_feedback PRIMARY KEY (id), 
    CONSTRAINT fk_nudge_feedback_nudge_id_nudges FOREIGN KEY(nudge_id) REFERENCES nudges (id) ON DELETE CASCADE, 
    CONSTRAINT fk_nudge_feedback_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_nudge_feedback_nudge_id ON nudge_feedback (nudge_id);

CREATE INDEX ix_nudge_feedback_user_id ON nudge_feedback (user_id);

CREATE TABLE quotes (
    task_id VARCHAR(32) NOT NULL, 
    call_id VARCHAR(32), 
    business_id VARCHAR(32), 
    business_name VARCHAR(200) NOT NULL, 
    amount_inr INTEGER, 
    original_amount_inr INTEGER, 
    price_text TEXT NOT NULL, 
    inclusions JSON NOT NULL, 
    exclusions JSON NOT NULL, 
    validity VARCHAR(200), 
    available_slots JSON NOT NULL, 
    notes TEXT, 
    within_budget BOOLEAN, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_quotes PRIMARY KEY (id), 
    CONSTRAINT fk_quotes_business_id_businesses FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE SET NULL, 
    CONSTRAINT fk_quotes_call_id_calls FOREIGN KEY(call_id) REFERENCES calls (id) ON DELETE SET NULL, 
    CONSTRAINT fk_quotes_task_id_tasks FOREIGN KEY(task_id) REFERENCES tasks (id) ON DELETE CASCADE
);

CREATE INDEX ix_quotes_task_id ON quotes (task_id);

INSERT INTO alembic_version (version_num) VALUES ('0001_baseline') RETURNING alembic_version.version_num;

-- Running upgrade 0001_baseline -> 0002_partitions

CREATE TABLE messages_new (
    user_id VARCHAR(32), 
    person_id VARCHAR(32), 
    business_id VARCHAR(32), 
    direction VARCHAR(8) NOT NULL, 
    channel VARCHAR(12) NOT NULL, 
    kind VARCHAR(16) NOT NULL, 
    phone TEXT NOT NULL, 
    phone_hmac VARCHAR(64), 
    text TEXT, 
    buttons JSON NOT NULL, 
    button_id VARCHAR(256), 
    template TEXT, 
    media_url TEXT, 
    location TEXT, 
    provider_message_id VARCHAR(128), 
    task_id VARCHAR(32), 
    nudge_id VARCHAR(32), 
    question_id VARCHAR(32), 
    ok BOOLEAN NOT NULL, 
    error TEXT, 
    at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    PRIMARY KEY (at, id)
) PARTITION BY RANGE (at);

CREATE TABLE messages_new_pdefault PARTITION OF messages_new DEFAULT;

CREATE TABLE IF NOT EXISTS messages_new_p2026_10 PARTITION OF messages_new FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');

CREATE TABLE IF NOT EXISTS messages_new_p2026_11 PARTITION OF messages_new FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');

CREATE TABLE IF NOT EXISTS messages_new_p2026_12 PARTITION OF messages_new FOR VALUES FROM ('2026-12-01') TO ('2027-01-01');

CREATE TABLE IF NOT EXISTS messages_new_p2027_01 PARTITION OF messages_new FOR VALUES FROM ('2027-01-01') TO ('2027-02-01');

CREATE TABLE IF NOT EXISTS messages_new_p2027_02 PARTITION OF messages_new FOR VALUES FROM ('2027-02-01') TO ('2027-03-01');

CREATE TABLE IF NOT EXISTS messages_new_p2027_03 PARTITION OF messages_new FOR VALUES FROM ('2027-03-01') TO ('2027-04-01');

CREATE TABLE IF NOT EXISTS messages_new_p2027_04 PARTITION OF messages_new FOR VALUES FROM ('2027-04-01') TO ('2027-05-01');

CREATE TABLE IF NOT EXISTS messages_new_p2027_05 PARTITION OF messages_new FOR VALUES FROM ('2027-05-01') TO ('2027-06-01');

CREATE TABLE IF NOT EXISTS messages_new_p2027_06 PARTITION OF messages_new FOR VALUES FROM ('2027-06-01') TO ('2027-07-01');

CREATE TABLE IF NOT EXISTS messages_new_p2027_07 PARTITION OF messages_new FOR VALUES FROM ('2027-07-01') TO ('2027-08-01');

CREATE TABLE IF NOT EXISTS messages_new_p2027_08 PARTITION OF messages_new FOR VALUES FROM ('2027-08-01') TO ('2027-09-01');

CREATE TABLE IF NOT EXISTS messages_new_p2027_09 PARTITION OF messages_new FOR VALUES FROM ('2027-09-01') TO ('2027-10-01');

INSERT INTO messages_new (user_id, person_id, business_id, direction, channel, kind, phone, phone_hmac, text, buttons, button_id, template, media_url, location, provider_message_id, task_id, nudge_id, question_id, ok, error, at, id) SELECT user_id, person_id, business_id, direction, channel, kind, phone, phone_hmac, text, buttons, button_id, template, media_url, location, provider_message_id, task_id, nudge_id, question_id, ok, error, at, id FROM messages;

DROP TABLE messages;

ALTER TABLE messages_new RENAME TO messages;

ALTER TABLE messages RENAME CONSTRAINT messages_new_pkey TO pk_messages;

CREATE INDEX ix_messages_phone_dir_at ON messages (phone_hmac, direction, at);

CREATE INDEX ix_messages_phone_hmac ON messages (phone_hmac);

CREATE INDEX ix_messages_provider_message_id ON messages (provider_message_id);

CREATE INDEX ix_messages_task_id ON messages (task_id);

CREATE INDEX ix_messages_user_at ON messages (user_id, at);

CREATE TABLE call_turns_new (
    id SERIAL NOT NULL, 
    call_id VARCHAR(32) NOT NULL, 
    seq INTEGER NOT NULL, 
    speaker VARCHAR(8) NOT NULL, 
    text TEXT NOT NULL, 
    language VARCHAR(12), 
    confidence FLOAT, 
    at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id, at)
) PARTITION BY RANGE (at);

CREATE TABLE call_turns_new_pdefault PARTITION OF call_turns_new DEFAULT;

CREATE TABLE IF NOT EXISTS call_turns_new_p2026_10 PARTITION OF call_turns_new FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');

CREATE TABLE IF NOT EXISTS call_turns_new_p2026_11 PARTITION OF call_turns_new FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');

CREATE TABLE IF NOT EXISTS call_turns_new_p2026_12 PARTITION OF call_turns_new FOR VALUES FROM ('2026-12-01') TO ('2027-01-01');

CREATE TABLE IF NOT EXISTS call_turns_new_p2027_01 PARTITION OF call_turns_new FOR VALUES FROM ('2027-01-01') TO ('2027-02-01');

CREATE TABLE IF NOT EXISTS call_turns_new_p2027_02 PARTITION OF call_turns_new FOR VALUES FROM ('2027-02-01') TO ('2027-03-01');

CREATE TABLE IF NOT EXISTS call_turns_new_p2027_03 PARTITION OF call_turns_new FOR VALUES FROM ('2027-03-01') TO ('2027-04-01');

CREATE TABLE IF NOT EXISTS call_turns_new_p2027_04 PARTITION OF call_turns_new FOR VALUES FROM ('2027-04-01') TO ('2027-05-01');

CREATE TABLE IF NOT EXISTS call_turns_new_p2027_05 PARTITION OF call_turns_new FOR VALUES FROM ('2027-05-01') TO ('2027-06-01');

CREATE TABLE IF NOT EXISTS call_turns_new_p2027_06 PARTITION OF call_turns_new FOR VALUES FROM ('2027-06-01') TO ('2027-07-01');

CREATE TABLE IF NOT EXISTS call_turns_new_p2027_07 PARTITION OF call_turns_new FOR VALUES FROM ('2027-07-01') TO ('2027-08-01');

CREATE TABLE IF NOT EXISTS call_turns_new_p2027_08 PARTITION OF call_turns_new FOR VALUES FROM ('2027-08-01') TO ('2027-09-01');

CREATE TABLE IF NOT EXISTS call_turns_new_p2027_09 PARTITION OF call_turns_new FOR VALUES FROM ('2027-09-01') TO ('2027-10-01');

INSERT INTO call_turns_new (id, call_id, seq, speaker, text, language, confidence, at) SELECT id, call_id, seq, speaker, text, language, confidence, at FROM call_turns;

DROP TABLE call_turns;

ALTER TABLE call_turns_new RENAME TO call_turns;

ALTER TABLE call_turns RENAME CONSTRAINT call_turns_new_pkey TO pk_call_turns;

CREATE INDEX ix_call_turns_call_id ON call_turns (call_id);

CREATE INDEX ix_call_turns_call_id_seq ON call_turns (call_id, seq);

CREATE TABLE audit_log_new (
    user_id VARCHAR(32), 
    actor VARCHAR(10) NOT NULL, 
    action VARCHAR(60) NOT NULL, 
    subject_id VARCHAR(32), 
    detail JSON NOT NULL, 
    at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    PRIMARY KEY (at, id)
) PARTITION BY RANGE (at);

CREATE TABLE audit_log_new_pdefault PARTITION OF audit_log_new DEFAULT;

CREATE TABLE IF NOT EXISTS audit_log_new_p2026_10 PARTITION OF audit_log_new FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');

CREATE TABLE IF NOT EXISTS audit_log_new_p2026_11 PARTITION OF audit_log_new FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');

CREATE TABLE IF NOT EXISTS audit_log_new_p2026_12 PARTITION OF audit_log_new FOR VALUES FROM ('2026-12-01') TO ('2027-01-01');

CREATE TABLE IF NOT EXISTS audit_log_new_p2027_01 PARTITION OF audit_log_new FOR VALUES FROM ('2027-01-01') TO ('2027-02-01');

CREATE TABLE IF NOT EXISTS audit_log_new_p2027_02 PARTITION OF audit_log_new FOR VALUES FROM ('2027-02-01') TO ('2027-03-01');

CREATE TABLE IF NOT EXISTS audit_log_new_p2027_03 PARTITION OF audit_log_new FOR VALUES FROM ('2027-03-01') TO ('2027-04-01');

CREATE TABLE IF NOT EXISTS audit_log_new_p2027_04 PARTITION OF audit_log_new FOR VALUES FROM ('2027-04-01') TO ('2027-05-01');

CREATE TABLE IF NOT EXISTS audit_log_new_p2027_05 PARTITION OF audit_log_new FOR VALUES FROM ('2027-05-01') TO ('2027-06-01');

CREATE TABLE IF NOT EXISTS audit_log_new_p2027_06 PARTITION OF audit_log_new FOR VALUES FROM ('2027-06-01') TO ('2027-07-01');

CREATE TABLE IF NOT EXISTS audit_log_new_p2027_07 PARTITION OF audit_log_new FOR VALUES FROM ('2027-07-01') TO ('2027-08-01');

CREATE TABLE IF NOT EXISTS audit_log_new_p2027_08 PARTITION OF audit_log_new FOR VALUES FROM ('2027-08-01') TO ('2027-09-01');

CREATE TABLE IF NOT EXISTS audit_log_new_p2027_09 PARTITION OF audit_log_new FOR VALUES FROM ('2027-09-01') TO ('2027-10-01');

INSERT INTO audit_log_new (user_id, actor, action, subject_id, detail, at, id) SELECT user_id, actor, action, subject_id, detail, at, id FROM audit_log;

DROP TABLE audit_log;

ALTER TABLE audit_log_new RENAME TO audit_log;

ALTER TABLE audit_log RENAME CONSTRAINT audit_log_new_pkey TO pk_audit_log;

CREATE INDEX ix_audit_user_at ON audit_log (user_id, at);

CREATE TABLE cost_entries_new (
    user_id VARCHAR(32) NOT NULL, 
    task_id VARCHAR(32), 
    call_id VARCHAR(32), 
    kind VARCHAR(16) NOT NULL, 
    amount_inr FLOAT NOT NULL, 
    at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    PRIMARY KEY (at, id)
) PARTITION BY RANGE (at);

CREATE TABLE cost_entries_new_pdefault PARTITION OF cost_entries_new DEFAULT;

CREATE TABLE IF NOT EXISTS cost_entries_new_p2026_10 PARTITION OF cost_entries_new FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');

CREATE TABLE IF NOT EXISTS cost_entries_new_p2026_11 PARTITION OF cost_entries_new FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');

CREATE TABLE IF NOT EXISTS cost_entries_new_p2026_12 PARTITION OF cost_entries_new FOR VALUES FROM ('2026-12-01') TO ('2027-01-01');

CREATE TABLE IF NOT EXISTS cost_entries_new_p2027_01 PARTITION OF cost_entries_new FOR VALUES FROM ('2027-01-01') TO ('2027-02-01');

CREATE TABLE IF NOT EXISTS cost_entries_new_p2027_02 PARTITION OF cost_entries_new FOR VALUES FROM ('2027-02-01') TO ('2027-03-01');

CREATE TABLE IF NOT EXISTS cost_entries_new_p2027_03 PARTITION OF cost_entries_new FOR VALUES FROM ('2027-03-01') TO ('2027-04-01');

CREATE TABLE IF NOT EXISTS cost_entries_new_p2027_04 PARTITION OF cost_entries_new FOR VALUES FROM ('2027-04-01') TO ('2027-05-01');

CREATE TABLE IF NOT EXISTS cost_entries_new_p2027_05 PARTITION OF cost_entries_new FOR VALUES FROM ('2027-05-01') TO ('2027-06-01');

CREATE TABLE IF NOT EXISTS cost_entries_new_p2027_06 PARTITION OF cost_entries_new FOR VALUES FROM ('2027-06-01') TO ('2027-07-01');

CREATE TABLE IF NOT EXISTS cost_entries_new_p2027_07 PARTITION OF cost_entries_new FOR VALUES FROM ('2027-07-01') TO ('2027-08-01');

CREATE TABLE IF NOT EXISTS cost_entries_new_p2027_08 PARTITION OF cost_entries_new FOR VALUES FROM ('2027-08-01') TO ('2027-09-01');

CREATE TABLE IF NOT EXISTS cost_entries_new_p2027_09 PARTITION OF cost_entries_new FOR VALUES FROM ('2027-09-01') TO ('2027-10-01');

INSERT INTO cost_entries_new (user_id, task_id, call_id, kind, amount_inr, at, id) SELECT user_id, task_id, call_id, kind, amount_inr, at, id FROM cost_entries;

DROP TABLE cost_entries;

ALTER TABLE cost_entries_new RENAME TO cost_entries;

ALTER TABLE cost_entries RENAME CONSTRAINT cost_entries_new_pkey TO pk_cost_entries;

CREATE INDEX ix_cost_entries_user_id ON cost_entries (user_id);

CREATE INDEX ix_cost_user_at ON cost_entries (user_id, at);

UPDATE alembic_version SET version_num='0002_partitions' WHERE alembic_version.version_num = '0001_baseline';

-- Running upgrade 0002_partitions -> 0003_task_role

ALTER TABLE tasks ADD COLUMN role VARCHAR(24);

ALTER TABLE calls ADD COLUMN from_number VARCHAR(20);

UPDATE alembic_version SET version_num='0003_task_role' WHERE alembic_version.version_num = '0002_partitions';

-- Running upgrade 0003_task_role -> 0004_quality_calls

CREATE TABLE quality_calls (
    call_id VARCHAR(64) NOT NULL, 
    user_id VARCHAR(32) NOT NULL, 
    stored_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    meta JSON NOT NULL, 
    transcript TEXT NOT NULL, 
    labels JSON NOT NULL, 
    note TEXT, 
    rating INTEGER, 
    rated_at TIMESTAMP WITH TIME ZONE, 
    labelled_at TIMESTAMP WITH TIME ZONE, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_quality_calls PRIMARY KEY (id), 
    CONSTRAINT fk_quality_calls_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_quality_calls_call_id UNIQUE (call_id)
);

CREATE INDEX ix_quality_calls_expires_at ON quality_calls (expires_at);

CREATE INDEX ix_quality_calls_user_id ON quality_calls (user_id);

UPDATE alembic_version SET version_num='0004_quality_calls' WHERE alembic_version.version_num = '0003_task_role';

-- Running upgrade 0004_quality_calls -> 0005_quote_conversations

CREATE TABLE quote_conversations (
    user_id VARCHAR(32) NOT NULL, 
    state VARCHAR(20) NOT NULL, 
    active BOOLEAN NOT NULL, 
    version INTEGER NOT NULL, 
    counted_at TIMESTAMP WITH TIME ZONE, 
    data TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_quote_conversations PRIMARY KEY (id), 
    CONSTRAINT fk_quote_conversations_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_quote_conversations_user_id ON quote_conversations (user_id);

CREATE INDEX ix_quote_conversations_state ON quote_conversations (state);

CREATE INDEX ix_quote_conversations_active ON quote_conversations (active);

CREATE INDEX ix_quote_conversations_counted_at ON quote_conversations (counted_at);

UPDATE alembic_version SET version_num='0005_quote_conversations' WHERE alembic_version.version_num = '0004_quality_calls';

-- Running upgrade 0005_quote_conversations -> 0006_google_connector

CREATE TABLE google_connections (
    user_id VARCHAR(32) NOT NULL, 
    google_sub_hmac VARCHAR(64) NOT NULL, 
    email TEXT, 
    scopes JSON NOT NULL, 
    refresh_token TEXT NOT NULL, 
    access_token TEXT, 
    access_expires_at TIMESTAMP WITH TIME ZONE, 
    status VARCHAR(20) NOT NULL, 
    last_used_at TIMESTAMP WITH TIME ZONE, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_google_connections PRIMARY KEY (id), 
    CONSTRAINT fk_google_connections_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_google_connections_user_id UNIQUE (user_id)
);

CREATE INDEX ix_google_connections_google_sub_hmac ON google_connections (google_sub_hmac);

CREATE TABLE google_oauth_states (
    id VARCHAR(64) NOT NULL, 
    user_id VARCHAR(32) NOT NULL, 
    code_verifier TEXT, 
    scopes JSON NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    used_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_google_oauth_states PRIMARY KEY (id), 
    CONSTRAINT fk_google_oauth_states_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_google_oauth_states_user_id ON google_oauth_states (user_id);

CREATE INDEX ix_google_oauth_states_expires_at ON google_oauth_states (expires_at);

UPDATE alembic_version SET version_num='0006_google_connector' WHERE alembic_version.version_num = '0005_quote_conversations';

-- Running upgrade 0006_google_connector -> 0007_consumer_calls

CREATE TABLE call_dnc (
    number_hash VARCHAR(64) NOT NULL, 
    reason VARCHAR(24) NOT NULL, 
    source VARCHAR(60) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_call_dnc PRIMARY KEY (id), 
    CONSTRAINT uq_call_dnc_number_hash UNIQUE (number_hash)
);

CREATE TABLE call_attempts (
    user_id VARCHAR(32) NOT NULL, 
    request_id VARCHAR(32) NOT NULL, 
    number_hash VARCHAR(64) NOT NULL, 
    started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    duration_s FLOAT NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_call_attempts PRIMARY KEY (id), 
    CONSTRAINT fk_call_attempts_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_call_attempts_number_hash ON call_attempts (number_hash);

CREATE INDEX ix_call_attempts_started_at ON call_attempts (started_at);

CREATE INDEX ix_call_attempts_user_id ON call_attempts (user_id);

CREATE TABLE call_requests (
    user_id VARCHAR(32) NOT NULL, 
    callee_kind VARCHAR(20) NOT NULL, 
    purpose TEXT NOT NULL, 
    purpose_kind VARCHAR(20) NOT NULL, 
    callee_ref TEXT, 
    callee_name TEXT, 
    callee_number TEXT, 
    callee_number_hash VARCHAR(64), 
    number_confirmed BOOLEAN NOT NULL, 
    company TEXT, 
    language VARCHAR(12) NOT NULL, 
    scheduled_for TIMESTAMP WITH TIME ZONE, 
    parent_id VARCHAR(32), 
    callback_of VARCHAR(32), 
    group_members TEXT NOT NULL, 
    raw_text TEXT, 
    source_message_id VARCHAR(80), 
    idempotency_key VARCHAR(64) NOT NULL, 
    status VARCHAR(20) NOT NULL, 
    attempts INTEGER NOT NULL, 
    next_attempt_at TIMESTAMP WITH TIME ZONE, 
    task_id VARCHAR(32), 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_call_requests PRIMARY KEY (id), 
    CONSTRAINT fk_call_requests_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_call_requests_idempotency_key UNIQUE (idempotency_key)
);

CREATE INDEX ix_call_requests_callee_number_hash ON call_requests (callee_number_hash);

CREATE INDEX ix_call_requests_next_attempt_at ON call_requests (next_attempt_at);

CREATE INDEX ix_call_requests_parent_id ON call_requests (parent_id);

CREATE INDEX ix_call_requests_status ON call_requests (status);

CREATE INDEX ix_call_requests_user_id ON call_requests (user_id);

CREATE TABLE call_strikes (
    user_id VARCHAR(32) NOT NULL, 
    reason VARCHAR(40) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_call_strikes PRIMARY KEY (id), 
    CONSTRAINT fk_call_strikes_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_call_strikes_user_id ON call_strikes (user_id);

CREATE TABLE consumer_contacts (
    user_id VARCHAR(32) NOT NULL, 
    name TEXT NOT NULL, 
    nicknames TEXT NOT NULL, 
    relationship VARCHAR(40), 
    number TEXT NOT NULL, 
    number_hash VARCHAR(64) NOT NULL, 
    confirmed_at TIMESTAMP WITH TIME ZONE, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_consumer_contacts PRIMARY KEY (id), 
    CONSTRAINT fk_consumer_contacts_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_consumer_contacts_user_id UNIQUE (user_id, number_hash)
);

CREATE INDEX ix_consumer_contacts_number_hash ON consumer_contacts (number_hash);

CREATE INDEX ix_consumer_contacts_user_id ON consumer_contacts (user_id);

CREATE TABLE call_briefs (
    request_id VARCHAR(32) NOT NULL, 
    user_id VARCHAR(32) NOT NULL, 
    payload TEXT NOT NULL, 
    content_hash VARCHAR(64) NOT NULL, 
    approved BOOLEAN NOT NULL, 
    approval_hash VARCHAR(64), 
    approved_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_call_briefs PRIMARY KEY (id), 
    CONSTRAINT fk_call_briefs_request_id_call_requests FOREIGN KEY(request_id) REFERENCES call_requests (id) ON DELETE CASCADE, 
    CONSTRAINT fk_call_briefs_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_call_briefs_request_id UNIQUE (request_id)
);

CREATE INDEX ix_call_briefs_user_id ON call_briefs (user_id);

CREATE TABLE call_outcomes (
    request_id VARCHAR(32) NOT NULL, 
    user_id VARCHAR(32) NOT NULL, 
    attempt INTEGER NOT NULL, 
    status VARCHAR(20) NOT NULL, 
    payload TEXT NOT NULL, 
    number_hash VARCHAR(64), 
    duration_s FLOAT NOT NULL, 
    started_at TIMESTAMP WITH TIME ZONE, 
    recording_ref TEXT, 
    transcript_ref TEXT, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_call_outcomes PRIMARY KEY (id), 
    CONSTRAINT fk_call_outcomes_request_id_call_requests FOREIGN KEY(request_id) REFERENCES call_requests (id) ON DELETE CASCADE, 
    CONSTRAINT fk_call_outcomes_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_call_outcomes_request_id ON call_outcomes (request_id);

CREATE INDEX ix_call_outcomes_started_at ON call_outcomes (started_at);

CREATE INDEX ix_call_outcomes_user_id ON call_outcomes (user_id);

UPDATE alembic_version SET version_num='0007_consumer_calls' WHERE alembic_version.version_num = '0006_google_connector';

-- Running upgrade 0007_consumer_calls -> 0008_savings_engine

CREATE TABLE wallet_cards (
    user_id VARCHAR(32) NOT NULL, 
    card_key_hmac VARCHAR(64) NOT NULL, 
    bank TEXT NOT NULL, 
    card_name TEXT NOT NULL, 
    data TEXT NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_wallet_cards PRIMARY KEY (id), 
    CONSTRAINT fk_wallet_cards_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_wallet_cards_user_id UNIQUE (user_id, card_key_hmac)
);

CREATE INDEX ix_wallet_cards_user_id ON wallet_cards (user_id);

CREATE TABLE card_rules (
    card_key VARCHAR(160) NOT NULL, 
    scope VARCHAR(200) NOT NULL, 
    bank VARCHAR(80) NOT NULL, 
    card_name VARCHAR(80) NOT NULL, 
    category VARCHAR(40) NOT NULL, 
    reward_type VARCHAR(12) NOT NULL, 
    rate_bp INTEGER NOT NULL, 
    monthly_cap_paise INTEGER, 
    per_txn_cap_paise INTEGER, 
    min_spend_paise INTEGER NOT NULL, 
    exclusions JSON NOT NULL, 
    merchants JSON NOT NULL, 
    source_url TEXT NOT NULL, 
    checked_on DATE, 
    verified_by VARCHAR(100), 
    valid_from DATE, 
    valid_to DATE, 
    notes TEXT NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_card_rules PRIMARY KEY (id), 
    CONSTRAINT uq_card_rules_card_key UNIQUE (card_key, scope)
);

CREATE INDEX ix_card_rules_card_key ON card_rules (card_key);

CREATE TABLE bills (
    user_id VARCHAR(32) NOT NULL, 
    status VARCHAR(12) NOT NULL, 
    confirmed BOOLEAN NOT NULL, 
    due_on DATE NOT NULL, 
    data TEXT NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_bills PRIMARY KEY (id), 
    CONSTRAINT fk_bills_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_bills_user_id ON bills (user_id);

CREATE INDEX ix_bills_status ON bills (status);

CREATE INDEX ix_bills_due_on ON bills (due_on);

CREATE TABLE savings_ledger (
    user_id VARCHAR(32) NOT NULL, 
    month VARCHAR(7) NOT NULL, 
    fingerprint_hmac VARCHAR(64) NOT NULL, 
    outcome VARCHAR(20) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    data TEXT NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_savings_ledger PRIMARY KEY (id), 
    CONSTRAINT fk_savings_ledger_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_savings_ledger_user_id UNIQUE (user_id, fingerprint_hmac)
);

CREATE INDEX ix_savings_ledger_user_id ON savings_ledger (user_id);

CREATE INDEX ix_savings_ledger_month ON savings_ledger (month);

CREATE INDEX ix_savings_ledger_outcome ON savings_ledger (outcome);

UPDATE alembic_version SET version_num='0008_savings_engine' WHERE alembic_version.version_num = '0007_consumer_calls';

-- Running upgrade 0008_savings_engine -> 0009_life_state

CREATE TABLE life_events (
    user_id VARCHAR(32) NOT NULL, 
    title TEXT NOT NULL, 
    start_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    end_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    kind VARCHAR(16) NOT NULL, 
    source VARCHAR(16) NOT NULL, 
    source_ref VARCHAR(128), 
    location TEXT, 
    protected BOOLEAN NOT NULL, 
    status VARCHAR(12) NOT NULL, 
    note TEXT, 
    repeat JSON, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_life_events PRIMARY KEY (id), 
    CONSTRAINT fk_life_events_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_life_events_source_ref UNIQUE (user_id, source, source_ref)
);

CREATE INDEX ix_life_events_user_start ON life_events (user_id, start_at);

CREATE TABLE life_commitments (
    user_id VARCHAR(32) NOT NULL, 
    text TEXT NOT NULL, 
    due_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    source VARCHAR(16) NOT NULL, 
    status VARCHAR(12) NOT NULL, 
    repeat JSON, 
    person TEXT, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_life_commitments PRIMARY KEY (id), 
    CONSTRAINT fk_life_commitments_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_life_commitments_user_due ON life_commitments (user_id, due_at);

CREATE TABLE mute_topics (
    user_id VARCHAR(32) NOT NULL, 
    topic VARCHAR(64) NOT NULL, 
    muted BOOLEAN NOT NULL, 
    channel VARCHAR(12) NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_mute_topics PRIMARY KEY (id), 
    CONSTRAINT fk_mute_topics_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_mute_topics_user_topic UNIQUE (user_id, topic)
);

CREATE INDEX ix_mute_topics_user_id ON mute_topics (user_id);

CREATE TABLE life_followups (
    user_id VARCHAR(32) NOT NULL, 
    key VARCHAR(160) NOT NULL, 
    topic VARCHAR(32) NOT NULL, 
    event_id VARCHAR(32), 
    status VARCHAR(12) NOT NULL, 
    text TEXT, 
    due_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    sent_at TIMESTAMP WITH TIME ZONE, 
    responded_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_life_followups PRIMARY KEY (id), 
    CONSTRAINT fk_life_followups_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_life_followups_user_key UNIQUE (user_id, key)
);

CREATE INDEX ix_life_followups_user_sent ON life_followups (user_id, sent_at);

UPDATE alembic_version SET version_num='0009_life_state' WHERE alembic_version.version_num = '0008_savings_engine';

-- Running upgrade 0009_life_state -> 0010_chatbot

CREATE TABLE chatbot_sessions (
    phone_hash VARCHAR(64) NOT NULL, 
    user_id VARCHAR(32), 
    step VARCHAR(24) NOT NULL, 
    lang VARCHAR(8) NOT NULL, 
    step_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    pending_kind VARCHAR(24), 
    pending TEXT, 
    last_hash VARCHAR(32), 
    refused_at TIMESTAMP WITH TIME ZONE, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_chatbot_sessions PRIMARY KEY (id), 
    CONSTRAINT fk_chatbot_sessions_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_chatbot_sessions_phone_hash UNIQUE (phone_hash)
);

CREATE INDEX ix_chatbot_sessions_user_id ON chatbot_sessions (user_id);

CREATE TABLE chatbot_waitlist (
    phone_hash VARCHAR(64) NOT NULL, 
    first_seen_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    hits INTEGER NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_chatbot_waitlist PRIMARY KEY (id), 
    CONSTRAINT uq_chatbot_waitlist_phone_hash UNIQUE (phone_hash)
);

CREATE TABLE chatbot_inbox (
    kind VARCHAR(12) NOT NULL, 
    user_id VARCHAR(32), 
    text TEXT NOT NULL, 
    lang VARCHAR(8) NOT NULL, 
    status VARCHAR(12) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_chatbot_inbox PRIMARY KEY (id), 
    CONSTRAINT fk_chatbot_inbox_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_chatbot_inbox_user_id ON chatbot_inbox (user_id);

CREATE INDEX ix_chatbot_inbox_kind_created ON chatbot_inbox (kind, created_at);

UPDATE alembic_version SET version_num='0010_chatbot' WHERE alembic_version.version_num = '0009_life_state';

-- Running upgrade 0010_chatbot -> 0011_receptionist

CREATE TABLE receptionist_configs (
    user_id VARCHAR(32) NOT NULL, 
    enabled BOOLEAN NOT NULL, 
    config TEXT NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_receptionist_configs PRIMARY KEY (id), 
    CONSTRAINT fk_receptionist_configs_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_receptionist_configs_user_id UNIQUE (user_id)
);

CREATE TABLE receptionist_messages (
    user_id VARCHAR(32), 
    caller_hash VARCHAR(64), 
    caller_number TEXT, 
    caller_name TEXT, 
    reason TEXT, 
    snippet TEXT, 
    callback_number TEXT, 
    known_contact_name TEXT, 
    urgency VARCHAR(8) NOT NULL, 
    outcome VARCHAR(16) NOT NULL, 
    status VARCHAR(12) NOT NULL, 
    notified_at TIMESTAMP WITH TIME ZONE, 
    duration_s FLOAT NOT NULL, 
    reasons JSON, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_receptionist_messages PRIMARY KEY (id), 
    CONSTRAINT fk_receptionist_messages_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_receptionist_messages_user_created ON receptionist_messages (user_id, created_at);

CREATE INDEX ix_receptionist_messages_caller_created ON receptionist_messages (caller_hash, created_at);

CREATE TABLE receptionist_blocks (
    user_id VARCHAR(32) NOT NULL, 
    number_hash VARCHAR(64) NOT NULL, 
    number TEXT NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_receptionist_blocks PRIMARY KEY (id), 
    CONSTRAINT fk_receptionist_blocks_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_receptionist_blocks UNIQUE (user_id, number_hash)
);

CREATE INDEX ix_receptionist_blocks_user_id ON receptionist_blocks (user_id);

UPDATE alembic_version SET version_num='0011_receptionist' WHERE alembic_version.version_num = '0010_chatbot';

-- Running upgrade 0011_receptionist -> 0012_receptionist_spam

CREATE TABLE receptionist_spam (
    number_hash VARCHAR(64) NOT NULL, 
    reports INTEGER NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_receptionist_spam PRIMARY KEY (id), 
    CONSTRAINT uq_receptionist_spam_number_hash UNIQUE (number_hash)
);

UPDATE alembic_version SET version_num='0012_receptionist_spam' WHERE alembic_version.version_num = '0011_receptionist';

-- Running upgrade 0012_receptionist_spam -> 0013_evidence

CREATE TABLE evidence_items (
    user_id VARCHAR(32) NOT NULL, 
    task_id VARCHAR(32) NOT NULL, 
    call_id VARCHAR(32), 
    kind VARCHAR(24) NOT NULL, 
    level VARCHAR(16) NOT NULL, 
    summary TEXT, 
    payload TEXT, 
    object_key VARCHAR(300), 
    sha256 VARCHAR(64), 
    source VARCHAR(16) NOT NULL, 
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE, 
    shareable BOOLEAN NOT NULL, 
    redaction VARCHAR(8) NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_evidence_items PRIMARY KEY (id), 
    CONSTRAINT fk_evidence_items_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT fk_evidence_items_task_id_tasks FOREIGN KEY(task_id) REFERENCES tasks (id) ON DELETE CASCADE
);

CREATE INDEX ix_evidence_items_task ON evidence_items (task_id);

CREATE INDEX ix_evidence_items_user_captured ON evidence_items (user_id, captured_at);

CREATE INDEX ix_evidence_items_expires ON evidence_items (expires_at);

CREATE TABLE done_claims (
    user_id VARCHAR(32) NOT NULL, 
    task_id VARCHAR(32) NOT NULL, 
    claim_type VARCHAR(24) NOT NULL, 
    required_level VARCHAR(16) NOT NULL, 
    status VARCHAR(10) NOT NULL, 
    evidence_ids JSON, 
    missing JSON, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_done_claims PRIMARY KEY (id), 
    CONSTRAINT fk_done_claims_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT fk_done_claims_task_id_tasks FOREIGN KEY(task_id) REFERENCES tasks (id) ON DELETE CASCADE
);

CREATE INDEX ix_done_claims_user_id ON done_claims (user_id);

CREATE UNIQUE INDEX ix_done_claims_task ON done_claims (task_id);

UPDATE alembic_version SET version_num='0013_evidence' WHERE alembic_version.version_num = '0012_receptionist_spam';

-- Running upgrade 0013_evidence -> 0014_documents

CREATE TABLE documents (
    user_id VARCHAR(32) NOT NULL, 
    doc_type VARCHAR(24) NOT NULL, 
    status VARCHAR(16) NOT NULL, 
    mime VARCHAR(32) NOT NULL, 
    size_bytes INTEGER NOT NULL, 
    sha256 VARCHAR(64), 
    language VARCHAR(10) NOT NULL, 
    confidence FLOAT NOT NULL, 
    injection_flag BOOLEAN NOT NULL, 
    pointer_kind VARCHAR(16), 
    pointer_ref TEXT, 
    expires_at TIMESTAMP WITH TIME ZONE, 
    confirmed_at TIMESTAMP WITH TIME ZONE, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_documents PRIMARY KEY (id), 
    CONSTRAINT fk_documents_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_documents_user_status ON documents (user_id, status);

CREATE INDEX ix_documents_expires ON documents (expires_at);

CREATE TABLE document_fields (
    document_id VARCHAR(32) NOT NULL, 
    user_id VARCHAR(32) NOT NULL, 
    name VARCHAR(32) NOT NULL, 
    value TEXT NOT NULL, 
    confidence FLOAT NOT NULL, 
    needs_confirm BOOLEAN NOT NULL, 
    confirmed BOOLEAN NOT NULL, 
    source VARCHAR(8) NOT NULL, 
    masked BOOLEAN NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_document_fields PRIMARY KEY (id), 
    CONSTRAINT fk_document_fields_document_id_documents FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE, 
    CONSTRAINT fk_document_fields_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_document_fields_doc ON document_fields (document_id);

CREATE INDEX ix_document_fields_user ON document_fields (user_id);

UPDATE alembic_version SET version_num='0014_documents' WHERE alembic_version.version_num = '0013_evidence';

-- Running upgrade 0014_documents -> 0015_urgent_escalation

CREATE TABLE urgent_escalation_configs (
    user_id VARCHAR(32) NOT NULL, 
    opted_in BOOLEAN NOT NULL, 
    config TEXT NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_urgent_escalation_configs PRIMARY KEY (id), 
    CONSTRAINT fk_urgent_escalation_configs_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_urgent_escalation_configs_user_id UNIQUE (user_id)
);

CREATE TABLE urgent_escalations (
    user_id VARCHAR(32) NOT NULL, 
    message_id VARCHAR(32) NOT NULL, 
    status VARCHAR(12) NOT NULL, 
    emergency BOOLEAN NOT NULL, 
    alert_ok BOOLEAN NOT NULL, 
    alert_sent_at TIMESTAMP WITH TIME ZONE, 
    wait_s INTEGER NOT NULL, 
    max_calls INTEGER NOT NULL, 
    spacing_s INTEGER NOT NULL, 
    next_action_at TIMESTAMP WITH TIME ZONE, 
    calls_made INTEGER NOT NULL, 
    in_flight BOOLEAN NOT NULL, 
    last_call_at TIMESTAMP WITH TIME ZONE, 
    last_call_result VARCHAR(16), 
    ack_at TIMESTAMP WITH TIME ZONE, 
    stop_reason VARCHAR(32), 
    finished_at TIMESTAMP WITH TIME ZONE, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_urgent_escalations PRIMARY KEY (id), 
    CONSTRAINT fk_urgent_escalations_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_urgent_escalations_user_message UNIQUE (user_id, message_id)
);

CREATE INDEX ix_urgent_escalations_user_id ON urgent_escalations (user_id);

CREATE INDEX ix_urgent_escalations_due ON urgent_escalations (status, next_action_at);

UPDATE alembic_version SET version_num='0015_urgent_escalation' WHERE alembic_version.version_num = '0014_documents';

-- Running upgrade 0015_urgent_escalation -> 0016_family_drive

CREATE TABLE drive_links (
    user_id VARCHAR(32) NOT NULL, 
    status VARCHAR(20) NOT NULL, 
    root_folder_id TEXT, 
    connected_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_drive_links PRIMARY KEY (id), 
    CONSTRAINT fk_drive_links_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_drive_links_user_id UNIQUE (user_id)
);

CREATE TABLE drive_folders (
    user_id VARCHAR(32) NOT NULL, 
    path_key VARCHAR(160) NOT NULL, 
    folder_id TEXT NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_drive_folders PRIMARY KEY (id), 
    CONSTRAINT fk_drive_folders_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_drive_folders_user_key UNIQUE (user_id, path_key)
);

CREATE INDEX ix_drive_folders_user_id ON drive_folders (user_id);

CREATE TABLE drive_shares (
    user_id VARCHAR(32) NOT NULL, 
    email TEXT NOT NULL, 
    role VARCHAR(8) NOT NULL, 
    status VARCHAR(12) NOT NULL, 
    permission_id TEXT, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    decided_at TIMESTAMP WITH TIME ZONE, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_drive_shares PRIMARY KEY (id), 
    CONSTRAINT fk_drive_shares_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_drive_shares_user_status ON drive_shares (user_id, status);

UPDATE alembic_version SET version_num='0016_family_drive' WHERE alembic_version.version_num = '0015_urgent_escalation';

-- Running upgrade 0016_family_drive -> 0017_trips

CREATE TABLE trips (
    user_id VARCHAR(32) NOT NULL, 
    title TEXT NOT NULL, 
    start_date DATE NOT NULL, 
    end_date DATE NOT NULL, 
    status VARCHAR(12) NOT NULL, 
    created_from VARCHAR(8) NOT NULL, 
    travel_minutes INTEGER, 
    pickup_address TEXT, 
    muted BOOLEAN NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_trips PRIMARY KEY (id), 
    CONSTRAINT fk_trips_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_trips_user_status ON trips (user_id, status);

CREATE TABLE trip_legs (
    user_id VARCHAR(32) NOT NULL, 
    trip_id VARCHAR(32) NOT NULL, 
    kind VARCHAR(8) NOT NULL, 
    starts_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    ends_at TIMESTAMP WITH TIME ZONE, 
    tz VARCHAR(40) NOT NULL, 
    end_tz VARCHAR(40), 
    origin TEXT, 
    dest TEXT, 
    ref TEXT, 
    data TEXT NOT NULL, 
    international BOOLEAN NOT NULL, 
    time_known BOOLEAN NOT NULL, 
    document_id VARCHAR(32), 
    pointer_kind VARCHAR(16), 
    dedupe_hmac VARCHAR(64) NOT NULL, 
    status VARCHAR(12) NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_trip_legs PRIMARY KEY (id), 
    CONSTRAINT fk_trip_legs_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT fk_trip_legs_trip_id_trips FOREIGN KEY(trip_id) REFERENCES trips (id) ON DELETE CASCADE, 
    CONSTRAINT uq_trip_legs_user_dedupe UNIQUE (user_id, dedupe_hmac)
);

CREATE INDEX ix_trip_legs_user_id ON trip_legs (user_id);

CREATE INDEX ix_trip_legs_trip ON trip_legs (trip_id);

CREATE TABLE trip_tasks (
    user_id VARCHAR(32) NOT NULL, 
    trip_id VARCHAR(32) NOT NULL, 
    leg_id VARCHAR(32), 
    kind VARCHAR(14) NOT NULL, 
    due_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    state VARCHAR(14) NOT NULL, 
    task_id VARCHAR(32), 
    evidence_ids JSON NOT NULL, 
    dedupe_key VARCHAR(120) NOT NULL, 
    locked BOOLEAN NOT NULL, 
    params TEXT NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_trip_tasks PRIMARY KEY (id), 
    CONSTRAINT fk_trip_tasks_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT fk_trip_tasks_trip_id_trips FOREIGN KEY(trip_id) REFERENCES trips (id) ON DELETE CASCADE, 
    CONSTRAINT uq_trip_tasks_user_dedupe UNIQUE (user_id, dedupe_key)
);

CREATE INDEX ix_trip_tasks_user_id ON trip_tasks (user_id);

CREATE INDEX ix_trip_tasks_trip ON trip_tasks (trip_id);

CREATE INDEX ix_trip_tasks_due ON trip_tasks (due_at);

CREATE TABLE flight_watch (
    user_id VARCHAR(32) NOT NULL, 
    trip_id VARCHAR(32) NOT NULL, 
    leg_id VARCHAR(32) NOT NULL, 
    last_status VARCHAR(14), 
    last_checked_at TIMESTAMP WITH TIME ZONE, 
    next_check_at TIMESTAMP WITH TIME ZONE, 
    delay_minutes INTEGER NOT NULL, 
    changed_notified BOOLEAN NOT NULL, 
    failures INTEGER NOT NULL, 
    info TEXT NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_flight_watch PRIMARY KEY (id), 
    CONSTRAINT fk_flight_watch_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT fk_flight_watch_trip_id_trips FOREIGN KEY(trip_id) REFERENCES trips (id) ON DELETE CASCADE, 
    CONSTRAINT uq_flight_watch_leg UNIQUE (leg_id)
);

CREATE INDEX ix_flight_watch_user_id ON flight_watch (user_id);

CREATE INDEX ix_flight_watch_next ON flight_watch (next_check_at);

CREATE TABLE trip_nudges (
    user_id VARCHAR(32) NOT NULL, 
    trip_id VARCHAR(32) NOT NULL, 
    key VARCHAR(140) NOT NULL, 
    topic VARCHAR(16) NOT NULL, 
    status VARCHAR(10) NOT NULL, 
    text TEXT, 
    sent_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    CONSTRAINT pk_trip_nudges PRIMARY KEY (id), 
    CONSTRAINT fk_trip_nudges_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT fk_trip_nudges_trip_id_trips FOREIGN KEY(trip_id) REFERENCES trips (id) ON DELETE CASCADE, 
    CONSTRAINT uq_trip_nudges_user_key UNIQUE (user_id, key)
);

CREATE INDEX ix_trip_nudges_user_id ON trip_nudges (user_id);

CREATE INDEX ix_trip_nudges_user_sent ON trip_nudges (user_id, sent_at);

CREATE TABLE card_perks (
    card_key VARCHAR(160) NOT NULL, 
    perk VARCHAR(20) NOT NULL, 
    bank VARCHAR(80) NOT NULL, 
    card_name VARCHAR(80) NOT NULL, 
    visits_per_period INTEGER, 
    period VARCHAR(12) NOT NULL, 
    conditions_text TEXT NOT NULL, 
    min_spend_paise INTEGER NOT NULL, 
    valid_from DATE, 
    valid_to DATE, 
    source_url TEXT NOT NULL, 
    checked_on DATE, 
    verified_by VARCHAR(100), 
    status VARCHAR(8) NOT NULL, 
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_card_perks PRIMARY KEY (id), 
    CONSTRAINT uq_card_perks_card_perk UNIQUE (card_key, perk)
);

CREATE INDEX ix_card_perks_card_key ON card_perks (card_key);

UPDATE alembic_version SET version_num='0017_trips' WHERE alembic_version.version_num = '0016_family_drive';

COMMIT;

