/* WebAuthn wire helpers.

   The browser's credential API speaks ArrayBuffers; the server speaks JSON,
   so every id, challenge and signature crosses as base64url. There is no
   dependency here on purpose: it is forty lines, and the same forty lines are
   written out again inline in the login page (auth.py), which cannot import
   anything because /_app sits behind the auth gate. */

export const toBuf = (s) => {
  let b = String(s).replace(/-/g, '+').replace(/_/g, '/');
  while (b.length % 4) b += '=';
  const bin = atob(b);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out.buffer;
};

export const toB64u = (buf) => {
  const bytes = new Uint8Array(buf);
  let s = '';
  for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
};

/** Options from py_webauthn's options_to_json, made ready for the browser. */
export function decodeCreationOptions(o) {
  const p = { ...o, challenge: toBuf(o.challenge), user: { ...o.user, id: toBuf(o.user.id) } };
  if (p.excludeCredentials) p.excludeCredentials = p.excludeCredentials.map((c) => ({ ...c, id: toBuf(c.id) }));
  return p;
}

export function decodeRequestOptions(o) {
  const p = { ...o, challenge: toBuf(o.challenge) };
  if (p.allowCredentials) p.allowCredentials = p.allowCredentials.map((c) => ({ ...c, id: toBuf(c.id) }));
  return p;
}

/** A PublicKeyCredential from create(), as JSON the server can verify. */
export function encodeRegistration(cred) {
  const r = cred.response;
  return {
    id: cred.id,
    rawId: toB64u(cred.rawId),
    type: cred.type,
    authenticatorAttachment: cred.authenticatorAttachment || undefined,
    clientExtensionResults: cred.getClientExtensionResults(),
    response: {
      clientDataJSON: toB64u(r.clientDataJSON),
      attestationObject: toB64u(r.attestationObject),
      // Not every browser reports transports; the server stores [] and the
      // credential still works — it only costs a UI hint next time.
      transports: r.getTransports ? r.getTransports() : []
    }
  };
}

/** The same, for get(). */
export function encodeAssertion(cred) {
  const r = cred.response;
  return {
    id: cred.id,
    rawId: toB64u(cred.rawId),
    type: cred.type,
    authenticatorAttachment: cred.authenticatorAttachment || undefined,
    clientExtensionResults: cred.getClientExtensionResults(),
    response: {
      clientDataJSON: toB64u(r.clientDataJSON),
      authenticatorData: toB64u(r.authenticatorData),
      signature: toB64u(r.signature),
      userHandle: r.userHandle ? toB64u(r.userHandle) : null
    }
  };
}

export const supported = () =>
  typeof window !== 'undefined' && !!window.PublicKeyCredential;
