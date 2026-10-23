# Browser-only remote access with Cloudflare Tunnel

Cloudflare Tunnel connects an outbound process on your Linux PC to a public HTTPS hostname. Your phone needs only a browser. No Tailscale installation, router port forwarding, nginx, or local TLS certificate is needed for this route. The cterm access token is still required. Cloudflare terminates HTTPS and proxies HTTP/WebSocket traffic to your localhost bridge.

## Temporary URL: no domain or Cloudflare account

```sh
cterm tunnel start
cterm url --qr
```

Scan the QR code with your phone camera, or open the complete access link. It includes the secret used to log in. After login, the browser shows the clean URL. Cookies currently last for the browser session; use the full access link again if the cookie is lost.

If `cloudflared` is missing, cterm downloads the official Linux amd64/arm64 binary from `cloudflare/cloudflared` on GitHub, verifies its release SHA-256 digest, and installs it under the private cterm state directory. A system installation on `PATH` takes precedence. This does not require sudo.

Quick Tunnel addresses look like `https://random-words.trycloudflare.com`. They change after restarting the tunnel and stop working when the connector stops. Cloudflare provides no uptime guarantee for Quick Tunnels; they are intended for development. Cloudflare currently limits them to 200 concurrent in-flight requests and does not support SSE (cterm uses WebSockets).

## Your own stable hostname

Your domain's DNS zone must be managed by Cloudflare. Use an unused subdomain, such as `terminal.example.com`.

Create a Cloudflare API token at <https://dash.cloudflare.com/profile/api-tokens> with:

| Type | Permission | Scope |
| --- | --- | --- |
| Account | Cloudflare Tunnel: Edit | The account containing your zone |
| Zone | DNS: Edit | Your domain only |
| Zone | Zone: Read | Your domain only |

Run:

```sh
cterm tunnel start --hostname terminal.example.com
```

On first setup, cterm prompts for the token without echoing it, and stores it at `~/.config/cterm/cloudflare.ini` with mode `600`. Alternatively, provide an existing owner-only file:

```sh
cterm tunnel start --hostname terminal.example.com \
  --api-token-file ~/.config/cterm/cloudflare.ini
```

The file may contain a raw API token or this INI entry:

```ini
dns_cloudflare_api_token = YOUR_RESTRICTED_TOKEN
```

cterm creates a remotely managed tunnel, configures the hostname to reach the localhost bridge, starts the connector, then publishes a proxied CNAME pointing to the tunnel. It does not change your root domain or other website records. Existing DNS at the selected hostname causes an error by default. To deliberately replace a single existing A or CNAME record, add `--replace-dns`. Multiple records or other record types require manual resolution first.

The named tunnel identity and connector token are stored in the private state directory under `tunnels/`. Subsequent starts with the same hostname and backend port reuse these credentials without needing the API token again. Keep the original API token available for setup retries and configuration changes. The tunnel token is passed via a protected file, not a command-line argument.

Cloudflare handles browser-facing HTTPS certificates. If migrating from the [private nginx setup](README.md), its nginx listener and Let's Encrypt certificate are no longer needed for this public route. Remove only the old cterm-specific nginx site and renewal configuration if you no longer use them; do not remove unrelated sites or certificates.

## Manage access

```sh
cterm tunnel status
cterm tunnel stop
```

Stopping the tunnel also stops the web bridge, while terminal jobs and registrations remain intact. Named tunnel configuration and DNS remain for reuse. To remove a named tunnel permanently, stop it, delete its tunnel and hostname record in Cloudflare, and remove that hostname's files from `STATE/tunnels/` (find `STATE` with `cterm status`). API tokens can be revoked from Cloudflare's API Tokens page.

Both the connector and bridge run in the background as your user. They stop on host reboot; start them again with `cterm tunnel start` and the same `--hostname` if applicable. This command does not install a boot service. `cterm stop` alone stops only the bridge; use `cterm tunnel stop` to shut down both processes.

Keep access links and QR codes private. The hostname is publicly reachable; the secret token protects terminal access. Cloudflare is a traffic intermediary. You can additionally configure Cloudflare Access in your account if you want identity-based login before requests reach cterm.

If connection setup fails, cterm stops its new connector and restores the previous bridge configuration. No terminal jobs are stopped. Check `STATE/tunnel.log`; do not publish logs without reviewing them. Your network must allow outbound TCP port 7844 to Cloudflare, as well as HTTPS for setup/downloads. DNS changes may take time to reach phone resolvers.

References: [Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/), [named tunnel setup and API](https://developers.cloudflare.com/tunnel/get-started/), [cloudflared token files](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/run-parameters/#token-file).
