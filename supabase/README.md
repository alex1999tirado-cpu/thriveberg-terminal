# THRIVEBERG Social setup

THRIVEBERG Social needs one shared Supabase project so every installed copy talks
to the same user directory and conversations.

1. Create a Supabase project.
2. Open its SQL editor and run `social_schema.sql` once.
3. Copy the project URL and the **publishable** key from the project's Connect
   dialog. Never use a secret or `service_role` key.
4. Put those public client values in `ajax_terminal/public_client_config.py`
   before building the installer. Installed users do not configure them.

The publishable key is intended for desktop clients and may be distributed with
the executable. Access is restricted by the row-level security policies in
`social_schema.sql`. A sidecar `ajax-social.json`, encrypted local configuration,
or process environment may override the bundled project for development and
self-hosted deployments.

Email confirmation can be enabled or disabled in the Supabase Auth settings. If
enabled, new users must confirm their email before signing in.
