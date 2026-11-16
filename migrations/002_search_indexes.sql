-- Search speed, measured on 982,666 companies:
--  * org number prefix (LIKE '559…%'): 370 ms -> 0.3 ms. The primary key's index can't serve
--    LIKE under a non-C collation; text_pattern_ops can.
--  * name search: 320 ms -> 40-70 ms. GiST trigram serves both the ILIKE filter and
--    "nearest name first" ordering (<->), so the top 20 come straight off the index instead of
--    sorting every match. It replaces the GIN index (one trigram index, not two: 123 MB vs 54+123).
create index companies_org_nr_prefix on companies (org_nr text_pattern_ops);
create index companies_name_gist on companies using gist (name gist_trgm_ops);
drop index companies_name_trgm;
