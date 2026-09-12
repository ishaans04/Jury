-- Tier assignment is by rule, not by model (PRD §16.2).
-- Unknown domains default to tier 3 in code.
insert into domain_tiers (domain, tier, note) values
-- tier 1 — regulators, registers, filings, stores, archives
('sec.gov',1,'filings'), ('rbi.org.in',1,'regulator'), ('mca.gov.in',1,'company register'),
('gst.gov.in',1,'tax register'), ('eur-lex.europa.eu',1,'regulator'),
('gov.uk',1,'regulator'), ('ftc.gov',1,'regulator'), ('fda.gov',1,'regulator'),
('web.archive.org',1,'wayback snapshot'), ('play.google.com',1,'store listing'),
('apps.apple.com',1,'store listing'),
-- tier 2 — structured third-party data and official statistics
('crunchbase.com',2,'funding database'), ('tracxn.com',2,'funding database'),
('data.worldbank.org',2,'official statistics'), ('census.gov',2,'official statistics'),
('statista.com',2,'aggregated statistics'), ('g2.com',2,'review aggregate with counts'),
('capterra.com',2,'review aggregate with counts'), ('trustpilot.com',2,'review aggregate'),
-- tier 3 — journalism, analysts, company blogs
('techcrunch.com',3,'journalism'), ('theinformation.com',3,'journalism'),
('economictimes.indiatimes.com',3,'journalism'), ('yourstory.com',3,'journalism'),
('inc42.com',3,'journalism'), ('a16z.com',3,'analyst'), ('failory.com',3,'postmortem collection'),
('autopsy.io',3,'postmortem collection'),
-- tier 4 — community anecdote
('reddit.com',4,'forum'), ('news.ycombinator.com',4,'forum'),
('indiehackers.com',4,'forum'), ('producthunt.com',4,'launch listing'),
('quora.com',4,'forum'), ('stackoverflow.com',4,'forum');
