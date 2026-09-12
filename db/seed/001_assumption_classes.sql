-- P4: the coverage denominator. Hand-authored static reference data.
-- NEVER generate these rows at runtime (PRD §25).
-- crit_weight: 1.0 = blocking, 0.6 = high, 0.3 = medium.

insert into assumption_classes (key, archetype, label, question, crit_weight) values
-- ── marketplace (PRD §12.3, verbatim) ──────────────────────────────────────
('marketplace.demand_exists',        'marketplace','Demand exists',        'Do buyers actively look for this today?',1.0),
('marketplace.supply_liquidity',     'marketplace','Supply liquidity',     'Will enough supply join and stay?',1.0),
('marketplace.take_rate_tolerance',  'marketplace','Take-rate tolerance',  'Will either side accept the commission?',1.0),
('marketplace.unit_economics',       'marketplace','Unit economics',       'Does revenue per transaction exceed delivered cost?',1.0),
('marketplace.regulatory',           'marketplace','Regulatory',           'Any licence, tax, or compliance requirement?',1.0),
('marketplace.channel_cost',         'marketplace','Channel cost',         'Can both sides be acquired affordably?',0.6),
('marketplace.frequency',            'marketplace','Frequency',            'Is purchase frequency high enough to matter?',0.6),
('marketplace.disintermediation',    'marketplace','Disintermediation',    'What stops both sides transacting off-platform?',0.6),
('marketplace.ops_feasibility',      'marketplace','Ops feasibility',      'Can fulfilment, trust and dispute be operated at this scale?',0.6),
('marketplace.incumbency',           'marketplace','Incumbency',           'Is the space already served or already a graveyard?',0.3),

-- ── subscription_saas (PRD §12.3, verbatim) ────────────────────────────────
('saas.pain_severity',   'subscription_saas','Pain severity',   'Is the pain acute enough to pay for?',1.0),
('saas.wtp_above_cost',  'subscription_saas','WTP above cost',  'Does willingness to pay exceed delivered cost per account?',1.0),
('saas.retention',       'subscription_saas','Retention',       'Will accounts stay long enough to repay acquisition?',1.0),
('saas.channel_cost',    'subscription_saas','Channel cost',    'Is CAC recoverable within an acceptable payback?',1.0),
('saas.buyer_identity',  'subscription_saas','Buyer identity',  'Is there a budget holder who can actually buy?',0.6),
('saas.switching_cost',  'subscription_saas','Switching cost',  'What makes them leave the current solution?',0.6),
('saas.dependency_risk', 'subscription_saas','Dependency risk', 'Do required third parties permit this at viable cost?',0.6),
('saas.data_compliance', 'subscription_saas','Data compliance', 'Any data, privacy or regulatory constraint?',0.6),
('saas.incumbency',      'subscription_saas','Incumbency',      'Is the category already won or already a graveyard?',0.3),
('saas.expansion',       'subscription_saas','Expansion',       'Is there an observable adjacency for expansion?',0.3),

-- ── d2c ────────────────────────────────────────────────────────────────────
('d2c.demand_exists',    'd2c','Demand exists',    'Do people already buy this category online?',1.0),
('d2c.gross_margin',     'd2c','Gross margin',     'Does landed price exceed COGS plus fulfilment by enough to fund acquisition?',1.0),
('d2c.cac_payback',      'd2c','CAC payback',      'Can a first order be acquired below contribution margin?',1.0),
('d2c.repeat_rate',      'd2c','Repeat rate',      'Will enough customers order again to make LTV exceed CAC?',1.0),
('d2c.supply_chain',     'd2c','Supply chain',     'Can the product be sourced at the assumed cost and lead time?',1.0),
('d2c.differentiation',  'd2c','Differentiation',  'Is there a reason to buy this over an incumbent brand?',0.6),
('d2c.return_rate',      'd2c','Return rate',      'Will returns and refunds stay below the margin line?',0.6),
('d2c.channel_access',   'd2c','Channel access',   'Is the assumed acquisition channel open and affordable?',0.6),
('d2c.compliance',       'd2c','Compliance',       'Any labelling, safety, import or category restriction?',0.6),
('d2c.incumbency',       'd2c','Incumbency',       'Is the shelf already crowded with near-identical products?',0.3),

-- ── services (minimum viable, 5) ───────────────────────────────────────────
('services.demand_exists',  'services','Demand exists',  'Are clients already paying someone for this work?',1.0),
('services.rate_tolerance', 'services','Rate tolerance', 'Will clients pay a rate above fully-loaded delivery cost?',1.0),
('services.utilisation',    'services','Utilisation',    'Can billable utilisation stay high enough to be profitable?',1.0),
('services.deliverability', 'services','Deliverability', 'Can the work be delivered at the promised quality and speed?',0.6),
('services.pipeline',       'services','Pipeline',       'Is there a repeatable channel to new clients?',0.6),

-- ── ad_consumer (minimum viable, 5) ────────────────────────────────────────
('ad.audience_reachable', 'ad_consumer','Audience reachable','Can a large enough audience be reached at low cost?',1.0),
('ad.engagement_depth',   'ad_consumer','Engagement depth',  'Will users return often enough to generate inventory?',1.0),
('ad.rpm_vs_cost',        'ad_consumer','RPM vs cost',       'Does revenue per thousand impressions exceed serving and content cost?',1.0),
('ad.retention',          'ad_consumer','Retention',         'Do users stay long enough to repay acquisition?',0.6),
('ad.platform_risk',      'ad_consumer','Platform risk',     'Does the distribution platform permit this and control the terms?',0.6),

-- ── hardware (minimum viable, 5) ───────────────────────────────────────────
('hardware.demand_exists', 'hardware','Demand exists', 'Do buyers pay for a physical device that solves this?',1.0),
('hardware.bom_margin',    'hardware','BOM margin',    'Does the sellable price exceed bill of materials plus assembly and freight?',1.0),
('hardware.manufacturing', 'hardware','Manufacturing', 'Can this be manufactured at the assumed cost, quality and volume?',1.0),
('hardware.certification', 'hardware','Certification', 'Which safety, radio or import certifications are required?',1.0),
('hardware.support_cost',  'hardware','Support cost',  'Will warranty, returns and support stay below the margin line?',0.6);
