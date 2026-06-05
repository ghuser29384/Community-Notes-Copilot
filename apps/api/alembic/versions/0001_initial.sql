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

