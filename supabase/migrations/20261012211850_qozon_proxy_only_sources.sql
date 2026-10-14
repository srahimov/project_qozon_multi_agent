-- Private citations are returned only through the API's RLS-checked proxy.
-- Direct authenticated Storage responses were observed cached after revocation.
-- Remove the newly introduced direct-reader policy; existing objects/buckets stay unchanged.
drop policy qozon_read_private_sources on storage.objects;
