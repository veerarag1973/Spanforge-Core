# `spanforge.sdk.identity` — Identity & SSO

> **Added in:** 2.0.13 (Phase 13 — SSO: SAML 2.0, SCIM 2.0, OIDC, Session Delegation)

The `spanforge.sdk.identity` module ships the `SFIdentityClient` class (and the
`sf_identity` singleton) that provides authentication and identity management
across five protocols:

| Protocol | Supported operations |
|----------|----------------------|
| **API key auth** | create/rotate/revoke keys, validate, session JWT exchange |
| **SAML 2.0** | SP metadata, Assertion Consumer Service (ACS) |
| **SCIM 2.0** | User/Group provision, list, patch, delete |
| **OIDC (PKCE)** | Authorization request, callback/token exchange |
| **SSO Session Delegation** | delegate IdP session → spanforge session, revoke, look-up |

## Import

```python
from spanforge.sdk import sf_identity          # pre-configured singleton
from spanforge.sdk.identity import SFIdentityClient  # for custom instances
```

---

## SAML 2.0

### `saml_metadata()`

> **Added in:** 2.0.13

```python
def saml_metadata(self) -> str
```

Returns the Service Provider (SP) SAML 2.0 metadata document as an XML string.
Expose this at `GET /saml/metadata` to register spanforge with your IdP.

**Returns:** `str` — well-formed XML metadata document.

```python
xml = sf_identity.saml_metadata()
# Serve at GET /saml/metadata
```

---

### `saml_acs()`

> **Added in:** 2.0.13

```python
def saml_acs(self, saml_response: str) -> dict[str, Any]
```

Processes the base64-encoded `SAMLResponse` POST parameter from your IdP.
Validates the assertion, extracts the authenticated subject, and issues a
short-lived spanforge session JWT.

| Parameter | Type | Description |
|-----------|------|-------------|
| `saml_response` | `str` | base64-encoded `SAMLResponse` from the IdP POST body |

**Returns:** `dict` with keys:

| Key | Type | Description |
|-----|------|-------------|
| `subject` | `str` | NameID / username from the assertion |
| `email` | `str` | Email attribute from the assertion |
| `session_jwt` | `str` | Short-lived spanforge session JWT |

**Raises:** `SFIdentityError` — if the assertion is invalid, expired, or the
signature does not verify.

```python
# In your SAML ACS route (e.g. POST /saml/acs):
result = sf_identity.saml_acs(request.form["SAMLResponse"])
set_session_cookie(result["session_jwt"])
```

---

## SCIM 2.0 — Users

### `scim_list_users()`

> **Added in:** 2.0.13

```python
def scim_list_users(
    self,
    filter_str: str = "",
    start_index: int = 1,
    count: int = 100,
) -> SCIMListResponse
```

Lists provisioned users with optional SCIM filter and pagination.

| Parameter | Type | Description |
|-----------|------|-------------|
| `filter_str` | `str` | SCIM filter expression, e.g. `userName eq "alice"` |
| `start_index` | `int` | 1-based page start index |
| `count` | `int` | Page size (max 100) |

**Returns:** [`SCIMListResponse`](#scimlistresponse)

```python
page = sf_identity.scim_list_users(filter_str='userName eq "alice"')
for user in page.resources:
    print(user.id, user.user_name, user.active)
```

---

### `scim_create_user()`

> **Added in:** 2.0.13

```python
def scim_create_user(self, user_data: dict) -> SCIMUser
```

Provisions a new SCIM user.  The IdP SCIM client typically calls this
automatically when a user is assigned to the spanforge application.

| Parameter | Type | Description |
|-----------|------|-------------|
| `user_data` | `dict` | SCIM User resource as per RFC 7643 |

**Returns:** [`SCIMUser`](#scimuser)

**Raises:** `SFIdentityError` — if `userName` already exists.

```python
user = sf_identity.scim_create_user({
    "userName": "alice@example.com",
    "name": {"givenName": "Alice", "familyName": "Smith"},
    "emails": [{"value": "alice@example.com", "primary": True}],
    "active": True,
})
print(user.id)
```

---

### `scim_get_user()`

> **Added in:** 2.0.13

```python
def scim_get_user(self, user_id: str) -> SCIMUser
```

Retrieves a single SCIM user by its spanforge-assigned `id`.

| Parameter | Type | Description |
|-----------|------|-------------|
| `user_id` | `str` | spanforge SCIM user ID (e.g. `scim-user-<ulid>`) |

**Returns:** [`SCIMUser`](#scimuser)

**Raises:** `SFIdentityError` — if the user is not found.

---

### `scim_patch_user()`

> **Added in:** 2.0.13

```python
def scim_patch_user(self, user_id: str, patch_ops: list[dict]) -> SCIMUser
```

Applies SCIM PATCH operations (RFC 7644 §3.5.2) to a user — typically used to
suspend (`"active": false`) or re-activate a user.

| Parameter | Type | Description |
|-----------|------|-------------|
| `user_id` | `str` | spanforge SCIM user ID |
| `patch_ops` | `list[dict]` | SCIM PATCH `Operations` array |

**Returns:** [`SCIMUser`](#scimuser) — updated user record.

```python
# Suspend a user
sf_identity.scim_patch_user(user_id, [
    {"op": "replace", "path": "active", "value": False}
])
```

---

### `scim_delete_user()`

> **Added in:** 2.0.13

```python
def scim_delete_user(self, user_id: str) -> None
```

Deprovisions and permanently removes a SCIM user. All SSO sessions for this
user are implicitly revoked.

| Parameter | Type | Description |
|-----------|------|-------------|
| `user_id` | `str` | spanforge SCIM user ID |

**Raises:** `SFIdentityError` — if the user is not found.

---

## SCIM 2.0 — Groups

### `scim_list_groups()`

> **Added in:** 2.0.13

```python
def scim_list_groups(
    self,
    start_index: int = 1,
    count: int = 100,
) -> SCIMListResponse
```

Lists provisioned groups.

**Returns:** [`SCIMListResponse`](#scimlistresponse) — `.resources` entries are
[`SCIMGroup`](#scimgroup) objects.

---

### `scim_create_group()`

> **Added in:** 2.0.13

```python
def scim_create_group(self, group_data: dict) -> SCIMGroup
```

Provisions a new SCIM group.

| Parameter | Type | Description |
|-----------|------|-------------|
| `group_data` | `dict` | SCIM Group resource as per RFC 7643 |

**Returns:** [`SCIMGroup`](#scimgroup)

```python
group = sf_identity.scim_create_group({
    "displayName": "spanforge-admins",
    "members": [{"value": user.id, "display": user.user_name}],
})
```

---

### `scim_delete_group()`

> **Added in:** 2.0.13

```python
def scim_delete_group(self, group_id: str) -> None
```

Removes a SCIM group.  Users that were members of the group are **not**
deleted.

| Parameter | Type | Description |
|-----------|------|-------------|
| `group_id` | `str` | spanforge SCIM group ID |

---

## OIDC (PKCE Relying Party)

### `oidc_authorize()`

> **Added in:** 2.0.13

```python
def oidc_authorize(
    self,
    provider_url: str,
    client_id: str,
    redirect_uri: str,
    scope: str = "openid email profile",
) -> OIDCAuthRequest
```

Constructs an OIDC PKCE authorization request.  Redirect the user to
`result.authorization_url` to begin the login flow.

| Parameter | Type | Description |
|-----------|------|-------------|
| `provider_url` | `str` | OIDC provider discovery URL (e.g. `https://idp.example.com`) |
| `client_id` | `str` | OAuth 2.0 client ID registered with the provider |
| `redirect_uri` | `str` | Callback URI registered with the provider |
| `scope` | `str` | Space-separated scopes (default: `openid email profile`) |

**Returns:** [`OIDCAuthRequest`](#oidcauthrequest)

```python
auth_req = sf_identity.oidc_authorize(
    provider_url=os.environ["SPANFORGE_OIDC_PROVIDER_URL"],
    client_id=os.environ["SPANFORGE_OIDC_CLIENT_ID"],
    redirect_uri="https://app.example.com/oidc/callback",
)
# Store auth_req.state in the user session, then redirect:
# return redirect(auth_req.authorization_url)
```

---

### `oidc_callback()`

> **Added in:** 2.0.13

```python
def oidc_callback(
    self,
    code: str,
    state: str,
    subject: str,
    email: str,
) -> OIDCTokenResult
```

Exchanges the authorization `code` for an access token and issues a
spanforge session JWT.

| Parameter | Type | Description |
|-----------|------|-------------|
| `code` | `str` | Authorization code from the IdP callback |
| `state` | `str` | State value from the original `oidc_authorize()` call |
| `subject` | `str` | Subject claim from the ID token |
| `email` | `str` | Email claim from the ID token |

**Returns:** [`OIDCTokenResult`](#oidctokenresult)

**Raises:** `SFIdentityError` — on `state` mismatch or token exchange failure.

```python
# In your OIDC callback route:
result = sf_identity.oidc_callback(
    code=request.args["code"],
    state=request.args["state"],
    subject=id_token_claims["sub"],
    email=id_token_claims["email"],
)
set_session_cookie(result.session_jwt)
```

---

## SSO Session Delegation

### `sso_delegate_session()`

> **Added in:** 2.0.13

```python
def sso_delegate_session(
    self,
    idp_session_id: str,
    subject: str,
    email: str,
    project_id: str,
) -> SSOSession
```

Creates a spanforge-side session that is bound to an external IdP session.
Call this after validating the IdP session server-side.

| Parameter | Type | Description |
|-----------|------|-------------|
| `idp_session_id` | `str` | Session ID from the IdP (SAML `SessionIndex`, OIDC `sid`, etc.) |
| `subject` | `str` | Authenticated subject / username |
| `email` | `str` | Authenticated email |
| `project_id` | `str` | spanforge project the session is scoped to |

**Returns:** [`SSOSession`](#ssosession)

```python
session = sf_identity.sso_delegate_session(
    idp_session_id=saml_session_index,
    subject="alice@example.com",
    email="alice@example.com",
    project_id="proj-abc123",
)
# Store session.session_id in the user's spanforge session cookie
```

---

### `sso_delegate_session_async()` — async variant

> **Added in:** 2.0.14

```python
async def sso_delegate_session_async(
    self,
    idp_session_id: str,
    subject: str,
    *,
    email: str = "",
    project_id: str = "default",
) -> SSOSession
```

Non-blocking async variant of `sso_delegate_session()`.  Delegates to the
synchronous method via `asyncio.get_event_loop().run_in_executor()` so it
never blocks the event loop.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `idp_session_id` | `str` | *(required)* | IdP session ID |
| `subject` | `str` | *(required)* | Authenticated subject |
| `email` | `str` | `""` | Authenticated email |
| `project_id` | `str` | `"default"` | Project scope |

**Returns:** [`SSOSession`](#ssosession)

**Example:**

```python
import asyncio
from spanforge.sdk import sf_identity

session = asyncio.run(
    sf_identity.sso_delegate_session_async(
        "idp-sess-xyz",
        "alice@example.com",
        email="alice@example.com",
        project_id="proj-abc",
    )
)
print(session.session_id)
```

---

### `sso_get_session()`

> **Added in:** 2.0.13

```python
def sso_get_session(self, session_id: str) -> SSOSession
```

Retrieves a previously delegated session by its spanforge `session_id`.

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `str` | The spanforge session ID from `sso_delegate_session()` |

**Returns:** [`SSOSession`](#ssosession)

**Raises:** `SFIdentityError` — if the session is not found or has expired.

---

### `sso_revoke_idp_session()`

> **Added in:** 2.0.13

```python
def sso_revoke_idp_session(self, idp_session_id: str) -> bool
```

Revokes **all** spanforge sessions that were delegated from the given
`idp_session_id`.  Call this from your IdP's back-channel logout handler.

| Parameter | Type | Description |
|-----------|------|-------------|
| `idp_session_id` | `str` | The original IdP session ID |

**Returns:** `True` if any sessions were revoked; `False` if none matched.

```python
# SAML back-channel logout / OIDC front-channel logout endpoint:
revoked = sf_identity.sso_revoke_idp_session(saml_session_index)
if revoked:
    print("User sessions revoked")
```

---

## Return types

### `SCIMUser`

```python
@dataclass
class SCIMUser:
    id: str                  # "scim-user-<ulid>"
    user_name: str           # primary SCIM identifier
    display_name: str
    emails: list[dict]       # [{"value": "...", "primary": True}]
    active: bool
    groups: list[str]        # list of group IDs
    created_at: str          # ISO 8601 UTC
    updated_at: str          # ISO 8601 UTC
```

---

### `SCIMGroup`

```python
@dataclass
class SCIMGroup:
    id: str                  # "scim-group-<ulid>"
    display_name: str
    members: list[dict]      # [{"value": user_id, "display": user_name}]
    created_at: str          # ISO 8601 UTC
```

---

### `SCIMListResponse`

```python
@dataclass
class SCIMListResponse:
    total_results: int
    start_index: int
    items_per_page: int
    resources: list[SCIMUser | SCIMGroup]
```

---

### `OIDCAuthRequest`

```python
@dataclass
class OIDCAuthRequest:
    authorization_url: str   # redirect the user here
    state: str               # CSRF state value — store in session
    code_verifier: str       # PKCE verifier — store server-side
    code_challenge: str      # sent to the IdP
    provider_url: str
    client_id: str
    redirect_uri: str
    scope: str
```

---

### `OIDCTokenResult`

```python
@dataclass
class OIDCTokenResult:
    access_token: str
    token_type: str          # "Bearer"
    expires_in: int          # seconds
    id_token: str | None
    session_jwt: str         # spanforge session JWT
    subject: str
    email: str
```

---

### `SSOSession`

```python
@dataclass
class SSOSession:
    session_id: str          # spanforge session ID ("sso-<ulid>")
    idp_session_id: str      # originating IdP session ID
    subject: str
    email: str
    project_id: str
    created_at: str          # ISO 8601 UTC
    expires_at: str          # ISO 8601 UTC (default +8 h)
    revoked: bool
```

---

## Exceptions

| Exception | Raised when |
|-----------|-------------|
| `SFIdentityError` | Base class for all identity errors |

All identity exceptions are re-exported from `spanforge.sdk`:

```python
from spanforge.sdk import SFIdentityError
```

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SPANFORGE_SAML_IDP_METADATA_URL` | — | URL of your IdP SAML metadata XML |
| `SPANFORGE_OIDC_PROVIDER_URL` | — | OIDC provider discovery base URL |
| `SPANFORGE_OIDC_CLIENT_ID` | — | OAuth 2.0 client ID |
| `SPANFORGE_OIDC_CLIENT_SECRET` | — | OAuth 2.0 client secret (**never log**) |
| `SPANFORGE_SCIM_BASE_URL` | — | SCIM 2.0 base URL exposed to IdP |

See [configuration.md](../configuration.md#identity-service-settings-phase-13) for full details.

---

## Thread safety

`SFIdentityClient` is safe to use from multiple threads simultaneously.
The in-memory user/group/session stores are protected by `threading.Lock()`
objects.  The `sf_identity` singleton uses the same locks.
