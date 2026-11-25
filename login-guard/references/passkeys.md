# Passkey（WebAuthn）

三種用法：登入後在設定登記、當密碼後的第二步、不輸密碼單獨登入。伺服器端用 Node `@simplewebauthn/server`（v14）或 Python `webauthn`（py_webauthn v3），瀏覽器端用 `@simplewebauthn/browser`。

## 規則與理由

**網址**

- **只在一個 HTTPS 網址上用**：設定一個正式網址（例如 `https://admin.example.com`），RP ID 是它的主機名稱，驗證時 `expectedOrigin` 與 `expectedRPID` 都只接受它。用 http、IP 或其他網址打開時，所有 passkey 端點回 409 `passkey_unavailable`（不算失敗次數），頁面說明原因並改用 TOTP。是不是 HTTPS 用入口算好的值（[client-ip.md](client-ip.md)），不看 `request.url`。
- 頁面先在瀏覽器確認 `location.origin` 等於正式網址、`window.isSecureContext`、有 WebAuthn（`browserSupportsWebAuthn()`），不符合就只顯示原因，不顯示可按的按鈕。

**挑戰值（challenge）**

- 伺服器產生、存在伺服器，**只能回答一次**（驗證前先取走並刪除），幾分鐘就過期。
- **綁定發起者**：第二步的挑戰值記在這個瀏覽器開著的第二步上；設定頁登記的挑戰值綁定發起的 session（另發一個只在記憶體、5 分鐘、只能用一次的登記 token）；免密碼登入的挑戰值誰都能要，所以存的數量設上限（例如 1000 個，滿了丟最舊的）。
- 要挑戰值的 options 端點不呼叫 `limit`（[two-step-login.md](two-step-login.md)）。

**登記**

- **登入後在設定登記**：已登入的 session 不需要登記碼，直接新增。
- **第一次還沒有任何能登入的裝置時**：用主機指令產生一次性登記碼（10 分鐘、用一次就失效、只存雜湊，新的取代舊的），登記時要密碼加登記碼。登記不發登入 Cookie。只要已經設好任何一種第二步，登入頁就不再顯示登記入口。
- `excludeCredentials` 帶已登記的 passkey，同一台裝置不會重複登記。瀏覽器回 `InvalidStateError` 時，頁面直接說「這台裝置已經有 passkey，直接用它登入」，不要只說失敗。
- 登記用 `userVerification: 'preferred'`，驗證登記時不要求 UV（使用者驗證：PIN、指紋或螢幕鎖），沒有 PIN 的實體安全金鑰才登記得進來、當第二步用。免密碼登入是否安全由**登入時**的 UV 檢查保證，不靠登記時；`residentKey: 'preferred'` 一定要寫：沒寫等於「不需要可探索憑證」，瀏覽器可能只開系統自己的安全金鑰視窗（USB、NFC、掃 QR），Bitwarden 等密碼管理器就算設為系統預設也可能收不到登記請求（實測發生過）；`attestationType: 'none'`。
- `userID` 用每個使用者固定的隨機位元組，不要放 email 或資料庫編號：它會存在驗證器上。
- 存：credential ID、公鑰（base64url）、簽章計數器、transports、登記時的 User-Agent（顯示名稱用）、登記與最後使用時間。設定頁只回傳顯示用欄位，credential ID 與公鑰留在伺服器。
- 設定頁登記失敗不要回 401：前端通常把 401 當成「已登出」而重新載入。用 400 `passkey_failed`、410 `enroll_expired`。

**登入**

- **當第二步**：`userVerification: 'preferred'`，驗證時不要求 UV（擁有這把鑰匙就是第二個因素，沒有 PIN 的實體安全金鑰也能用）。
- **單獨登入**：`userVerification: 'required'`，驗證時 `requireUserVerification` 一定要開。SimpleWebAuthn 預設是開的；**py_webauthn 預設是關的**，要明確傳 `require_user_verification=True`。
- `allowCredentials`：只有一個管理者時列出全部 passkey，之前不是以可探索憑證登記的也能用；多使用者的免密碼登入留空，讓瀏覽器自己列出這個網站的 passkey，再用回傳的 credential ID 找出是誰。
- **簽章計數器**：兩邊的函式庫都會拒絕「任一方不為 0 且新值沒有變大」的回應。寫回新值要用比較後寫入（`UPDATE ... SET counter = :new WHERE id = :id AND counter = :old`），兩個同時的登入才不會都通過；期間被刪掉的 passkey 也不會通過。
- 驗證失敗（簽章、來源、挑戰值、計數器、UV）一律算一次失敗；通過才 `succeeded` 並建 session。
- 刪除 passkey 後它立刻不能登入；刪除要先確認。

## Node：`@simplewebauthn/server`

```ts
// passkeys.ts
import {
	generateAuthenticationOptions,
	generateRegistrationOptions,
	verifyAuthenticationResponse,
	verifyRegistrationResponse,
	type AuthenticationResponseJSON,
	type RegistrationResponseJSON
} from '@simplewebauthn/server';

export interface Site { origin: string; rpID: string; rpName: string }
/** 每把 passkey 存的東西；id 與 publicKey 是 base64url。 */
export interface StoredPasskey { id: string; publicKey: string; counter: number; transports: string[] }
export type PasskeyUse = 'alone' | 'second-step';

/** 設定頁登記。options.challenge 存在伺服器，綁定這個 session，只能用一次。 */
export function registrationOptions(site: Site, user: { id: Uint8Array; name: string }, existing: StoredPasskey[]) {
	return generateRegistrationOptions({
		rpName: site.rpName,
		rpID: site.rpID,
		userID: user.id,
		userName: user.name,
		attestationType: 'none',
		excludeCredentials: existing.map(({ id, transports }) => ({ id, transports })),
		authenticatorSelection: { residentKey: 'preferred', userVerification: 'preferred' },
		timeout: 120_000
	});
}

export async function verifyRegistration(site: Site, expectedChallenge: string, response: RegistrationResponseJSON): Promise<StoredPasskey | null> {
	try {
		const result = await verifyRegistrationResponse({
			response,
			expectedChallenge,
			expectedOrigin: site.origin,
			expectedRPID: site.rpID,
			requireUserVerification: false // 預設 true；UV 在免密碼登入時才檢查
		});
		if (!result.verified) return null;
		const { credential } = result.registrationInfo;
		return { id: credential.id, publicKey: Buffer.from(credential.publicKey).toString('base64url'), counter: credential.counter, transports: credential.transports ?? [] };
	} catch {
		return null; // 格式錯、來源不對、挑戰值不對：對呼叫端都一樣
	}
}

/** `allow` 空陣列 = 讓瀏覽器自己列出這個網站的 passkey。 */
export function loginOptions(site: Site, allow: StoredPasskey[], use: PasskeyUse) {
	return generateAuthenticationOptions({
		rpID: site.rpID,
		allowCredentials: allow.map(({ id, transports }) => ({ id, transports })),
		userVerification: use === 'alone' ? 'required' : 'preferred',
		timeout: 120_000
	});
}

/** 通過時回傳新的計數器，否則 null。 */
export async function verifyLogin(site: Site, expectedChallenge: string, response: AuthenticationResponseJSON, passkey: StoredPasskey, use: PasskeyUse): Promise<number | null> {
	try {
		const result = await verifyAuthenticationResponse({
			response,
			expectedChallenge,
			expectedOrigin: site.origin,
			expectedRPID: site.rpID,
			credential: { id: passkey.id, publicKey: Buffer.from(passkey.publicKey, 'base64url'), counter: passkey.counter, transports: passkey.transports },
			requireUserVerification: use === 'alone'
		});
		return result.verified ? result.authenticationInfo.newCounter : null;
	} catch {
		return null;
	}
}
```

瀏覽器端：`@simplewebauthn/browser` v13 起參數包在 `{ optionsJSON }` 裡（`startRegistration({ optionsJSON: options })`）；`catch` 到的錯誤把 `error.name` 回報給伺服器記錄（[session-and-headers.md](session-and-headers.md) 的登入紀錄）。

## Python：`webauthn`（py_webauthn）

```python
# passkeys.py
from dataclasses import dataclass
from typing import Literal

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

Use = Literal["alone", "second-step"]


@dataclass
class Site:
    origin: str  # "https://admin.example.com"
    rp_id: str  # "admin.example.com"
    rp_name: str


@dataclass
class StoredPasskey:
    id: str  # base64url
    public_key: str  # base64url
    sign_count: int
    transports: list[str]


def _descriptor(p: StoredPasskey) -> PublicKeyCredentialDescriptor:
    known = {t.value for t in AuthenticatorTransport}
    return PublicKeyCredentialDescriptor(
        id=base64url_to_bytes(p.id), transports=[AuthenticatorTransport(t) for t in p.transports if t in known]
    )


def registration_options(site: Site, user_id: bytes, user_name: str, existing: list[StoredPasskey]) -> tuple[str, bytes]:
    """回傳（給瀏覽器的 JSON, 要存在伺服器的 challenge）。"""
    options = generate_registration_options(
        rp_id=site.rp_id,
        rp_name=site.rp_name,
        user_id=user_id,
        user_name=user_name,
        exclude_credentials=[_descriptor(p) for p in existing],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        timeout=120_000,
    )
    return options_to_json(options), options.challenge


def verify_registration(site: Site, challenge: bytes, credential: dict) -> StoredPasskey | None:
    try:
        result = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=site.rp_id,
            expected_origin=site.origin,
            require_user_verification=False,  # UV 在免密碼登入時才檢查
        )
    except WebAuthnException:  # 簽章、來源、挑戰值不對，或格式錯
        return None
    return StoredPasskey(
        id=bytes_to_base64url(result.credential_id),
        public_key=bytes_to_base64url(result.credential_public_key),
        sign_count=result.sign_count,
        transports=list(credential.get("response", {}).get("transports", [])),
    )


def login_options(site: Site, allow: list[StoredPasskey], use: Use) -> tuple[str, bytes]:
    options = generate_authentication_options(
        rp_id=site.rp_id,
        allow_credentials=[_descriptor(p) for p in allow],
        user_verification=UserVerificationRequirement.REQUIRED if use == "alone" else UserVerificationRequirement.PREFERRED,
        timeout=120_000,
    )
    return options_to_json(options), options.challenge


def verify_login(site: Site, challenge: bytes, credential: dict, passkey: StoredPasskey, use: Use) -> int | None:
    """通過時回傳新的計數器，否則 None。"""
    try:
        result = verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=site.rp_id,
            expected_origin=site.origin,
            credential_public_key=base64url_to_bytes(passkey.public_key),
            credential_current_sign_count=passkey.sign_count,
            require_user_verification=use == "alone",  # 預設 False，單獨登入一定要 True
        )
    except WebAuthnException:
        return None
    return result.new_sign_count
```

FastAPI 端點的順序與 [two-step-login.md](two-step-login.md) 相同：options 端點產生挑戰值並存起來；驗證端點 `admit` → 取走挑戰值 → 用回應的 `id` 找 passkey → `verify_login` → 比較後寫入計數器 → `succeeded` 或 `failed` → 建 session。
