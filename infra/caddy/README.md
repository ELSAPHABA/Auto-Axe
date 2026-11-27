# Caddy

Phase 2 adds [Caddyfile.example](Caddyfile.example) as a *review-only* HTTPS edge configuration. The disposable fixture Compose stack still has no Caddy process or public listener. Keycloak OIDC issuer, redirects, production session secrets, certificate issuance/rotation and separate verified mutual-TLS broker listener have not been provisioned or tested. No trusted X-Client-Certificate header is accepted by the backend. This example must not be deployed as production security without external validation. External MCP remains Phase 6.
