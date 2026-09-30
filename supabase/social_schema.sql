-- AJAX Social schema for Supabase. Run once in the Supabase SQL editor.
create extension if not exists citext;

create table if not exists public.profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    username citext not null unique check (username ~ '^[a-z0-9_.-]{3,24}$'),
    display_name text not null check (char_length(display_name) between 1 and 50),
    status text not null default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.friend_requests (
    id uuid primary key default gen_random_uuid(),
    sender_id uuid not null references public.profiles(id) on delete cascade,
    receiver_id uuid not null references public.profiles(id) on delete cascade,
    status text not null default 'pending' check (status in ('pending', 'accepted', 'rejected')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    check (sender_id <> receiver_id)
);

create unique index if not exists friend_requests_active_pair
on public.friend_requests (least(sender_id, receiver_id), greatest(sender_id, receiver_id))
where status in ('pending', 'accepted');

create table if not exists public.messages (
    id uuid primary key default gen_random_uuid(),
    sender_id uuid not null references public.profiles(id) on delete cascade,
    recipient_id uuid not null references public.profiles(id) on delete cascade,
    body text not null default '' check (char_length(body) <= 2000),
    shared_command text check (shared_command is null or char_length(shared_command) <= 96),
    created_at timestamptz not null default now(),
    read_at timestamptz,
    check (sender_id <> recipient_id),
    check (body <> '' or shared_command is not null)
);

create index if not exists messages_conversation_idx
on public.messages (sender_id, recipient_id, created_at);

create or replace function public.handle_new_social_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
    insert into public.profiles (id, username, display_name)
    values (
        new.id,
        lower(coalesce(new.raw_user_meta_data ->> 'username', split_part(new.email, '@', 1))),
        coalesce(new.raw_user_meta_data ->> 'display_name', new.raw_user_meta_data ->> 'username', split_part(new.email, '@', 1))
    );
    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
after insert on auth.users
for each row execute procedure public.handle_new_social_user();

create or replace function public.are_friends(first_user uuid, second_user uuid)
returns boolean
language sql
stable
security definer set search_path = public
as $$
    select exists (
        select 1 from public.friend_requests
        where status = 'accepted'
          and ((sender_id = first_user and receiver_id = second_user)
            or (sender_id = second_user and receiver_id = first_user))
    );
$$;

alter table public.profiles enable row level security;
alter table public.friend_requests enable row level security;
alter table public.messages enable row level security;

drop policy if exists "profiles visible to authenticated users" on public.profiles;
create policy "profiles visible to authenticated users"
on public.profiles for select to authenticated using (true);

drop policy if exists "users update own profile" on public.profiles;
create policy "users update own profile"
on public.profiles for update to authenticated using (auth.uid() = id) with check (auth.uid() = id);

drop policy if exists "friend requests visible to participants" on public.friend_requests;
create policy "friend requests visible to participants"
on public.friend_requests for select to authenticated
using (auth.uid() = sender_id or auth.uid() = receiver_id);

drop policy if exists "users send own friend requests" on public.friend_requests;
create policy "users send own friend requests"
on public.friend_requests for insert to authenticated
with check (auth.uid() = sender_id and sender_id <> receiver_id and status = 'pending');

drop policy if exists "receivers answer pending requests" on public.friend_requests;
create policy "receivers answer pending requests"
on public.friend_requests for update to authenticated
using (auth.uid() = receiver_id and status = 'pending')
with check (auth.uid() = receiver_id and status in ('accepted', 'rejected'));

drop policy if exists "friends read their messages" on public.messages;
create policy "friends read their messages"
on public.messages for select to authenticated
using (auth.uid() in (sender_id, recipient_id) and public.are_friends(sender_id, recipient_id));

drop policy if exists "friends send messages" on public.messages;
create policy "friends send messages"
on public.messages for insert to authenticated
with check (auth.uid() = sender_id and public.are_friends(sender_id, recipient_id));

revoke all on public.profiles, public.friend_requests, public.messages from anon;
grant select, update on public.profiles to authenticated;
revoke update on public.friend_requests from authenticated;
grant select, insert on public.friend_requests to authenticated;
grant update (status) on public.friend_requests to authenticated;
grant select, insert on public.messages to authenticated;

revoke all on function public.handle_new_social_user() from public, anon, authenticated;
revoke all on function public.are_friends(uuid, uuid) from public, anon;
grant execute on function public.are_friends(uuid, uuid) to authenticated;
