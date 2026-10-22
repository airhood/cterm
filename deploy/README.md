# A private custom domain with HTTPS

This example keeps cterm reachable **only through Tailscale**, while giving the browser an address such as `https://cterm.example.com`. It does not publish the terminal bridge to the public internet. The cterm access token is still required.

Prerequisites: control of the domain's DNS, a trusted TLS certificate, nginx on the same Linux host as cterm, and permission to configure nginx and port 443. The examples below use Cloudflare DNS and Debian/Ubuntu packages. Replace every example domain, IP, and credential path with your own values.

## 1. Point a DNS-only record at the Tailscale address

Find the host's address with `tailscale ip -4`. In Cloudflare DNS, create:

| Type | Name | Value | Proxy status |
| --- | --- | --- | --- |
| A | cterm | Your host's Tailscale IPv4 address | **DNS only** (proxy off) |

Do not change the domain's root records. Cloudflare's public proxy cannot reach a private tailnet address. Devices outside your tailnet may resolve the hostname but cannot connect to that private address. Some local DNS resolvers block public records returning private addresses; test resolution on the actual client if necessary.

## 2. Obtain a trusted certificate using DNS-01

DNS-01 validation proves control of DNS, so the web service does not need a publicly reachable HTTP endpoint. A `.dev` domain requires HTTPS because the entire top-level domain is HSTS-preloaded.

On Debian/Ubuntu, one approach is:

```sh
sudo apt install nginx certbot python3-certbot-dns-cloudflare
```

Create a user-readable-only credentials file outside the checkout, such as `~/.config/cterm/cloudflare.ini`, containing your Cloudflare token:

```ini
dns_cloudflare_api_token = YOUR_RESTRICTED_TOKEN
```

Use a token restricted to DNS editing for the relevant zone. Do not put it in a shell argument, chat, or Git repository. Set its permissions:

```sh
chmod 600 ~/.config/cterm/cloudflare.ini
sudo certbot certonly --dns-cloudflare \
  --dns-cloudflare-credentials "$HOME/.config/cterm/cloudflare.ini" \
  -d cterm.example.com
```

Complete Certbot's account and terms flow yourself. Keep the credential file at its recorded location for automatic renewal. Verify your installation's renewal timer is enabled and configure a successful-renewal deploy hook to reload nginx. Test renewal with `sudo certbot renew --dry-run`.

## 3. Configure nginx

Copy `nginx.conf.example` to your nginx configuration, replacing:

- `<TAILSCALE_IPV4>` with the host's actual tailnet address.
- `cterm.example.com` with your chosen domain in both the server name and certificate paths.

The example binds HTTPS specifically to the Tailscale address and proxies to a localhost-only backend. It preserves the original Host header so WebSocket origin validation still works. Request access logging is disabled because initial authentication URLs contain a token.

Check the configuration with `sudo nginx -t`, then reload nginx. Do not bypass browser certificate warnings; resolve the certificate or hostname mismatch first.

## 4. Start the backend with the browser origin

```sh
cterm stop
cterm start --bind 127.0.0.1 --base-url https://cterm.example.com
```

`--base-url` changes the URL printed by `cterm start` and `cterm url`, and makes the login cookie Secure. It does **not** create DNS records, obtain certificates, or start nginx. Local readiness checks still use the local listener, independently of external DNS or proxy setup.

Open the full access link once from a tailnet-connected phone. After login, the browser displays the clean domain URL. The cookie currently lasts for the browser session; after it is lost, open the full secret link again. A domain does not remove authentication.

## Verify

1. From the phone on Tailscale, confirm the hostname resolves to the host's tailnet IP.
2. Open the printed access link and verify the trusted HTTPS connection and terminal list.
3. Select a test terminal and confirm both screen updates and input. This checks WebSocket proxying as well as HTTP.
4. Disconnect Tailscale on the phone and confirm the private service is unreachable.

No Cloudflare Tunnel, Tailscale Funnel, or router port forwarding is involved.

References: [Cloudflare proxy status](https://developers.cloudflare.com/dns/proxy-status/), [Certbot Cloudflare plugin](https://certbot-dns-cloudflare.readthedocs.io/en/stable/), [Let's Encrypt DNS-01](https://letsencrypt.org/docs/challenge-types/#dns-01-challenge), [nginx WebSocket proxying](https://nginx.org/en/docs/http/websocket.html), [Google Registry .dev HTTPS requirement](https://www.registry.google/domains/dev/).
