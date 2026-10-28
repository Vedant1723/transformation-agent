# VPN / ingress-owned access control

This mode is for the user's confirmed VPN-only deployment where ingress
overwrites x-channel-name and x-service-id and applies rate limiting. Network
controls must block direct backend access, including from untrusted workloads.
These headers are metadata, not cryptographic proof of authentication.

Set AUTH_MODE=ingress and configure INGRESS_CHANNEL_NAME and INGRESS_SERVICE_ID
to the exact values ingress supplies. Set INGRESS_SHARED_SUBJECT to the shared
backend username. No GATEWAY_SHARED_SECRET, X-Gateway-Key or X-Authenticated-User
is required in this mode. The default remains AUTH_MODE=gateway for existing
deployments; that mode retains its shared-key authentication checks.

All existing business APIs remain available. They require the configured
ingress metadata and an active, provisioned shared user. Saved transformations,
feedback and ownership are shared by every caller using that account.
Feedback review, benchmark checks and training-operator permissions remain
unchanged; automatic training is disabled in the sample ConfigMap.

After migrations, provision the identity once from backend:

```sh
python -m scripts.provision_gateway_user --subject transformation-service --email transformation-service@example.invalid
```

Use an appropriate service-account email for your organisation. Provisioning
creates no login password. Rebuild the image and deploy the updated ConfigMap.
Context path remains /transformation-agent. Ingress must preserve that prefix.
Historical shared-key deployment docs describe gateway mode, not ingress mode.

Do not commit real database credentials or internal tokens to public Git.
