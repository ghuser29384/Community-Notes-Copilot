-- Initial production schema sketch. The dependency-light fixture runtime stores
-- records in memory, but these tables map to the required domain models.

create table if not exists candidate_posts (
  id uuid primary key,
  x_post_id text not null,
  status text not null,
  canonical_hash text not null unique,
  normalized_context jsonb not null,
  created_at timestamptz not null default now()
);

create table if not exists draft_notes (
  id uuid primary key,
  candidate_id uuid not null references candidate_posts(id),
  text text not null,
  exact_text_hash text not null,
  status text not null,
  operator_approved boolean not null default false,
  support_map_json jsonb not null,
  created_at timestamptz not null default now()
);

create table if not exists app_records (
  record_type text not null,
  id text not null,
  parent_id text,
  canonical_hash text,
  payload jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (record_type, id)
);

create index if not exists app_records_parent_idx
  on app_records (record_type, parent_id);

create unique index if not exists app_records_candidate_hash_idx
  on app_records (canonical_hash)
  where record_type = 'candidate' and canonical_hash is not null;
