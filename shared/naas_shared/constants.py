# Redis Streams (pipeline stages)
STREAM_LOGIN_EVENTS = "login_events"
STREAM_NORMALIZED_EVENTS = "normalized_events"
STREAM_ENRICHED_EVENTS = "enriched_events"

# Redis Streams - maxlen cap
STREAM_MAXLEN = 10000

# Redis Pub/Sub channels (broadcast)
CHANNEL_DECISIONS = "decisions"
CHANNEL_ALERTS = "alerts"

# Consumer groups
GROUP_NORMALIZATION = "normalization_workers"
GROUP_ENRICHMENT = "enrichment_workers"
GROUP_EVALUATOR = "evaluator_workers"

# Cache key prefixes and TTLs (seconds)
CACHE_POLICY_ACTIVE = "policy:active"
CACHE_POLICY_TTL = 60
CACHE_IP_REP_PREFIX = "ip_rep:"
CACHE_IP_REP_TTL = 86400  # 24h
CACHE_GEO_PREFIX = "geo:"
CACHE_GEO_TTL = 604800  # 7d
CACHE_JWKS = "jwks:keycloak"
CACHE_JWKS_TTL = 300  # 5min
CACHE_FEATURE_FLAGS = "feature_flags"
CACHE_FEATURE_FLAGS_TTL = 60
LDAP_ENRICHMENT_CACHE_PREFIX = "ldap_enrichment:"
