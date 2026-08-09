/* Meridian — Cloudflare Worker: passcode gate + static assets.
   Secrets to set on the Worker (Settings → Variables and Secrets, type "Secret"):
     PASSCODE      — the passcode typed on a new device
     COOKIE_SECRET — long random string used to sign the auth cookie
   The gate stays OFF until both secrets exist. Unlocked devices stay signed
   in for 90 days via a signed HttpOnly cookie. */

const COOKIE = "kday_auth";
const NINETY_DAYS = 90 * 24 * 60 * 60;

async function hmac(secret, value) {
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(value));
  return btoa(String.fromCharCode(...new Uint8Array(sig)))
    .replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

async function validCookie(request, env) {
  const cookies = request.headers.get("Cookie") ?? "";
  const match = cookies.match(new RegExp(`${COOKIE}=([^;]+)`));
  if (!match) return false;
  const [expiry, sig] = match[1].split(".");
  if (!expiry || !sig) return false;
  if (Number(expiry) < Date.now() / 1000) return false;
  return sig === (await hmac(env.COOKIE_SECRET, expiry));
}

function loginPage(wrong = false) {
  return new Response(`<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Meridian</title>
<style>
  body{margin:0;background:#FDFDFB;color:#161310;font-family:"Helvetica Neue",Helvetica,Arial,sans-serif;
       display:flex;align-items:center;justify-content:center;min-height:100vh}
  .card{text-align:center;padding:40px}
  .monogram{width:44px;height:44px;margin:0 auto 16px;border:1px solid #161310;border-radius:50%;
       display:flex;align-items:center;justify-content:center;font-family:Didot,"Bodoni 72",Georgia,serif;font-size:20px}
  .wordmark{font-size:13px;letter-spacing:.42em;text-transform:uppercase;font-weight:500;margin-left:.42em}
  form{margin-top:30px}
  input{font-family:Didot,"Bodoni 72",Georgia,serif;font-size:22px;text-align:center;letter-spacing:.2em;
       border:none;border-bottom:1px solid #161310;background:transparent;padding:8px 4px;width:200px;outline:none}
  button{display:block;margin:26px auto 0;font-size:10.5px;letter-spacing:.22em;text-transform:uppercase;
       background:none;border:1px solid #161310;padding:10px 26px;cursor:pointer;color:#161310}
  button:hover{background:#161310;color:#FDFDFB}
  .err{margin-top:18px;font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:#93392F}
</style></head><body>
<div class="card">
  <div class="monogram">M</div>
  <div class="wordmark">Meridian</div>
  <form method="POST" action="/login">
    <input type="password" name="passcode" autofocus autocomplete="current-password" aria-label="Passcode">
    <button type="submit">Unlock</button>
  </form>
  ${wrong ? '<div class="err">Incorrect passcode</div>' : ""}
</div></body></html>`, {
    status: 401,
    headers: { "Content-Type": "text/html; charset=utf-8" },
  });
}

export default {
  async fetch(request, env) {
    if (!env.PASSCODE || !env.COOKIE_SECRET) return env.ASSETS.fetch(request);

    const url = new URL(request.url);

    if (url.pathname === "/login" && request.method === "POST") {
      const form = await request.formData();
      if (form.get("passcode") === env.PASSCODE) {
        const expiry = String(Math.floor(Date.now() / 1000) + NINETY_DAYS);
        const sig = await hmac(env.COOKIE_SECRET, expiry);
        return new Response(null, {
          status: 303,
          headers: {
            Location: "/",
            "Set-Cookie": `${COOKIE}=${expiry}.${sig}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${NINETY_DAYS}`,
          },
        });
      }
      return loginPage(true);
    }

    if (await validCookie(request, env)) return env.ASSETS.fetch(request);
    return loginPage();
  },
};
