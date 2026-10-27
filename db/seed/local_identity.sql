-- Local-only synthetic fixture. Never run this file against hosted Supabase.
BEGIN;

INSERT INTO auth.users (id, raw_user_meta_data)
VALUES (
    '00000000-0000-4000-8000-000000000001',
    '{"display_name":"Synthetic Teacher"}'::jsonb
)
ON CONFLICT (id) DO NOTHING;

SELECT public.create_personal_workspace(
    '00000000-0000-4000-8000-000000000001'::uuid,
    'Synthetic Teacher Workspace',
    'synthetic-teacher',
    'terms-v1',
    'safety-v1'
);

COMMIT;
